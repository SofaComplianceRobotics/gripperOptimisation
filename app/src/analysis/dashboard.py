"""
dashboard.py — Unified web interface: configure, generate, optimise, and analyse.

All lab workflows are accessible from a single browser window.
Tabs: Config | Generate | Scenes | Optimise | Performance | Progress | Parameter Bounds
"""

import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

try:
    from dash import Dash, dcc, html, callback, Input, Output, State, ALL
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    DASH_AVAILABLE = True
except ImportError:
    DASH_AVAILABLE = False

# ── Paths ──────────────────────────────────────────────────────
LAB_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = LAB_ROOT / "app" / "src"
TRIALS_DIR = LAB_ROOT / "runtime" / "trials"
CONFIG_FILE = LAB_ROOT / "config" / "lab_config.jsonc"
OPTIMIZE_SCRIPT = LAB_ROOT / "app" / "src" / "optimization" / "optimize.py"
GENERATE_SCRIPT = LAB_ROOT / "app" / "src" / "generation" / "generate_gripper.py"
GENERATE_FINE_SCRIPT = LAB_ROOT / "app" / "src" / "generation" / "generate_gripper_fine.py"
INVERSE_SCENE = LAB_ROOT / "lab_shapeOPT_inverse.py"
RECORDING_SCENE = LAB_ROOT / "lab_shapeOPT_recording.py"
SESSION_CONFIG_FILE = LAB_ROOT / "runtime" / "session_config.json"
_LOG_DIR = LAB_ROOT / "runtime" / "logs"
CENTERPARTS_DIR = LAB_ROOT.parent.parent / "data" / "meshes" / "centerparts"

ANALYSIS_DIR = Path(__file__).resolve().parent

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(ANALYSIS_DIR))

# Suppress noisy server logs
os.environ.pop("WERKZEUG_RUN_MAIN", None)
os.environ.pop("WERKZEUG_SERVER_FD", None)
logging.getLogger("werkzeug").setLevel(logging.ERROR)
logging.getLogger("dash").setLevel(logging.ERROR)

from analyze_io import load_all_trials, load_gen_summaries
from analyze_plotting import (
    _collect_all_test_names,
    _compute_contributions,
    compute_plot_data,
    _build_bar_traces,
    _build_hover_overlay,
    _build_final_ticks,
    _build_avg_traces,
    C_BANNER,
    C_BG,
    C_BORDER,
    C_FINAL,
    C_AVG,
    C_BEST,
)
from analyze_config import CENTERED_AVG_HALF_WINDOW, LIVE_REFRESH_SECONDS

# ── Caches & module-level state ────────────────────────────────
_MAX_SCORE_CACHE: dict[str, float] = {}
_DATA_CACHE: dict = {"records": [], "summaries": [], "last_load": 0.0}

# Running subprocesses keyed by role ("optimize", "generate")
_PROCS: dict[str, subprocess.Popen | None] = {
    "optimize": None,
    "generate": None,
}


