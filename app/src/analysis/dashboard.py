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
from analyze_config import CENTERED_AVG_HALF_WINDOW


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


def build_performance_tab(records: list[dict], summaries: list[dict]) -> html.Div:
    """Build performance visualization tab with bars and score lines."""
    return html.Div(
        [
            html.H3("Performance & Leaderboard", className="mb-3"),
            dcc.Graph(id="performance-graph", style={"height": "600px"}),
            html.Hr(),
            html.Div(id="leaderboard-table", className="mt-4"),
            dcc.Interval(id="performance-interval", interval=5000, n_intervals=0),
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
            dcc.Graph(id="param-bounds-graph", style={"height": "600px"}),
            dcc.Interval(id="bounds-interval", interval=2000, n_intervals=0),
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
                        "Jump to earliest running trial",
                        id="jump-running-trial",
                        n_clicks=0,
                        className="btn btn-primary btn-sm",
                    ),
                    html.Span(
                        "Scrolls to the trial most likely to finish next.",
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
            dcc.Store(id="jump-auto-enabled", data=True),
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
                        "Auto-jump: On",
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
            dcc.Interval(id="progress-interval", interval=1000, n_intervals=0),
        ],
        className="p-3",
    )


# ─────────────────────────────────────────────────────────────
# Callback helpers
# ─────────────────────────────────────────────────────────────


def _load_data():
    """Load all trial data and summaries."""
    try:
        records = load_all_trials()
        summaries = load_gen_summaries()
        return records, summaries
    except Exception as e:
        print(f"[warn] Error loading data: {e}")
        return [], []


def _current_generation_records(records: list[dict]) -> list[dict]:
    if not records:
        return []

    current_gen = max(
        (record.get("gen_index", -1) for record in records),
        default=-1,
    )
    if current_gen < 0:
        return []

    return [record for record in records if record.get("gen_index", -1) == current_gen]


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


