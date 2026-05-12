"""
dashboard.py — Unified Plotly/Dash web dashboard with tabbed analysis views.

Consolidates all analysis tools (leaderboard, performance plots, parameter bounds,
progress monitor) into a single browser window with interactive tabs.

Features:
- Multiple tabs for different analysis views
- Real-time updates while optimization runs
- Interactive charts with zoom/pan
- Responsive layout
"""

import os
import sys
import threading
import time
import webbrowser
from pathlib import Path
import logging

try:
    from dash import Dash, dcc, html, callback, Input, Output, State
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    DASH_AVAILABLE = True
except ImportError:
    DASH_AVAILABLE = False

# Setup paths
LAB_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = LAB_ROOT / "app" / "src"
TRIALS_DIR = LAB_ROOT / "runtime" / "trials"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

# Suppress logs
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

# Cache MAX_SCORE per test so we don't re-import scoring modules on every update
_MAX_SCORE_CACHE: dict[str, float] = {}

# Simple in-memory cache to avoid re-parsing thousands of JSON files
# on every interval tick or initial page load.
_DATA_CACHE: dict = {"records": [], "summaries": [], "last_load": 0.0}


def _get_test_max_score(test_name: str) -> float:
    """Return the declared MAX_SCORE for a test, falling back to 1.0."""
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