def install_dependencies():
    """Auto-install missing dependencies."""
    packages = ["dash"]
    for pkg in packages:
        try:
            __import__(pkg.replace("-", "_"))
        except ImportError:
            print(f"[info] Installing {pkg}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])


if not DASH_AVAILABLE:
    install_dependencies()
    from dash import Dash, dcc, html, callback, Input, Output, State, ALL
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots


# ─────────────────────────────────────────────────────────────
# Process management helpers
# ─────────────────────────────────────────────────────────────


def _proc_running(name: str) -> bool:
    proc = _PROCS.get(name)
    return proc is not None and proc.poll() is None


def _start_proc(name: str, script: Path, env: dict | None = None) -> str:
    if _proc_running(name):
        return f"Already running (PID {_PROCS[name].pid})."
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = _LOG_DIR / f"{name}.log"
        log_file = open(log_path, "w", encoding="utf-8")
        run_env = env if env is not None else os.environ.copy()
        # Force UTF-8 stdout in the subprocess so unicode characters don't crash on Windows
        run_env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.Popen(
            [sys.executable, str(script)],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=str(script.parent),
            env=run_env,
        )
        _PROCS[name] = proc
        return f"Started (PID {proc.pid})."
    except Exception as exc:
        return f"Error starting process: {exc}"


def _stop_proc(name: str) -> str:
    proc = _PROCS.get(name)
    if proc is None or proc.poll() is not None:
        return "Not running."
    try:
        proc.kill()
        _PROCS[name] = None
        return "Stopped."
    except Exception as exc:
        return f"Error stopping process: {exc}"


def _read_proc_log(name: str, tail: int = 150) -> str:
    log_path = _LOG_DIR / f"{name}.log"
    if not log_path.exists():
        return ""
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        return "\n".join(lines[-tail:])
    except Exception:
        return ""


def _launch_sofa_scene(scene_file: Path, extra_env: dict | None = None) -> str:
    # Interactive scenes require the emiolabs SOFA (ImGui + emiolabs plugins).
    # The custom batch SOFA used for optimisation does not have these.
    runsofa = os.environ.get(
        "EMIOLABS_RUNSOFA_EXE",
        r"C:\Users\Cesar\AppData\Local\Programs\emio-labs\resources\sofa\bin\runSofa.exe",
    )
    if not os.path.isfile(runsofa):
        return f"runSofa.exe not found at: {runsofa}"

    # Derive the emiolabs SOFA root from the executable path (bin/runSofa.exe → sofa/)
    emiolabs_sofa_root = str(Path(runsofa).parents[1])
    assets_root = str(LAB_ROOT.parent.parent)

    env = os.environ.copy()

    # Override SOFA_ROOT / SOFAPYTHON3_ROOT so the emiolabs runSofa.exe loads its own
    # Python packages instead of the custom build's — prevents 'No module named Sofa.Helper'
    env["SOFA_ROOT"] = emiolabs_sofa_root
    env["SOFAPYTHON3_ROOT"] = emiolabs_sofa_root

    # Drop vars that reference the custom Python 3.12 / batch-SOFA build
    for _k in ("SOFA_SITE_PACKAGES", "SOFA_PYTHON_PATH", "RUNSOFA_EXE"):
        env.pop(_k, None)

    if extra_env:
        env.update(extra_env)

    try:
        proc = subprocess.Popen(
            [runsofa, "-l", "SofaPython3", "-g", "imgui", str(scene_file)],
            env=env,
            cwd=assets_root,
        )
        return f"Launched SOFA (PID {proc.pid})."
    except Exception as exc:
        return f"Failed to launch: {exc}"


def _write_session_config(recording_test: str) -> None:
    SESSION_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_CONFIG_FILE.write_text(
        json.dumps({"recording_test": recording_test}, indent=2),
        encoding="utf-8",
    )


def _load_config_text() -> str:
    try:
        return CONFIG_FILE.read_text(encoding="utf-8")
    except Exception:
        return "{}"


# ─────────────────────────────────────────────────────────────
# Tab: Config
# ─────────────────────────────────────────────────────────────

_LOG_STYLE = {
    "height": "420px",
    "overflowY": "auto",
    "background": "#1e1e1e",
    "color": "#d4d4d4",
    "padding": "12px",
    "borderRadius": "6px",
    "fontSize": "0.82rem",
    "whiteSpace": "pre-wrap",
    "wordBreak": "break-word",
    "fontFamily": "monospace",
}


def build_config_tab() -> html.Div:
    return html.Div(
        [
            html.H3("Gripper Configuration", className="mb-2"),
            html.P(
                "Edit lab_config.jsonc parameters. Click Save to write to disk.",
                className="text-muted mb-3",
            ),
            dcc.Textarea(
                id="config-textarea",
                value=_load_config_text(),
                style={
                    "width": "100%",
                    "height": "520px",
                    "fontFamily": "monospace",
                    "fontSize": "0.88rem",
                    "border": "1px solid #ced4da",
                    "borderRadius": "6px",
                    "padding": "10px",
                },
            ),
            html.Div(
                [
                    html.Button(
                        "Save",
                        id="config-save-btn",
                        n_clicks=0,
                        className="btn btn-primary me-3",
                    ),
                    html.Span(id="config-save-status", className="align-middle"),
                ],
                className="mt-2 d-flex align-items-center",
            ),
        ],
        className="p-3",
    )


# ─────────────────────────────────────────────────────────────
# Tab: Generate
# ─────────────────────────────────────────────────────────────


def build_generate_tab() -> html.Div:
    return html.Div(
        [
            html.H3("Generate 3D Model", className="mb-2"),
            html.P(
                "Generate STL/VTK/JSON files from the current lab_config.jsonc.",
                className="text-muted mb-3",
            ),
            html.Div(
                [
                    html.Button(
                        "Generate (sim mesh)",
                        id="gen-btn",
                        n_clicks=0,
                        className="btn btn-primary me-2",
                    ),
                    html.Button(
                        "Generate Fine (print mesh)",
                        id="gen-fine-btn",
                        n_clicks=0,
                        className="btn btn-secondary me-2",
                    ),
                    html.Button(
                        "Stop",
                        id="gen-stop-btn",
                        n_clicks=0,
                        className="btn btn-danger",
                    ),
                ],
                className="mb-3",
            ),
            html.Div(id="gen-status", className="mb-2 fw-semibold"),
            html.Pre(id="gen-log", style=_LOG_STYLE),
            dcc.Interval(id="gen-interval", interval=800, n_intervals=0),
            html.Hr(className="mt-3"),
            html.H6("Open generated files", className="mb-2 text-muted"),
            html.Div(
                [
                    html.Div(
                        [
                            html.Small("Sim mesh", className="d-block text-muted mb-1"),
                            html.Button(
                                "Open STL",
                                id="gen-open-stl-btn",
                                n_clicks=0,
                                className="btn btn-outline-secondary btn-sm me-2",
                            ),
                            html.Button(
                                "Open JSON",
                                id="gen-open-json-btn",
                                n_clicks=0,
                                className="btn btn-outline-secondary btn-sm",
                            ),
                        ],
                        className="me-4",
                    ),
                    html.Div(
                        [
                            html.Small("Print mesh", className="d-block text-muted mb-1"),
                            html.Button(
                                "Open STL",
                                id="gen-open-fine-stl-btn",
                                n_clicks=0,
                                className="btn btn-outline-secondary btn-sm",
                            ),
                        ],
                    ),
                ],
                className="d-flex align-items-start mb-2",
            ),
            html.Div(id="gen-open-status", className="small text-muted"),
        ],
        className="p-3",
    )


# ─────────────────────────────────────────────────────────────
# Tab: Scenes
# ─────────────────────────────────────────────────────────────


def build_scenes_tab(catalog: dict) -> html.Div:
    test_options = [
        {"label": spec.label, "value": name} for name, spec in catalog.items()
    ]
    default_test = next(iter(catalog), "")

    return html.Div(
        [
            html.H3("SOFA Scenes", className="mb-3"),
            html.Div(
                [
                    html.H5("Inverse Control"),
                    html.P(
                        "Interactive inverse-mode scene — drag the end-effector target to control the gripper.",
                        className="text-muted",
                    ),
                    html.Button(
                        "Launch Inverse Scene",
                        id="scene-inverse-btn",
                        n_clicks=0,
                        className="btn btn-primary",
                    ),
                ],
                className="p-3 mb-3 border rounded",
            ),
            html.Div(
                [
                    html.H5("Motor Recording"),
                    html.P(
                        "Record motor trajectories for a test target. The target is saved before launching.",
                        className="text-muted",
                    ),
                    html.Div(
                        [
                            html.Label("Target test:", className="me-2 fw-semibold"),
                            dcc.Dropdown(
                                id="scene-recording-test",
                                options=test_options,
                                value=default_test,
                                clearable=False,
                                style={"width": "300px"},
                            ),
                        ],
                        className="d-flex align-items-center mb-3",
                    ),
                    html.Button(
                        "Set Target & Launch Recording Scene",
                        id="scene-recording-btn",
                        n_clicks=0,
                        className="btn btn-primary",
                    ),
                ],
                className="p-3 border rounded",
            ),
            html.Div(id="scene-status", className="mt-3 fw-semibold"),
        ],
        className="p-3",
    )


# ─────────────────────────────────────────────────────────────
# Tab: Optimise
# ─────────────────────────────────────────────────────────────

_PIE_PALETTE = [
    "#4c8bf5", "#e84393", "#34a853", "#fa7b17",
    "#9c27b0", "#00bcd4", "#ff5722", "#8bc34a",
]


def _equal_split(n: int) -> list[int]:
    if n == 0:
        return []
    base = 100 // n
    rem = 100 - base * n
    return [base + (1 if i < rem else 0) for i in range(n)]


def build_optimise_tab(catalog: dict) -> html.Div:
    names = list(catalog.keys())
    n = len(names)
    any_default = any(spec.default_selected for spec in catalog.values())

    selected_names = [
        name for name, spec in catalog.items()
        if spec.default_selected or not any_default
    ]
    weights = _equal_split(len(selected_names))
    initial_store: dict[str, int] = {}
    wi = 0
    for name in names:
        if name in selected_names:
            initial_store[name] = weights[wi]
            wi += 1
        else:
            initial_store[name] = 0

    test_rows = []
    for i, (name, spec) in enumerate(catalog.items()):
        pre_selected = spec.default_selected or not any_default
        test_rows.append(
            html.Div(
                [
                    dcc.Checklist(
                        id={"type": "test-check", "test": name},
                        options=[{"label": f" {spec.label}", "value": name}],
                        value=[name] if pre_selected else [],
                        style={
                            "display": "inline-flex",
                            "alignItems": "center",
                            "minWidth": "200px",
                            "flexShrink": 0,
                        },
                        className="me-2",
                    ),
                    html.Div(
                        dcc.Slider(
                            id={"type": "weight-slider", "test": name},
                            min=0,
                            max=100,
                            step=1,
                            value=initial_store[name],
                            marks=None,
                            tooltip={"placement": "bottom", "always_visible": True},
                            updatemode="drag",
                        ),
                        style={"flexGrow": 1},
                    ),
                ],
                className="d-flex align-items-center mb-3",
                style={"gap": "8px"},
            )
        )

    return html.Div(
        [
            html.H3("Optimisation", className="mb-2"),
            # Weights store — single source of truth, always sums to 100 across selected tests
            dcc.Store(id="opt-weights-store", data=initial_store),
            html.Div(
                [
                    html.Div(
                        [
                            html.P(
                                "Drag a slider — the others adjust so the total stays at 100%.",
                                className="text-muted mb-3",
                            ),
                            html.Div(test_rows, className="mb-2"),
                            html.Div(
                                [
                                    html.Button(
                                        "Equal split",
                                        id="opt-equal-btn",
                                        n_clicks=0,
                                        className="btn btn-outline-secondary btn-sm me-2",
                                    ),
                                    html.Button(
                                        "Normalize",
                                        id="opt-normalize-btn",
                                        n_clicks=0,
                                        className="btn btn-outline-secondary btn-sm",
                                    ),
                                ],
                                className="mb-3",
                            ),
                        ],
                        className="col-12 col-md-7",
                    ),
                    html.Div(
                        dcc.Graph(
                            id="opt-pie",
                            config={"displayModeBar": False},
                            style={"height": "320px"},
                        ),
                        className="col-12 col-md-5",
                    ),
                ],
                className="row g-3 mb-3",
            ),
            html.Div(id="opt-weight-status", className="mb-3"),
            html.Div(
                [
                    html.Button(
                        "Start Optimisation",
                        id="opt-start-btn",
                        n_clicks=0,
                        className="btn btn-success me-2",
                    ),
                    html.Button(
                        "Stop",
                        id="opt-stop-btn",
                        n_clicks=0,
                        className="btn btn-danger",
                    ),
                ],
                className="mb-3",
            ),
            html.Div(id="opt-status", className="mb-2 fw-semibold"),
            html.Pre(id="opt-log", style=_LOG_STYLE),
            dcc.Interval(id="opt-interval", interval=1000, n_intervals=0),
        ],
        className="p-3",
    )


# ─────────────────────────────────────────────────────────────
# Tab: Performance & Leaderboard
# ─────────────────────────────────────────────────────────────


def build_performance_tab() -> html.Div:
    return html.Div(
        [
            html.H3("Performance & Leaderboard", className="mb-3"),
            dcc.Graph(id="performance-graph", style={"height": "600px"}),
            html.Div(id="trial-detail-panel", className="my-3"),
            html.Hr(),
            html.Div(id="leaderboard-table", className="mt-4"),
            dcc.Interval(
                id="performance-interval",
                interval=int(max(1.0, LIVE_REFRESH_SECONDS) * 1000),
                n_intervals=0,
            ),
        ],
        className="p-3",
    )


# ─────────────────────────────────────────────────────────────
# Tab: Parameter Bounds
# ─────────────────────────────────────────────────────────────


def build_param_bounds_tab() -> html.Div:
    return html.Div(
        [
            html.H3("Parameter Bounds Monitor", className="mb-3"),
            html.P("Live tracking of parameter values within optimization bounds."),
            dcc.Graph(id="param-bounds-graph"),
            dcc.Interval(
                id="bounds-interval",
                interval=int(max(1.0, LIVE_REFRESH_SECONDS) * 1000),
                n_intervals=0,
            ),
        ],
        className="p-3",
    )


# ─────────────────────────────────────────────────────────────
# Tab: Progress Monitor
# ─────────────────────────────────────────────────────────────


def build_progress_tab() -> html.Div:
    return html.Div(
        [
            html.H3("Optimization Progress", className="mb-3"),
            html.Div(
                [
                    html.Button(
                        "Jump to earliest unfinished trial",
                        id="jump-running-trial",
                        n_clicks=0,
                        className="btn btn-primary btn-sm",
                    ),
                ],
                className="d-flex align-items-center gap-2 mb-3",
                style={
                    "position": "sticky",
                    "top": "0",
                    "zIndex": 20,
                    "background": "#ffffff",
                    "padding": "8px 0",
                },
            ),
            dcc.Store(id="jump-auto-enabled", data=False),
            html.Div(id="progress-stats", className="mb-3"),
            html.Div(id="progress-grid"),
            dcc.Store(id="jump-running-target-store"),
            html.Div(id="jump-running-target-output", style={"display": "none"}),
            html.Div(id="jump-top-output", style={"display": "none"}),
            html.Div(
                [
                    html.Button(
                        "Top",
                        id="jump-top-button",
                        n_clicks=0,
                        className="btn btn-sm btn-secondary me-2",
                    ),
                    html.Button(
                        "Auto-jump: Off",
                        id="jump-auto-toggle",
                        n_clicks=0,
                        className="btn btn-sm btn-outline-primary",
                    ),
                ],
                style={
                    "position": "fixed",
                    "right": "16px",
                    "bottom": "16px",
                    "zIndex": 9999,
                    "boxShadow": "0 6px 18px rgba(0,0,0,0.12)",
                    "padding": "8px",
                    "borderRadius": "8px",
                    "background": "#ffffff",
                },
            ),
            dcc.Interval(
                id="progress-interval",
                interval=int(max(1.0, LIVE_REFRESH_SECONDS) * 1000),
                n_intervals=0,
            ),
        ],
        className="p-3",
    )


# ─────────────────────────────────────────────────────────────
# Callback helpers
# ─────────────────────────────────────────────────────────────


def _get_test_max_score(test_name: str) -> float:
    if not test_name:
        return 1.0
    if test_name in _MAX_SCORE_CACHE:
        return _MAX_SCORE_CACHE[test_name]
    try:
        from labtests.registry import get_test_catalog

        catalog = get_test_catalog()
        spec = catalog.get(test_name)
        result = spec.max_score if spec else 1.0
    except Exception:
        result = 1.0
    _MAX_SCORE_CACHE[test_name] = result
    return result


def _load_data():
    try:
        now = time.time()
        if _DATA_CACHE.get("records") and (
            now - float(_DATA_CACHE.get("last_load", 0))
        ) < max(0.5, float(LIVE_REFRESH_SECONDS)):
            return _DATA_CACHE["records"], _DATA_CACHE["summaries"]

        records = load_all_trials()
        summaries = load_gen_summaries()
        _DATA_CACHE["records"] = records
        _DATA_CACHE["summaries"] = summaries
        _DATA_CACHE["last_load"] = now
        return records, summaries
    except Exception as exc:
        print(f"[warn] Error loading data: {exc}")
        return (
            _DATA_CACHE.get("records", []) or [],
            _DATA_CACHE.get("summaries", []) or [],
        )


def _current_generation_records(records: list[dict]) -> list[dict]:
    if not records:
        return []
    current_gen = max(
        (record.get("gen_index", -1) for record in records),
        default=-1,
    )
    if current_gen < 0:
        return []
    result = [r for r in records if r.get("gen_index", -1) == current_gen]
    return sorted(result, key=lambda r: r.get("trial_index", 0))


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_trial_state(trial_record: dict) -> dict | None:
    trial_path = (
        TRIALS_DIR
        / trial_record.get("gen_name", "")
        / trial_record.get("trial_name", "")
        / "trial_state.json"
    )
    if not trial_path.exists():
        return None
    return _read_json(trial_path)


def _run_progress_pct(run: dict) -> float:
    state = str(run.get("state", "")).lower()
    if state in {"done", "failed", "error", "pruned", "skipped", "cancelled"}:
        return 100.0
    current_frame = run.get("current_frame")
    total_frames = run.get("total_frames")
    if (
        isinstance(current_frame, (int, float))
        and isinstance(total_frames, (int, float))
        and total_frames > 0
    ):
        return max(0.0, min(100.0, 100.0 * float(current_frame) / float(total_frames)))
    return 0.0


def _state_color(state: str) -> str:
    state = state.lower()
    if state in {"done"}:
        return "#2f9e44"
    if state in {"running", "launching"}:
        return "#0270ff"
    if state in {"failed", "error", "pruned", "skipped", "cancelled"}:
        return "#e03131"
    return "#868e96"


def _get_trial_actual_state(trial_record: dict) -> str:
    raw_state = _load_trial_state(trial_record)
    if raw_state is None and not trial_record.get("is_complete"):
        return "waiting"
    trial_state = raw_state or {}
    runs = trial_state.get("runs") if isinstance(trial_state.get("runs"), list) else []

    state = str(
        trial_state.get("state")
        or ("done" if trial_record.get("is_complete") else "running")
    ).lower()

    terminal = {"done", "failed", "error", "pruned", "skipped", "cancelled"}
    if (
        state not in terminal
        and runs
        and all(
            str(r.get("state", "")).lower() in terminal
            for r in runs
            if isinstance(r, dict)
        )
    ):
        state = "done"

    return state


def _build_progress_card(trial_record: dict) -> html.Div:
    trial_state = _load_trial_state(trial_record) or {}
    runs = trial_state.get("runs") if isinstance(trial_state.get("runs"), list) else []
    trial_index = trial_record.get("trial_index", 0)
    final_score = trial_record.get("final_score")

    state = _get_trial_actual_state(trial_record)

    run_rows = []
    if runs:
        for run in runs:
            if not isinstance(run, dict):
                continue
            run_state = str(run.get("state", "not-started")).lower()
            bar_color = _state_color(run_state)

            test_name = run.get("test_name") or run.get("run_label") or "run"
            max_score = _get_test_max_score(test_name)

            live_val, is_final = _get_live_score(run)
            if live_val is not None and run_state not in {"not-started"}:
                bar_pct = (
                    max(0.0, min(100.0, live_val / max_score * 100))
                    if max_score > 0
                    else 0.0
                )
                score_label = f"{live_val:.3f}" if is_final else f"~{live_val:.3f}"
            else:
                bar_pct = 0.0
                score_label = "--"

            run_idx = run.get("test_run_index")
            run_total = run.get("test_run_total")
            count_str = (
                f" {run_idx}/{run_total} |"
                if run_idx is not None and run_total is not None and run_total > 1
                else ""
            )
            label_text = f"{test_name} | {count_str} {score_label} | {run_state}"

            run_rows.append(
                html.Div(
                    [
                        html.Span(
                            label_text,
                            style={
                                "width": "260px",
                                "minWidth": "260px",
                                "flexShrink": 0,
                                "fontSize": "0.82rem",
                                "color": bar_color,
                                "fontWeight": 600,
                                "whiteSpace": "nowrap",
                                "overflow": "hidden",
                                "textOverflow": "ellipsis",
                            },
                        ),
                        html.Div(
                            html.Div(
                                style={
                                    "width": f"{bar_pct:.1f}%",
                                    "height": "100%",
                                    "background": bar_color,
                                    "borderRadius": "999px",
                                    "transition": "width 600ms ease",
                                    "willChange": "width",
                                    "minWidth": "0",
                                }
                            ),
                            style={
                                "flexGrow": 1,
                                "height": "20px",
                                "background": "#e9ecef",
                                "borderRadius": "999px",
                                "overflow": "hidden",
                            },
                        ),
                    ],
                    style={
                        "display": "flex",
                        "alignItems": "center",
                        "gap": "12px",
                        "marginBottom": "6px",
                    },
                )
            )

    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Div("Trial", className="text-muted"),
                            html.Div(str(trial_index), className="fw-semibold"),
                        ],
                        className="col-12 col-md-4",
                    ),
                    html.Div(
                        [
                            html.Div("State", className="text-muted"),
                            html.Div(
                                state,
                                style={"color": _state_color(state), "fontWeight": 600},
                            ),
                        ],
                        className="col-12 col-md-4",
                    ),
                    html.Div(
                        [
                            html.Div("Score", className="text-muted"),
                            html.Div(
                                (
                                    f"{final_score:.4f}"
                                    if isinstance(final_score, (int, float))
                                    else "--"
                                ),
                                className="fw-semibold",
                            ),
                        ],
                        className="col-12 col-md-4",
                    ),
                ],
                className="row g-3 mb-3",
            ),
            html.Div(
                run_rows
                or [html.Div("No run details available yet.", className="text-muted")]
            ),
            html.Hr(),
        ],
        id=f"trial-card-{trial_record.get('gen_index', 0):04d}-{trial_record.get('trial_index', 0):04d}",
        className="p-3 border rounded",
        style={"background": "#fafbfc"},
    )