def _build_progress_card(trial_record: dict) -> html.Div:
    trial_state = _load_trial_state(trial_record) or {}
    runs = trial_state.get("runs") if isinstance(trial_state.get("runs"), list) else []
    trial_label = (
        f"{trial_record.get('gen_name', '')} / {trial_record.get('trial_name', '')}"
    )
    final_score = trial_record.get("final_score")
    state = str(
        trial_state.get("state")
        or ("done" if trial_record.get("is_complete") else "running")
    ).lower()

    run_rows = []
    if runs:
        for run in runs:
            if not isinstance(run, dict):
                continue
            pct = _run_progress_pct(run)
            run_state = str(run.get("state", "not-started")).lower()
            score = run.get("score")
            total_frames = run.get("total_frames")
            current_frame = run.get("current_frame")
            right_text = []
            if isinstance(current_frame, (int, float)) and isinstance(
                total_frames, (int, float)
            ):
                right_text.append(f"{int(current_frame)}/{int(total_frames)}")
            if isinstance(score, (int, float)):
                right_text.append(f"score {float(score):.2f}")
            right_text.append(run_state)
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
                                    ", ".join(right_text),
                                    style={"color": _state_color(run_state)},
                                ),
                            ],
                            className="d-flex justify-content-between align-items-center mb-1",
                        ),
                        html.Div(
                            [
                                html.Div(
                                    style={
                                        "width": f"{pct:.1f}%",
                                        "height": "100%",
                                        "background": _state_color(run_state),
                                        "borderRadius": "999px",
                                        "transition": "width 600ms ease",
                                        "willChange": "width",
                                    }
                                )
                            ],
                            style={
                                "height": "10px",
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


def _build_param_bounds_graph() -> go.Figure:
    """Build parameter bounds visualization."""
    try:
        from optimization.optimize_config import PARAM_SPECS

        active_specs = [p for p in PARAM_SPECS if p["min"] < p["max"]]

        if not active_specs:
            return go.Figure().add_annotation(text="No active parameters to display")

        # Find latest trial values
        latest_config = None
        best_gen, best_trial = -1, -1
        for gen_dir in TRIALS_DIR.glob("gen_*"):
            try:
                gen_num = int(gen_dir.name.split("_")[1])
            except (ValueError, IndexError):
                continue
            for trial_dir in gen_dir.glob("trial_*"):
                try:
                    trial_num = int(trial_dir.name.split("_")[1])
                except (ValueError, IndexError):
                    continue
                config_file = trial_dir / "lab_config.jsonc"
                if config_file.exists() and (gen_num, trial_num) > (
                    best_gen,
                    best_trial,
                ):
                    best_gen, best_trial = gen_num, trial_num
                    latest_config = config_file

        fig = go.Figure()

        for spec in active_specs:
            name = spec["name"]
            param_min = spec["min"]
            param_max = spec["max"]
            # Default to midpoint if no latest config
            current_val = (param_min + param_max) / 2

            # Try to extract from latest config
            if latest_config:
                try:
                    import json

                    content = latest_config.read_text()
                    # Simple JSON parsing (ignoring comments)
                    data = json.loads(content.split("//")[0])
                    current_val = data.get(name, current_val)
                except Exception:
                    pass

            # Normalize to 0-1
            normalized = (
                (current_val - param_min) / (param_max - param_min)
                if param_max > param_min
                else 0.5
            )
            normalized = max(0, min(1, normalized))

            # Color based on position
            if normalized < 0.1 or normalized > 0.9:
                color = "#f44336"  # red - critical
            elif normalized < 0.15 or normalized > 0.85:
                color = "#ff9800"  # orange - warning
            else:
                color = "#4caf50"  # green - ok

            fig.add_trace(
                go.Bar(
                    y=[name],
                    x=[normalized],
                    orientation="h",
                    marker=dict(color=color),
                    text=f"{current_val:.3f}",
                    textposition="auto",
                    hovertemplate=f"<b>{name}</b><br>Value: {current_val:.3f}<br>Range: [{param_min:.3f}, {param_max:.3f}]<extra></extra>",
                    showlegend=False,
                )
            )

        fig.update_layout(
            title="Parameter Bounds Monitor (Latest Trial)",
            xaxis_title="Position in Range (0=Min, 1=Max)",
            height=400 + len(active_specs) * 30,
            showlegend=False,
            margin={"l": 150, "r": 50, "t": 50, "b": 50},
            plot_bgcolor=C_BG,
            paper_bgcolor=C_BG,
        )
        # Hint Plotly to animate updates smoothly when figures are replaced
        try:
            fig.layout.transition = dict(duration=600, easing="cubic-in-out")
        except Exception:
            pass
        fig.update_xaxes(range=[0, 1])

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


def _find_earliest_running_trial(records: list[dict]) -> str | None:
    for record in records:
        trial_state = _load_trial_state(record) or {}
        trial_state_name = str(trial_state.get("state") or "").lower()
        if trial_state_name in {
            "done",
            "failed",
            "error",
            "pruned",
            "skipped",
            "cancelled",
        }:
            continue

        runs = (
            trial_state.get("runs") if isinstance(trial_state.get("runs"), list) else []
        )
        if any(
            str(run.get("state", "")).lower() in {"running", "launching", "not-started"}
            for run in runs
            if isinstance(run, dict)
        ):
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

    # Global data store
    records, summaries = _load_data()

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
                        children=build_performance_tab(records, summaries),
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
            dcc.Store(id="data-store", data={"records": records}),
        ],
        className="py-3",
    )

    # Callbacks
    @callback(
        [
            Output("performance-graph", "figure"),
            Output("leaderboard-table", "children"),
        ],
        Input("tabs", "value"),
        Input("performance-interval", "n_intervals"),
    )
    def update_performance(tab, _):
        if tab != "performance":
            return go.Figure(), html.Div()
        records, summaries = _load_data()
        fig = _build_performance_graph(records, summaries)
        leaderboard = _build_leaderboard_html(records)
        return fig, leaderboard

    @callback(
        Output("param-bounds-graph", "figure"),
        Input("bounds-interval", "n_intervals"),
    )
    def update_bounds(_):
        return _build_param_bounds_graph()

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
        State("data-store", "data"),
        State("jump-auto-enabled", "data"),
    )
    def update_jump_target(_clicks, _intervals, data, auto_enabled):
        # Decide whether to emit a jump target: either user clicked the button
        # or auto-jump is enabled during an interval tick.
        try:
            from dash import ctx
        except Exception:
            ctx = None

        triggered = None
        if ctx is not None:
            triggered = getattr(ctx, "triggered_id", None)

        # If this was an interval tick and auto-jump is disabled, do nothing
        if triggered == "progress-interval" and not bool(auto_enabled):
            return {"target_id": None}

        records, _summaries = _load_data()
        current_records = _current_generation_records(records)
        return {"target_id": _find_earliest_running_trial(current_records)}

    app.clientside_callback(
        """
        function(target) {
            if (!target || !target.target_id) {
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
    )

    # Clientside scroll-to-top when the Top button is pressed
    app.clientside_callback(
        """
        function(n) {
            if (!n) { return window.dash_clientside.no_update; }
            window.scrollTo({top: 0, behavior: 'smooth'});
            return window.dash_clientside.no_update;
        }
        """,
        Output("jump-top-output", "children"),
        Input("jump-top-button", "n_clicks"),
    )

    @callback(
        [Output("jump-auto-toggle", "children"), Output("jump-auto-enabled", "data")],
        Input("jump-auto-toggle", "n_clicks"),
        State("jump-auto-enabled", "data"),
    )
    def toggle_auto_jump(n, current):
        # Toggle the auto-jump enabled flag and update button label
        if not current:
            current = False
        if not n:
            # initial render
            return ("Auto-jump: On" if current else "Auto-jump: Off"), current
        new_state = not bool(current)
        return ("Auto-jump: On" if new_state else "Auto-jump: Off"), new_state

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