def install_dependencies():
    """Auto-install missing dependencies."""
    import subprocess

    packages = ["dash"]
    for pkg in packages:
        try:
            __import__(pkg.replace("-", "_"))
        except ImportError:
            print(f"[info] Installing {pkg}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])


if not DASH_AVAILABLE:
    install_dependencies()
    from dash import Dash, dcc, html, callback, Input, Output, State
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots


# ─────────────────────────────────────────────────────────────
# Tab: Performance & Leaderboard
# ─────────────────────────────────────────────────────────────


def build_performance_tab() -> html.Div:
    """Build performance visualization tab with bars and score lines."""
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
    """Build parameter bounds visualization tab."""
    return html.Div(
        [
            html.H3("Parameter Bounds Monitor", className="mb-3"),
            html.P("Live tracking of parameter values within optimization bounds."),
            # The parameter history is shown as a heatmap (last ~40 trials).
            # No fixed height — figure height adapts to parameter count; page scrolls naturally
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
    """Build progress monitoring tab."""
    return html.Div(
        [
            html.H3("Optimization Progress", className="mb-3"),
            html.P(
                "Only the current generation's trials are shown, one card per trial and one progress bar per run slot.",
                className="text-muted mb-3",
            ),
            html.Div(
                [
                    html.Button(
                        "Jump to earliest unfinished trial",
                        id="jump-running-trial",
                        n_clicks=0,
                        className="btn btn-primary btn-sm",
                    ),
                    html.Span(
                        "Scrolls to the first trial that is not yet complete.",
                        className="text-muted ms-3",
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
            # Floating toolbar: back-to-top and auto-jump toggle (visible anywhere)
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


def _load_data():
    """Load all trial data and summaries with a short in-memory cache.

    This avoids re-parsing thousands of JSON files on every interval tick
    or initial page render. The cache TTL is controlled by
    `LIVE_REFRESH_SECONDS` in `analyze_config`.
    """
    try:
        now = time.time()
        # Use cached values when recent
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
    except Exception as e:
        print(f"[warn] Error loading data: {e}")
        # Fall back to cached data when available
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

    # Sort by trial_index to ensure consistent ordering across all callbacks
    result = [
        record for record in records if record.get("gen_index", -1) == current_gen
    ]
    return sorted(result, key=lambda r: r.get("trial_index", 0))


def _read_json(path: Path) -> dict | None:
    try:
        import json

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


def _format_run_label(run: dict) -> str:
    label = run.get("run_label") or run.get("test_name") or "run"
    idx = run.get("test_run_index")
    total = run.get("test_run_total")
    if label and idx and total:
        return f"{label}"
    return str(label)


def _get_trial_actual_state(trial_record: dict) -> str:
    """Determine the actual state of a trial using the same logic as display.

    This matches the logic in _build_progress_card to ensure consistency
    between what we display and what we check for completion.
    """
    trial_state = _load_trial_state(trial_record) or {}
    runs = trial_state.get("runs") if isinstance(trial_state.get("runs"), list) else []

    # Start with explicit state or default based on is_complete flag
    state = str(
        trial_state.get("state")
        or ("done" if trial_record.get("is_complete") else "running")
    ).lower()

    # If state is not terminal but all individual runs ARE terminal, infer "done"
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
    trial_label = (
        f"{trial_record.get('gen_name', '')} / {trial_record.get('trial_name', '')}"
    )
    final_score = trial_record.get("final_score")

    # Use the shared state determination logic
    state = _get_trial_actual_state(trial_record)

    run_rows = []
    if runs:
        for run in runs:
            if not isinstance(run, dict):
                continue
            run_state = str(run.get("state", "not-started")).lower()
            bar_color = _state_color(run_state)

            # Normalize against MAX_SCORE for this test
            test_name = run.get("test_name") or run.get("run_label") or ""
            max_score = _get_test_max_score(test_name)

            live_val, is_final = _get_live_score(run)
            if live_val is not None and run_state not in {"not-started"}:
                bar_pct = (
                    max(0.0, min(100.0, live_val / max_score * 100))
                    if max_score > 0
                    else 0.0
                )
                # Tilde prefix on live (non-final) values so the user knows it's in progress
                score_label = f"{live_val:.3f}" if is_final else f"~{live_val:.3f}"
            else:
                bar_pct = 0.0
                score_label = "--"

            run_rows.append(
                html.Div(
                    [
                        html.Div(
                            [
                                html.Span(
                                    _format_run_label(run), className="fw-semibold"
                                ),
                                html.Span(" · ", className="text-muted"),
                                html.Span(
                                    score_label,
                                    style={
                                        "color": bar_color,
                                        "fontWeight": 700,
                                        "fontSize": "1rem",
                                    },
                                ),
                                html.Span(
                                    f"  {run_state}",
                                    style={"color": bar_color, "fontSize": "0.8rem"},
                                ),
                            ],
                            className="d-flex align-items-center gap-1 mb-1",
                        ),
                        html.Div(
                            [
                                html.Div(
                                    score_label if bar_pct > 8 else "",
                                    style={
                                        "width": f"{bar_pct:.1f}%",
                                        "height": "100%",
                                        "background": bar_color,
                                        "borderRadius": "999px",
                                        "transition": "width 600ms ease",
                                        "willChange": "width",
                                        "display": "flex",
                                        "alignItems": "center",
                                        "paddingLeft": "8px",
                                        "color": "#fff",
                                        "fontSize": "0.72rem",
                                        "fontWeight": 600,
                                        "minWidth": "0",
                                        "overflow": "hidden",
                                        "whiteSpace": "nowrap",
                                    },
                                )
                            ],
                            style={
                                "height": "20px",
                                "background": "#e9ecef",
                                "borderRadius": "999px",
                                "overflow": "hidden",
                            },
                        ),
                    ],
                    className="mb-2",
                )
            )

    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Div("Trial", className="text-muted"),
                            html.Div(trial_label, className="fw-semibold"),
                        ],
                        className="col-12 col-md-5",
                    ),
                    html.Div(
                        [
                            html.Div("State", className="text-muted"),
                            html.Div(
                                state,
                                style={"color": _state_color(state), "fontWeight": 600},
                            ),
                        ],
                        className="col-12 col-md-3",
                    ),
                    html.Div(
                        [
                            html.Div("Final score", className="text-muted"),
                            html.Div(
                                (
                                    f"{final_score:.4f}"
                                    if isinstance(final_score, (int, float))
                                    else "--"
                                ),
                                className="fw-semibold",
                            ),
                        ],
                        className="col-12 col-md-2",
                    ),
                    html.Div(
                        [
                            html.Div("Runs", className="text-muted"),
                            html.Div(
                                str(len(runs) or trial_record.get("n_runs", 0)),
                                className="fw-semibold",
                            ),
                        ],
                        className="col-12 col-md-2",
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
    """Build the per-trial detail panel shown when the user clicks a bar."""
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
        contribution = norm * weight  # pts earned out of weight_pct max
        success_pct = norm * 100  # % of the test's own maximum
        run_scores: list = info.get("run_scores") or []
        run_total = int(info.get("run_total", 1))

        bar_pct = min(norm * 100, 100)

        # Mini run-score table for multi-run tests
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
                    # Test name + weight badge
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
                    # Progress bar
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
                    # Score line
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
                    # Individual run scores (multi-run tests only)
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
    """Build HTML table for leaderboard display."""
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
    """Build combined performance plot with bars and lines."""
    if not records:
        return go.Figure().add_annotation(text="No data available")

    try:
        all_test_names = _collect_all_test_names(records)
        plot_data = compute_plot_data(records, all_test_names)

        # Compute bar width
        xs = plot_data["xs"]
        bar_width = max(0.4, (max(xs) - min(xs) + 1) / len(xs) * 0.8) if xs else 0.8

        bar_traces = _build_bar_traces(records, plot_data, all_test_names)
        hover_overlay = _build_hover_overlay(
            records, plot_data, all_test_names, bar_width
        )
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
            # Keep zoom/pan/legend state across data refreshes
            uirevision="performance-graph",
        )
        # Hint Plotly to animate updates smoothly when figures are replaced
        try:
            fig.layout.transition = dict(duration=600, easing="cubic-in-out")
        except Exception:
            pass
        return fig
    except Exception as e:
        print(f"[warn] Error building performance graph: {e}")
        return go.Figure().add_annotation(text=f"Error: {e}")


def _build_param_bounds_graph(show_heatmap: bool = False) -> go.Figure:
    """Build parameter bounds visualization with optional history heatmap."""
    try:
        import json, re
        from optimization.optimize_config import PARAM_SPECS

        active_specs = [p for p in PARAM_SPECS if p["min"] < p["max"]]

        if not active_specs:
            return go.Figure().add_annotation(text="No active parameters to display")

        def _parse_jsonc(text: str) -> dict:
            clean = re.sub(r"//[^\n]*", "", text)
            return json.loads(clean)

        # Collect trial configs in chronological order (cap at last 40)
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

        # Build a per-parameter heatmap from the last N trial configs.
        # X axis = trial index (older -> left), Y axis = parameter name.
        n_hist = len(trial_configs)
        cyclical_cs = [
            [0.0, "#FFEB3B"],
            [0.5, "#F44336"],
            [1.0, "#FFEB3B"],
        ]

        if n_hist > 0:
            # Build density histograms across the normalized parameter range for each spec.
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

                # Normalize per-row so color shows relative density for that parameter.
                if total > 0:
                    maxc = max(counts)
                    row = [c / maxc if maxc > 0 else 0.0 for c in counts]
                else:
                    row = [0.0 for _ in counts]
                z_rows.append(row)

            # Use a sequential colorscale for density (yellow->red).
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

        # Current value markers: support single numeric OR list of numerics
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
                    # filter numeric entries
                    values = [float(x) for x in v if isinstance(x, (int, float))]

            # If no explicit current value, fall back to mid-point
            if not values:
                values = [(param_min + param_max) / 2]

            # Plot each current value as a white-ringed marker and collect text for side-list
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

                # Add side annotation listing the present values similar to history representation
                fig.add_annotation(
                    x=1.02,
                    y=name,
                    text="[" + ", ".join(side_texts) + "]",
                    showarrow=False,
                    xanchor="left",
                    yanchor="middle",
                    font=dict(size=11, color="#111"),
                )

        # Row height: taller when heatmap is on to give room for dots; extra room for min/max labels
        row_h = 70 if show_heatmap else 52
        fig.update_layout(
            title="Parameter Bounds Monitor (Latest Trial)",
            xaxis=dict(
                title="Position in Range (0 = Min, 1 = Max)",
                range=[0, 1],
                fixedrange=True,
            ),
            yaxis=dict(
                # Lock the category order so the axis never shifts on update
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

        # Min/max labels placed BELOW each bar row to avoid overlapping the y-axis param names
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
    except Exception as e:
        print(f"[warn] Error building param bounds: {e}")
        return go.Figure().add_annotation(text=f"Error: {e}")


def _build_progress_stats(records: list[dict]) -> html.Div:
    """Build progress statistics display."""
    total = len(records)
    failed = sum(1 for r in records if r.get("failed", False))
    valid = total - failed
    success_pct = (100 * valid / total) if total > 0 else 0

    best_record = max(
        [r for r in records if not r.get("failed", False)],
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
                            html.H6("Total Trials", className="text-muted"),
                            html.H4(str(total), className="text-info"),
                        ],
                        className="col-12 col-md-3",
                    ),
                    html.Div(
                        [
                            html.H6("Success Rate", className="text-muted"),
                            html.H4(f"{success_pct:.1f}%", className="text-success"),
                        ],
                        className="col-12 col-md-3",
                    ),
                    html.Div(
                        [
                            html.H6("Failed", className="text-muted"),
                            html.H4(str(failed), className="text-danger"),
                        ],
                        className="col-12 col-md-3",
                    ),
                    html.Div(
                        [
                            html.H6("Best Score", className="text-muted"),
                            html.H4(f"{best_score:.4f}", className="text-warning"),
                            html.Small(best_trial, className="text-muted"),
                        ],
                        className="col-12 col-md-3",
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

    rows = []
    for record in records:
        rows.append(_build_progress_card(record))

    return html.Div(rows, style={"display": "grid", "gap": "12px"})


def _get_live_score(run: dict) -> tuple[float | None, bool]:
    """Return (value, is_final) for the best available score from a run dict.

    Priority:
      1. run["score"]    — final score written by write_score_and_stop (is_final=True)
      2. run["hold_time"]— live tally for pickup tests; equals the final score in progress
      Returns (None, False) when nothing meaningful is available yet.
    """
    score = run.get("score")
    if isinstance(score, (int, float)):
        return float(score), True
    hold_time = run.get("hold_time")
    if isinstance(hold_time, (int, float)):
        return float(hold_time), False
    return None, False


def _find_earliest_not_done(records: list[dict]) -> str | None:
    """Return the card ID of the first trial that is not yet in a terminal state."""
    terminal = {"done", "failed", "error", "pruned", "skipped", "cancelled"}
    for record in records:
        # Use the same state determination as the display
        state = _get_trial_actual_state(record)
        if state not in terminal:
            return f"trial-card-{record.get('gen_index', 0):04d}-{record.get('trial_index', 0):04d}"
    return None


# ─────────────────────────────────────────────────────────────
# Main Dash App
# ─────────────────────────────────────────────────────────────


def create_app() -> Dash:
    """Create and configure the Dash application."""
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
                    html.H1(
                        "ShapeOPT Analysis Dashboard",
                        className="text-center mb-3 mt-3",
                    ),
                    html.P(
                        "Unified visualization of optimization performance, parameters, and progress",
                        className="text-center text-muted mb-4",
                    ),
                ]
            ),
            dcc.Tabs(
                id="tabs",
                value="performance",
                children=[
                    dcc.Tab(
                        label="📊 Performance & Leaderboard",
                        value="performance",
                        children=build_performance_tab(),
                    ),
                    dcc.Tab(
                        label="📈 Progress Monitor",
                        value="progress",
                        children=build_progress_tab(),
                    ),
                    dcc.Tab(
                        label="🎛️ Parameter Bounds",
                        value="bounds",
                        children=build_param_bounds_tab(),
                    ),
                ],
            ),
        ],
        className="py-3",
    )

    # Callbacks
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
            # customdata layout: [hover_html, gen_name, trial_name]
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
        except Exception as e:
            return html.Div(f"Could not load trial: {e}", className="text-muted")

    @callback(
        [
            Output("performance-graph", "figure"),
            Output("leaderboard-table", "children"),
        ],
        Input("tabs", "value"),
        Input("performance-interval", "n_intervals"),
    )
    def update_performance(tab, _):
        # Always update data, but only render if on the performance tab
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

    # History is always rendered as a heatmap; removed manual toggle.

    @callback(
        [Output("progress-stats", "children"), Output("progress-grid", "children")],
        Input("progress-interval", "n_intervals"),
    )
    def update_progress(_):
        records, summaries = _load_data()
        current_records = _current_generation_records(records)
        stats = _build_progress_stats(current_records)
        grid = _build_progress_grid(current_records)
        return stats, grid

    @callback(
        Output("jump-running-target-store", "data"),
        Input("jump-running-trial", "n_clicks"),
        Input("progress-interval", "n_intervals"),
        State("jump-auto-enabled", "data"),
    )
    def update_jump_target(_clicks, _intervals, auto_enabled):
        # Decide whether to emit a jump target: either user clicked the button
        # or auto-jump is enabled during an interval tick.
        try:
            from dash import ctx
        except Exception:
            ctx = None

        triggered = None
        if ctx is not None:
            triggered = getattr(ctx, "triggered_id", None)

        is_auto = triggered == "progress-interval"

        # If this was an interval tick and auto-jump is disabled, do nothing
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
            // For auto-jumps, re-check the store at execution time.
            // The scroll-detection clientside callback (fast) has already updated
            // the store by the time this fires (after the slower server round-trip),
            // so this catches the race where the server emitted a target before
            // learning the user had scrolled.
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

    # Detect USER-initiated scroll (wheel / touch / keyboard) via event listeners.
    # Polling window.pageYOffset does NOT work here because the auto-jump itself calls
    # scrollIntoView which moves the page and would immediately disable auto-jump.
    # Using event listeners we only catch real user gestures.
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

    # "Top" button: scroll to top and disable auto-jump
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

    # jump-top-output is unused but kept to satisfy the existing layout element
    app.clientside_callback(
        "function(n) { return window.dash_clientside.no_update; }",
        Output("jump-top-output", "children"),
        Input("jump-top-button", "n_clicks"),
    )

    # Auto-jump toggle — clientside so the button responds instantly without a server round-trip
    app.clientside_callback(
        "function(n, cur) { if (!n) return window.dash_clientside.no_update; return !cur; }",
        Output("jump-auto-enabled", "data", allow_duplicate=True),
        Input("jump-auto-toggle", "n_clicks"),
        State("jump-auto-enabled", "data"),
        prevent_initial_call=True,
    )
    # Label always mirrors the store — updated by ANY source that changes the store
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
    """Launch the Dash dashboard server."""
    print(f"[info] Starting ShapeOPT Dashboard on http://localhost:{port}")

    os.environ["WERKZEUG_RUN_MAIN"] = "false"
    os.environ.pop("WERKZEUG_SERVER_FD", None)

    app = create_app()
    launch_url = f"http://localhost:{port}/?v={int(time.time())}"

    if open_browser:
        # Open browser after a short delay to let server start
        def open_browser_delayed():
            time.sleep(2)
            webbrowser.open_new_tab(launch_url)

        thread = threading.Thread(target=open_browser_delayed, daemon=True)
        thread.start()

    app.run(debug=False, use_reloader=False, port=port, host="127.0.0.1")


if __name__ == "__main__":
    launch_dashboard()