def _build_trial_detail(state: dict, gen_name: str, trial_name: str) -> html.Div:
    final_score = state.get("final_score", 0.0) or 0.0
    test_scores: dict = state.get("test_scores") or {}

    header = html.Div(
        [
            html.Span(f"{gen_name} / {trial_name}", className="fw-semibold me-3"),
            html.Span(
                f"Final score: {final_score:.2f} / 100",
                style={"color": C_FINAL, "fontWeight": 700},
            ),
        ],
        className="d-flex align-items-center mb-3",
        style={"fontSize": "1.05rem"},
    )

    rows = []
    for test_name, info in sorted(
        test_scores.items(), key=lambda kv: kv[1].get("weight_pct", 0), reverse=True
    ):
        if not isinstance(info, dict):
            continue
        agg = float(info.get("aggregate_score", 0.0) or 0.0)
        max_s = float(info.get("max_score", 1.0) or 1.0)
        weight = float(info.get("weight_pct", 0.0) or 0.0)
        norm = min(agg / max_s, 1.0) if max_s > 0 else 0.0
        contribution = norm * weight
        success_pct = norm * 100
        run_scores: list = info.get("run_scores") or []
        run_total = int(info.get("run_total", 1))

        bar_pct = min(norm * 100, 100)

        run_cells = []
        if run_total > 1 and run_scores:
            for idx, rs in enumerate(run_scores):
                if rs == float("-inf") or rs is None:
                    label, color = "FAIL", "#e03131"
                else:
                    label, color = f"{rs:.3f}", "#2f9e44"
                run_cells.append(
                    html.Span(
                        f"run {idx + 1}: {label}",
                        style={
                            "color": color,
                            "background": "#f1f3f5",
                            "borderRadius": "4px",
                            "padding": "2px 8px",
                            "fontSize": "0.78rem",
                            "fontWeight": 600,
                            "marginRight": "6px",
                        },
                    )
                )

        rows.append(
            html.Div(
                [
                    html.Div(
                        [
                            html.Span(test_name, className="fw-semibold me-2"),
                            html.Span(
                                f"{weight:.0f}% of score",
                                style={
                                    "background": "#e7f5ff",
                                    "color": "#1971c2",
                                    "borderRadius": "999px",
                                    "padding": "1px 10px",
                                    "fontSize": "0.78rem",
                                    "fontWeight": 600,
                                },
                            ),
                        ],
                        className="d-flex align-items-center mb-1",
                    ),
                    html.Div(
                        html.Div(
                            style={
                                "width": f"{bar_pct:.1f}%",
                                "height": "100%",
                                "background": C_BANNER,
                                "borderRadius": "999px",
                                "transition": "width 400ms ease",
                            }
                        ),
                        style={
                            "height": "10px",
                            "background": "#dee2e6",
                            "borderRadius": "999px",
                            "overflow": "hidden",
                            "marginBottom": "4px",
                        },
                    ),
                    html.Div(
                        [
                            html.Span(
                                f"{agg:.3f} / {max_s:.3f}",
                                style={"fontWeight": 600, "marginRight": "6px"},
                            ),
                            html.Span(
                                f"→ {success_pct:.1f}% success rate",
                                className="text-muted me-3",
                            ),
                            html.Span(
                                f"earned {contribution:.2f} / {weight:.1f} pts",
                                style={"color": C_FINAL, "fontWeight": 600},
                            ),
                        ],
                        style={"fontSize": "0.82rem"},
                        className="mb-1",
                    ),
                    (
                        html.Div(run_cells, className="d-flex flex-wrap")
                        if run_cells
                        else html.Div()
                    ),
                ],
                className="mb-3 pb-3",
                style={"borderBottom": f"1px solid {C_BORDER}"},
            )
        )

    return html.Div(
        [header] + rows,
        style={
            "background": "#f8f9fa",
            "border": f"1px solid {C_BORDER}",
            "borderRadius": "8px",
            "padding": "16px 20px",
        },
    )


def _build_leaderboard_html(records: list[dict]) -> html.Div:
    valid = [r for r in records if not r.get("failed", False)]
    sorted_records = sorted(valid, key=lambda r: r.get("final_score", 0), reverse=True)

    if not sorted_records:
        return html.Div("No valid trials found.", className="text-muted")

    rows = []
    for rank, record in enumerate(sorted_records[:10], 1):
        label = f"{record.get('gen_name', '')} / {record.get('trial_name', '')}"
        score = record.get("final_score", 0.0)
        marker = " ⭐ BEST" if rank == 1 else ""
        rows.append(
            html.Tr(
                [
                    html.Td(str(rank), className="fw-bold"),
                    html.Td(label),
                    html.Td(f"{score:.4f}", className="text-end"),
                    html.Td(marker, className="text-success fw-bold"),
                ]
            )
        )

    return html.Div(
        [
            html.H5("Top 10 Trials", className="mt-3 mb-2"),
            html.Table(
                [
                    html.Thead(
                        html.Tr(
                            [
                                html.Th("Rank"),
                                html.Th("Trial"),
                                html.Th("Score"),
                                html.Th("Status"),
                            ]
                        )
                    ),
                    html.Tbody(rows),
                ],
                className="table table-striped table-sm",
            ),
        ]
    )


def _build_performance_graph(records: list[dict], summaries: list[dict]) -> go.Figure:
    if not records:
        return go.Figure().add_annotation(text="No data available")

    try:
        all_test_names = _collect_all_test_names(records)
        plot_data = compute_plot_data(records, all_test_names)

        xs = plot_data["xs"]
        bar_width = max(0.4, (max(xs) - min(xs) + 1) / len(xs) * 0.8) if xs else 0.8

        bar_traces = _build_bar_traces(records, plot_data, all_test_names)
        hover_overlay = _build_hover_overlay(records, plot_data, all_test_names, bar_width)
        final_ticks = _build_final_ticks(plot_data, bar_width)
        avg_traces = _build_avg_traces(plot_data, all_test_names)
        all_traces = bar_traces + [hover_overlay, final_ticks] + avg_traces

        fig = go.Figure(data=all_traces)
        fig.update_layout(
            title="Performance Overview: Per-Test Contributions & Score Trends",
            xaxis_title="Trial",
            yaxis_title="Score / Contribution",
            barmode="relative",
            hovermode="x unified",
            height=600,
            margin={"l": 50, "r": 50, "t": 50, "b": 50},
            plot_bgcolor=C_BG,
            paper_bgcolor=C_BG,
            uirevision="performance-graph",
        )
        try:
            fig.layout.transition = dict(duration=600, easing="cubic-in-out")
        except Exception:
            pass
        return fig
    except Exception as exc:
        print(f"[warn] Error building performance graph: {exc}")
        return go.Figure().add_annotation(text=f"Error: {exc}")


def _build_param_bounds_graph(show_heatmap: bool = False) -> go.Figure:
    try:
        from optimization.optimize_config import PARAM_SPECS

        active_specs = [p for p in PARAM_SPECS if p["min"] < p["max"]]

        if not active_specs:
            return go.Figure().add_annotation(text="No active parameters to display")

        def _parse_jsonc(text: str) -> dict:
            clean = re.sub(r"//[^\n]*", "", text)
            return json.loads(clean)

        trial_config_paths = []
        try:
            for gen_dir in sorted(
                TRIALS_DIR.glob("gen_*"),
                key=lambda d: (
                    int(d.name.split("_")[1]) if len(d.name.split("_")) > 1 else 0
                ),
            ):
                for trial_dir in sorted(
                    gen_dir.glob("trial_*"),
                    key=lambda d: (
                        int(d.name.split("_")[1]) if len(d.name.split("_")) > 1 else 0
                    ),
                ):
                    cfg = trial_dir / "lab_config.jsonc"
                    if cfg.exists():
                        trial_config_paths.append(cfg)
        except Exception:
            pass

        trial_configs = []
        for cfg_path in trial_config_paths[-40:]:
            try:
                trial_configs.append(_parse_jsonc(cfg_path.read_text(encoding="utf-8")))
            except Exception:
                pass

        latest_config = trial_configs[-1] if trial_configs else None
        param_names = [spec["name"] for spec in active_specs]
        fig = go.Figure()

        n_hist = len(trial_configs)
        if n_hist > 0:
            nbins = 64
            bin_centers = [(i + 0.5) / nbins for i in range(nbins)]

            z_rows = []
            for spec in active_specs:
                name = spec["name"]
                span = (spec["max"] - spec["min"]) or 1.0
                counts = [0] * nbins
                total = 0
                for cfg in trial_configs:
                    v = cfg.get(name)
                    if isinstance(v, (int, float)):
                        norm = max(0.0, min(1.0, (v - spec["min"]) / span))
                        idx = int(norm * nbins)
                        if idx >= nbins:
                            idx = nbins - 1
                        counts[idx] += 1
                        total += 1

                if total > 0:
                    maxc = max(counts)
                    row = [c / maxc if maxc > 0 else 0.0 for c in counts]
                else:
                    row = [0.0 for _ in counts]
                z_rows.append(row)

            fig.add_trace(
                go.Heatmap(
                    x=bin_centers,
                    y=param_names,
                    z=z_rows,
                    colorscale="YlOrRd",
                    showscale=False,
                    hovertemplate="%{y}<br>Value: %{x:.2f}<br>Rel. density: %{z:.2f}<extra></extra>",
                    zmin=0,
                    zmax=1,
                )
            )

        for spec in active_specs:
            name = spec["name"]
            param_min, param_max = spec["min"], spec["max"]
            span = (param_max - param_min) or 1.0

            values = []
            if latest_config is None:
                values = []
            else:
                v = latest_config.get(name)
                if isinstance(v, (int, float)):
                    values = [float(v)]
                elif isinstance(v, (list, tuple)):
                    values = [float(x) for x in v if isinstance(x, (int, float))]

            if not values:
                values = [(param_min + param_max) / 2]

            side_texts = []
            marker_xs = []
            for val in values:
                norm = max(0.0, min(1.0, (val - param_min) / span))
                marker_xs.append(norm)
                side_texts.append(f"{val:.3f}")

            if marker_xs:
                fig.add_trace(
                    go.Scatter(
                        x=marker_xs,
                        y=[name] * len(marker_xs),
                        mode="markers",
                        marker=dict(
                            symbol="diamond",
                            size=12,
                            color="#ffffff",
                            line=dict(width=2, color="#212121"),
                        ),
                        hovertemplate=(
                            f"<b>{name}</b><br>Current: "
                            + ", ".join(side_texts)
                            + f"<br>Min: {param_min:.3f} | Max: {param_max:.3f}<extra></extra>"
                        ),
                        showlegend=False,
                    )
                )

                fig.add_annotation(
                    x=1.02,
                    y=name,
                    text="[" + ", ".join(side_texts) + "]",
                    showarrow=False,
                    xanchor="left",
                    yanchor="middle",
                    font=dict(size=11, color="#111"),
                )

        row_h = 70 if show_heatmap else 52
        fig.update_layout(
            title="Parameter Bounds Monitor (Latest Trial)",
            xaxis=dict(
                title="Position in Range (0 = Min, 1 = Max)",
                range=[0, 1],
                fixedrange=True,
            ),
            yaxis=dict(
                categoryorder="array",
                categoryarray=list(reversed(param_names)),
                fixedrange=True,
            ),
            barmode="overlay",
            height=max(400, 90 + len(active_specs) * row_h),
            showlegend=False,
            margin={"l": 160, "r": 70, "t": 50, "b": 50},
            plot_bgcolor=C_BG,
            paper_bgcolor=C_BG,
        )

        for spec in active_specs:
            fig.add_annotation(
                x=0.0,
                y=spec["name"],
                text=f"{spec['min']:.3f}",
                xanchor="left",
                yanchor="top",
                showarrow=False,
                yshift=-18,
                font=dict(size=9, color="#888"),
            )
            fig.add_annotation(
                x=1.0,
                y=spec["name"],
                text=f"{spec['max']:.3f}",
                xanchor="right",
                yanchor="top",
                showarrow=False,
                yshift=-18,
                font=dict(size=9, color="#888"),
            )

        return fig
    except Exception as exc:
        print(f"[warn] Error building param bounds: {exc}")
        return go.Figure().add_annotation(text=f"Error: {exc}")


def _build_progress_stats(
    current_records: list[dict], all_records: list[dict]
) -> html.Div:
    gen_index = current_records[0].get("gen_index", -1) if current_records else -1
    gen_label = f"Gen {gen_index}" if gen_index >= 0 else "—"

    best_record = max(
        [r for r in all_records if not r.get("failed", False)],
        key=lambda x: x.get("final_score", 0),
        default=None,
    )
    best_score = best_record.get("final_score", 0) if best_record else 0
    best_trial = (
        f"{best_record.get('gen_name', '')} / {best_record.get('trial_name', '')}"
        if best_record
        else "N/A"
    )

    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.H6("Generation", className="text-muted"),
                            html.H4(gen_label, className="text-info"),
                        ],
                        className="col-12 col-md-6",
                    ),
                    html.Div(
                        [
                            html.H6("Best Score", className="text-muted"),
                            html.H4(f"{best_score:.4f}", className="text-warning"),
                            html.Small(best_trial, className="text-muted"),
                        ],
                        className="col-12 col-md-6",
                    ),
                ],
                className="row g-3",
            )
        ],
        className="p-3 bg-light rounded",
    )


def _build_progress_grid(records: list[dict]) -> html.Div:
    if not records:
        return html.Div("No trial data found.", className="text-muted")
    rows = [_build_progress_card(record) for record in records]
    return html.Div(rows, style={"display": "grid", "gap": "12px"})


def _get_live_score(run: dict) -> tuple[float | None, bool]:
    score = run.get("score")
    if isinstance(score, (int, float)):
        return float(score), True
    hold_time = run.get("hold_time")
    if isinstance(hold_time, (int, float)):
        return float(hold_time), False
    return None, False


def _find_earliest_not_done(records: list[dict]) -> str | None:
    terminal = {"done", "failed", "error", "pruned", "skipped", "cancelled"}
    for record in records:
        state = _get_trial_actual_state(record)
        if state not in terminal:
            return f"trial-card-{record.get('gen_index', 0):04d}-{record.get('trial_index', 0):04d}"
    return None



# ─────────────────────────────────────────────────────────────
# Main Dash App
# ─────────────────────────────────────────────────────────────


def create_app() -> Dash:
    from labtests.registry import get_test_catalog

    try:
        catalog = get_test_catalog()
    except Exception as exc:
        print(f"[warn] Could not load test catalog: {exc}")
        catalog = {}

    all_test_names_ordered = list(catalog.keys())

    app = Dash(
        __name__,
        external_stylesheets=[
            "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"
        ],
    )

    app.layout = html.Div(
        [
            html.Div(
                [
                    html.H1("ShapeOPT", className="text-center mb-2 mt-3"),
                    html.P(
                        "Configure · Generate · Optimise · Analyse",
                        className="text-center text-muted mb-4",
                    ),
                ]
            ),
            dcc.Tabs(
                id="tabs",
                value="config",
                children=[
                    dcc.Tab(
                        label="⚙️ Config",
                        value="config",
                        children=build_config_tab(),
                    ),
                    dcc.Tab(
                        label="\U0001f527 Generate",
                        value="generate",
                        children=build_generate_tab(),
                    ),
                    dcc.Tab(
                        label="\U0001f3ac Scenes",
                        value="scenes",
                        children=build_scenes_tab(catalog),
                    ),
                    dcc.Tab(
                        label="\U0001f680 Optimise",
                        value="optimise",
                        children=build_optimise_tab(catalog),
                    ),
                    dcc.Tab(
                        label="\U0001f4ca Performance & Leaderboard",
                        value="performance",
                        children=build_performance_tab(),
                    ),
                    dcc.Tab(
                        label="\U0001f4c8 Progress Monitor",
                        value="progress",
                        children=build_progress_tab(),
                    ),
                    dcc.Tab(
                        label="\U0001f39b️ Parameter Bounds",
                        value="bounds",
                        children=build_param_bounds_tab(),
                    ),
                ],
            ),
        ],
        className="py-3",
    )

    # ── Config callbacks ──────────────────────────────────────

    @callback(
        Output("config-save-status", "children"),
        Input("config-save-btn", "n_clicks"),
        State("config-textarea", "value"),
        prevent_initial_call=True,
    )
    def save_config(_, text):
        if not text:
            return "Nothing to save."
        try:
            clean = re.sub(r"//[^\n]*", "", text)
            data = json.loads(clean)
            CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return html.Span("Saved.", style={"color": "#2f9e44"})
        except json.JSONDecodeError as exc:
            return html.Span(f"Invalid JSON: {exc}", style={"color": "#e03131"})
        except Exception as exc:
            return html.Span(f"Error: {exc}", style={"color": "#e03131"})

    # ── Generate callbacks ────────────────────────────────────

    @callback(
        Output("gen-status", "children"),
        Input("gen-btn", "n_clicks"),
        Input("gen-fine-btn", "n_clicks"),
        Input("gen-stop-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def handle_generate(_, __, ___):
        from dash import ctx

        tid = ctx.triggered_id
        if tid == "gen-stop-btn":
            return _stop_proc("generate")
        elif tid == "gen-fine-btn":
            return _start_proc("generate", GENERATE_FINE_SCRIPT)
        else:
            return _start_proc("generate", GENERATE_SCRIPT)

    @callback(
        Output("gen-log", "children"),
        Input("gen-interval", "n_intervals"),
    )
    def update_gen_log(_):
        return _read_proc_log("generate")

    @callback(
        Output("gen-open-status", "children"),
        Input("gen-open-stl-btn", "n_clicks"),
        Input("gen-open-json-btn", "n_clicks"),
        Input("gen-open-fine-stl-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def handle_gen_open(_, __, ___):
        from dash import ctx

        file_map = {
            "gen-open-stl-btn": CENTERPARTS_DIR / "new_gripper.stl",
            "gen-open-json-btn": CENTERPARTS_DIR / "new_gripper.json",
            "gen-open-fine-stl-btn": CENTERPARTS_DIR / "new_gripper_print.stl",
        }
        path = file_map.get(ctx.triggered_id)
        if path is None:
            return ""
        if not path.exists():
            return f"{path.name} not found — generate first."
        try:
            os.startfile(str(path))
            return f"Opened {path.name}."
        except Exception as exc:
            return f"Could not open {path.name}: {exc}"

    # ── Scenes callbacks ──────────────────────────────────────

    @callback(
        Output("scene-status", "children"),
        Input("scene-inverse-btn", "n_clicks"),
        Input("scene-recording-btn", "n_clicks"),
        State("scene-recording-test", "value"),
        prevent_initial_call=True,
    )
    def handle_scene(_, __, recording_test):
        from dash import ctx

        tid = ctx.triggered_id
        if tid == "scene-inverse-btn":
            return _launch_sofa_scene(INVERSE_SCENE)
        if tid == "scene-recording-btn" and recording_test:
            _write_session_config(recording_test)
            return _launch_sofa_scene(RECORDING_SCENE)
        return ""

    # ── Optimise callbacks (clientside — zero server round-trips) ─────────
    #
    # Architecture: opt-weights-store is the single source of truth.
    # All weight logic runs in the browser as JS → instant response on drag.
    #
    #   user drag slider ─┐
    #   checkbox toggle  ─┤──► update_weights_store (JS) ──► opt-weights-store
    #   equal / normalize ┘              │
    #                                    ├──► sync_sliders_from_store (JS) ──► sliders
    #                                    ├──► update_opt_pie (JS)           ──► pie chart
    #                                    └──► update_opt_weight_status (JS) ──► status
    #
    # Loop break: programmatic slider sync sets values equal to the store;
    # update_weights_store detects store[test] === newValue and returns no_update.

    app.clientside_callback(
        """
        function(slider_vals, check_vals, eq_clicks, norm_clicks, slider_ids, store) {
            var NO_UPDATE = window.dash_clientside.no_update;
            var ctx = window.dash_clientside.callback_context;
            if (!ctx || !ctx.triggered || ctx.triggered.length === 0) return NO_UPDATE;

            // Parse triggered component id (object for pattern-match, string otherwise)
            var prop_id = ctx.triggered[0].prop_id;
            var dot = prop_id.lastIndexOf('.');
            var id_part = prop_id.substring(0, dot);
            var tid;
            try { tid = JSON.parse(id_part); } catch(e) { tid = id_part; }

            store = store ? Object.assign({}, store) : {};
            var all_tests = slider_ids.map(function(s) { return s.test; });
            var selected_tests = [];
            slider_ids.forEach(function(s, i) {
                if (check_vals[i] && check_vals[i].length > 0) selected_tests.push(s.test);
            });

            function equal_split(n) {
                if (n === 0) return [];
                var base = Math.floor(100 / n), rem = 100 - base * n;
                return Array.from({length: n}, function(_, i) { return base + (i < rem ? 1 : 0); });
            }

            function normalize_selected() {
                var total = selected_tests.reduce(function(s,t){ return s+(store[t]||0); }, 0);
                all_tests.forEach(function(t){
                    if (selected_tests.indexOf(t) < 0) store[t] = 0;
                });
                if (total === 0) {
                    var w = equal_split(selected_tests.length);
                    selected_tests.forEach(function(t,i){ store[t] = w[i]; });
                } else {
                    var scaled = selected_tests.map(function(t){
                        return Math.round((store[t]||0) / total * 100);
                    });
                    var diff = 100 - scaled.reduce(function(a,b){return a+b;}, 0);
                    if (diff) scaled[0] += diff;
                    selected_tests.forEach(function(t,i){ store[t] = scaled[i]; });
                }
            }

            // ── Equal split ──────────────────────────────────────────────
            if (tid === 'opt-equal-btn') {
                if (selected_tests.length === 0) return NO_UPDATE;
                var w = equal_split(selected_tests.length);
                all_tests.forEach(function(t){ store[t] = 0; });
                selected_tests.forEach(function(t,i){ store[t] = w[i]; });
                return store;
            }

            // ── Normalize ────────────────────────────────────────────────
            if (tid === 'opt-normalize-btn') {
                if (selected_tests.length === 0) return NO_UPDATE;
                normalize_selected();
                return store;
            }

            // ── Checkbox toggled ─────────────────────────────────────────
            if (tid && typeof tid === 'object' && tid.type === 'test-check') {
                if (selected_tests.length === 0) {
                    all_tests.forEach(function(t){ store[t] = 0; });
                    return store;
                }
                normalize_selected();
                return store;
            }

            // ── Slider dragged ───────────────────────────────────────────
            if (tid && typeof tid === 'object' && tid.type === 'weight-slider') {
                var changed_test = tid.test;
                var changed_value = null;
                slider_ids.forEach(function(sid, i) {
                    if (sid.test === changed_test) changed_value = slider_vals[i];
                });
                if (changed_value === null) return NO_UPDATE;

                // Loop break: this was a programmatic sync, not a user drag
                if (store[changed_test] === changed_value) return NO_UPDATE;
                if (selected_tests.indexOf(changed_test) < 0) return NO_UPDATE;

                var n_sel = selected_tests.length;
                if (n_sel === 1) { store[changed_test] = 100; return store; }

                var old_val = store[changed_test] || 0;
                var new_val = Math.max(0, Math.min(100, Math.round(changed_value)));
                var delta = new_val - old_val;
                if (delta === 0) return NO_UPDATE;

                store[changed_test] = new_val;
                var idx = selected_tests.indexOf(changed_test);
                var remaining = delta;

                for (var step = 1; step < n_sel; step++) {
                    var next_test = selected_tests[(idx + step) % n_sel];
                    var cur = store[next_test] || 0;
                    if (remaining > 0) {
                        var take = Math.min(remaining, cur);
                        store[next_test] = cur - take;
                        remaining -= take;
                    } else {
                        var give = Math.min(-remaining, 100 - cur);
                        store[next_test] = cur + give;
                        remaining += give;
                    }
                    if (remaining === 0) break;
                }
                if (remaining !== 0) store[changed_test] = new_val - remaining;

                all_tests.forEach(function(t) {
                    if (selected_tests.indexOf(t) < 0) store[t] = 0;
                });
                return store;
            }

            return NO_UPDATE;
        }
        """,
        Output("opt-weights-store", "data"),
        Input({"type": "weight-slider", "test": ALL}, "value"),
        Input({"type": "test-check", "test": ALL}, "value"),
        Input("opt-equal-btn", "n_clicks"),
        Input("opt-normalize-btn", "n_clicks"),
        State({"type": "weight-slider", "test": ALL}, "id"),
        State("opt-weights-store", "data"),
        prevent_initial_call=True,
    )

    app.clientside_callback(
        """
        function(store, slider_ids) {
            if (!store) return slider_ids.map(function() { return 0; });
            return slider_ids.map(function(sid) { return store[sid.test] || 0; });
        }
        """,
        Output({"type": "weight-slider", "test": ALL}, "value"),
        Input("opt-weights-store", "data"),
        State({"type": "weight-slider", "test": ALL}, "id"),
    )

    app.clientside_callback(
        """
        function(store, slider_ids, check_vals) {
            var palette = ["#4c8bf5","#e84393","#34a853","#fa7b17",
                           "#9c27b0","#00bcd4","#ff5722","#8bc34a"];
            store = store || {};
            var labels = [], values = [], colors = [];
            slider_ids.forEach(function(sid, i) {
                var w = store[sid.test] || 0;
                if (check_vals[i] && check_vals[i].length > 0 && w > 0) {
                    labels.push(sid.test);
                    values.push(w);
                    colors.push(palette[i % palette.length]);
                }
            });
            var layout = {
                margin: {l:10, r:10, t:30, b:10},
                showlegend: false,
                paper_bgcolor: 'rgba(0,0,0,0)'
            };
            if (labels.length === 0) {
                return {
                    data: [{type:'pie', labels:['none'], values:[1],
                            marker:{colors:['#dee2e6']}, textinfo:'none', hoverinfo:'none'}],
                    layout: layout
                };
            }
            return {
                data: [{
                    type: 'pie', labels: labels, values: values,
                    marker: {colors: colors}, textinfo: 'label+percent',
                    hovertemplate: '%{label}: %{value}%<extra></extra>', hole: 0.35
                }],
                layout: layout
            };
        }
        """,
        Output("opt-pie", "figure"),
        Input("opt-weights-store", "data"),
        State({"type": "weight-slider", "test": ALL}, "id"),
        State({"type": "test-check", "test": ALL}, "value"),
    )

    app.clientside_callback(
        """
        function(store, check_vals, slider_ids) {
            store = store || {};
            var selected_count = check_vals.filter(function(v) {
                return v && v.length > 0;
            }).length;
            var total = 0;
            slider_ids.forEach(function(sid, i) {
                if (check_vals[i] && check_vals[i].length > 0) total += (store[sid.test] || 0);
            });
            var mk = function(txt, cls) {
                return {type:'Span', namespace:'dash_html_components',
                        props:{children: txt, className: cls}};
            };
            if (selected_count === 0)
                return mk('Select at least one test.', 'text-warning');
            if (total !== 100)
                return mk('Selected weights sum to ' + total + '% — must equal 100%.',
                          'text-danger fw-semibold');
            return mk(selected_count + ' test(s) selected · weights OK (total 100%).',
                      'text-success fw-semibold');
        }
        """,
        Output("opt-weight-status", "children"),
        Input("opt-weights-store", "data"),
        Input({"type": "test-check", "test": ALL}, "value"),
        State({"type": "weight-slider", "test": ALL}, "id"),
    )

    @callback(
        Output("opt-status", "children"),
        Input("opt-start-btn", "n_clicks"),
        Input("opt-stop-btn", "n_clicks"),
        State({"type": "test-check", "test": ALL}, "value"),
        State({"type": "test-check", "test": ALL}, "id"),
        State("opt-weights-store", "data"),
        prevent_initial_call=True,
    )
    def handle_optimise(_, __, check_vals, check_ids, store):
        from dash import ctx

        if ctx.triggered_id == "opt-stop-btn":
            return _stop_proc("optimize")

        store = store or {}
        test_names: list[str] = []
        test_weights: dict[str, int] = {}
        for checks, cid in zip(check_vals, check_ids):
            if checks:
                name = cid["test"]
                test_names.append(name)
                test_weights[name] = int(store.get(name, 0))

        if not test_names:
            return "No tests selected."

        total = sum(test_weights.values())
        if total != 100:
            return f"Weights must sum to 100% (currently {total}%)."

        env = os.environ.copy()
        env["LAB_SHAPEOPT_TESTS"] = ",".join(test_names)
        env["LAB_SHAPEOPT_TEST_WEIGHTS"] = json.dumps(test_weights)
        return _start_proc("optimize", OPTIMIZE_SCRIPT, env)

    @callback(
        Output("opt-log", "children"),
        Input("opt-interval", "n_intervals"),
    )
    def update_opt_log(_):
        return _read_proc_log("optimize")

    # ── Performance callbacks ─────────────────────────────────

    @callback(
        Output("trial-detail-panel", "children"),
        Input("performance-graph", "clickData"),
    )
    def on_trial_click(click_data):
        if not click_data:
            return html.Div()
        try:
            point = click_data["points"][0]
            cd = point.get("customdata")
            if not cd or len(cd) < 3:
                return html.Div()
            gen_name, trial_name = cd[1], cd[2]
            if not gen_name or not trial_name:
                return html.Div()
            state = _read_json(TRIALS_DIR / gen_name / trial_name / "trial_state.json")
            if not state:
                return html.Div(
                    "No detail available for this trial.", className="text-muted"
                )
            return _build_trial_detail(state, gen_name, trial_name)
        except Exception as exc:
            return html.Div(f"Could not load trial: {exc}", className="text-muted")

    @callback(
        [
            Output("performance-graph", "figure"),
            Output("leaderboard-table", "children"),
        ],
        Input("tabs", "value"),
        Input("performance-interval", "n_intervals"),
    )
    def update_performance(tab, _):
        records, summaries = _load_data()
        if tab != "performance":
            return go.Figure(), html.Div()
        fig = _build_performance_graph(records, summaries)
        leaderboard = _build_leaderboard_html(records)
        return fig, leaderboard

    @callback(
        Output("param-bounds-graph", "figure"),
        Input("bounds-interval", "n_intervals"),
    )
    def update_bounds(_):
        return _build_param_bounds_graph(show_heatmap=True)

    @callback(
        [Output("progress-stats", "children"), Output("progress-grid", "children")],
        Input("progress-interval", "n_intervals"),
    )
    def update_progress(_):
        records, summaries = _load_data()
        current_records = _current_generation_records(records)
        stats = _build_progress_stats(current_records, records)
        grid = _build_progress_grid(current_records)
        return stats, grid

    @callback(
        Output("jump-running-target-store", "data"),
        Input("jump-running-trial", "n_clicks"),
        Input("progress-interval", "n_intervals"),
        State("jump-auto-enabled", "data"),
    )
    def update_jump_target(_clicks, _intervals, auto_enabled):
        try:
            from dash import ctx
        except Exception:
            ctx = None

        triggered = None
        if ctx is not None:
            triggered = getattr(ctx, "triggered_id", None)

        is_auto = triggered == "progress-interval"

        if is_auto and not bool(auto_enabled):
            return {"target_id": None, "auto": True}

        records, _summaries = _load_data()
        current_records = _current_generation_records(records)
        return {"target_id": _find_earliest_not_done(current_records), "auto": is_auto}

    app.clientside_callback(
        """
        function(target, auto_enabled) {
            if (!target || !target.target_id) {
                return window.dash_clientside.no_update;
            }
            if (target.auto && !auto_enabled) {
                return window.dash_clientside.no_update;
            }
            const el = document.getElementById(target.target_id);
            if (el) {
                el.scrollIntoView({behavior: 'smooth', block: 'center'});
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output("jump-running-target-output", "children"),
        Input("jump-running-target-store", "data"),
        State("jump-auto-enabled", "data"),
    )

    app.clientside_callback(
        """
        function(n_intervals, auto_enabled) {
            if (!window._ajScrollListenerReady) {
                window._ajUserScrolled = false;
                var mark = function() { window._ajUserScrolled = true; };
                window.addEventListener('wheel',     mark, {passive: true});
                window.addEventListener('touchmove', mark, {passive: true});
                window.addEventListener('keydown', function(e) {
                    if ([' ','ArrowUp','ArrowDown','PageUp','PageDown','Home','End'].includes(e.key)) {
                        window._ajUserScrolled = true;
                    }
                }, {passive: true});
                window._ajScrollListenerReady = true;
            }
            if (!auto_enabled) {
                window._ajUserScrolled = false;
                return window.dash_clientside.no_update;
            }
            if (window._ajUserScrolled) {
                window._ajUserScrolled = false;
                return false;
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output("jump-auto-enabled", "data", allow_duplicate=True),
        Input("progress-interval", "n_intervals"),
        State("jump-auto-enabled", "data"),
        prevent_initial_call=True,
    )

    app.clientside_callback(
        """
        function(n) {
            if (!n) { return window.dash_clientside.no_update; }
            window.scrollTo({top: 0, behavior: 'smooth'});
            return false;
        }
        """,
        Output("jump-auto-enabled", "data", allow_duplicate=True),
        Input("jump-top-button", "n_clicks"),
        prevent_initial_call=True,
    )

    app.clientside_callback(
        "function(n) { return window.dash_clientside.no_update; }",
        Output("jump-top-output", "children"),
        Input("jump-top-button", "n_clicks"),
    )

    app.clientside_callback(
        "function(n, cur) { if (!n) return window.dash_clientside.no_update; return !cur; }",
        Output("jump-auto-enabled", "data", allow_duplicate=True),
        Input("jump-auto-toggle", "n_clicks"),
        State("jump-auto-enabled", "data"),
        prevent_initial_call=True,
    )

    app.clientside_callback(
        'function(on) { return on ? "Auto-jump: On" : "Auto-jump: Off"; }',
        Output("jump-auto-toggle", "children"),
        Input("jump-auto-enabled", "data"),
    )

    return app


# ─────────────────────────────────────────────────────────────
# Launch
# ─────────────────────────────────────────────────────────────


def launch_dashboard(port: int = 8050, open_browser: bool = True) -> None:
    print(f"[info] Starting ShapeOPT on http://localhost:{port}")

    os.environ["WERKZEUG_RUN_MAIN"] = "false"
    os.environ.pop("WERKZEUG_SERVER_FD", None)

    app = create_app()
    launch_url = f"http://localhost:{port}/?v={int(time.time())}"

    if open_browser:
        def open_browser_delayed():
            time.sleep(2)
            webbrowser.open_new_tab(launch_url)

        thread = threading.Thread(target=open_browser_delayed, daemon=True)
        thread.start()

    app.run(debug=False, use_reloader=False, port=port, host="127.0.0.1")


if __name__ == "__main__":
    launch_dashboard()