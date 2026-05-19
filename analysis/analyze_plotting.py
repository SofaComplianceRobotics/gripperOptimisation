"""
analyze_plotting.py — Main entry point for interactive Plotly visualization.

Entry point for plot_combined() which orchestrates live Dash updates of
performance plots with per-test contribution bars, rolling averages, and trends.

Implementation details in: plotting.compute (math) and plotting.traces (visualization)
"""

# Auto-install dependencies
try:
    import plotly.graph_objects as go
except ImportError:
    print("[info] Plotly not found. Installing...")
    import subprocess
    import sys

    subprocess.check_call([sys.executable, "-m", "pip", "install", "plotly", "-q"])
    import plotly.graph_objects as go

try:
    from dash import Dash, dcc, html
    from dash.dependencies import Input, Output, State

    DASH_AVAILABLE = True
except Exception:
    DASH_AVAILABLE = False
    try:
        import subprocess, sys

        subprocess.check_call([sys.executable, "-m", "pip", "install", "dash", "-q"])
        from dash import Dash, dcc, html
        from dash.dependencies import Input, Output, State

        DASH_AVAILABLE = True
        print("[info] Dash installed successfully.")
    except Exception as exc:
        print(f"[warn] Dash not available and automatic install failed: {exc}")

import threading
import time
import webbrowser
import logging
import os
import sys
import subprocess

# Suppress Werkzeug and Dash logs
os.environ.pop("WERKZEUG_RUN_MAIN", None)
os.environ.pop("WERKZEUG_SERVER_FD", None)
os.environ.pop("WERKZEUG_SERVER_FD_DEF", None)
logging.getLogger("werkzeug").setLevel(logging.ERROR)
logging.getLogger("dash").setLevel(logging.ERROR)
logging.getLogger("dash.dash").setLevel(logging.ERROR)

from analyze_config import LIVE_REFRESH_SECONDS
from analyze_io import load_all_trials
from plotting.compute import (
    _collect_all_test_names,
    compute_plot_data,
    _calculate_smart_ticks,
    C_BANNER,
    C_BG,
    C_SECTION,
    C_BORDER,
)
from plotting.traces import (
    _build_bar_traces,
    _build_hover_overlay,
    _build_final_ticks,
    _build_avg_traces,
)

# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def plot_combined(records: list[dict], summaries: list[dict]) -> None:
    """Plot per-test contribution bars, rolling average, and best-so-far using Plotly.

    Args:
        records: Trial records from analyze_io.load_all_trials.
        summaries: Generation summary records (unused; kept for API symmetry).
    """
    if not records:
        print("[warn] No trial data to plot.")
        return

    _ = summaries

    all_test_names = _collect_all_test_names(records)
    plot_data = compute_plot_data(records, all_test_names)

    # Compute bar width (used for final-score tick length)
    xs = plot_data["xs"]
    bar_width = max(0.4, (max(xs) - min(xs) + 1) / len(xs) * 0.8) if xs else 0.8

    # Build traces
    bar_traces = _build_bar_traces(records, plot_data, all_test_names)
    hover_overlay = _build_hover_overlay(records, plot_data, all_test_names, bar_width)
    final_ticks = _build_final_ticks(plot_data, bar_width)
    avg_traces = _build_avg_traces(plot_data, all_test_names)
    all_traces = bar_traces + [hover_overlay, final_ticks] + avg_traces

    # Create figure
    fig = go.Figure(data=all_traces)

    # Calculate axis limits
    all_ys = list(plot_data["final_scores"])
    for contrib in plot_data["contributions"]:
        pos = sum(v for v in contrib.values() if v > 0)
        neg = sum(v for v in contrib.values() if v < 0)
        all_ys.extend([pos, neg])
    if plot_data["avg_y"]:
        all_ys.extend(plot_data["avg_y"])
    if plot_data["best_y"]:
        all_ys.extend(plot_data["best_y"])

    y_min, y_max = min(all_ys) if all_ys else 0, max(all_ys) if all_ys else 1
    y_pad = max(1.0, abs(y_max - y_min) * 0.08)

    xs = plot_data["xs"]
    x_min, x_max = min(xs), max(xs)
    x_pad = max(1.0, (x_max - x_min) * 0.02)

    # Update layout with buttons and interactivity
    gen_ticks = plot_data["gen_tick_positions"]
    gen_labels = plot_data["gen_tick_labels"]

    # Calculate initial smart ticks
    filtered_tick_vals, filtered_tick_labels = _calculate_smart_ticks(
        gen_ticks, gen_labels
    )

    fig.update_layout(
        title={
            "text": "Gripper Optimization — Per-Test Contributions",
            "font": {"size": 18, "color": C_BANNER},
            "x": 0.5,
            "xanchor": "center",
        },
        xaxis=dict(
            title="Generation",
            tickvals=filtered_tick_vals,
            ticktext=filtered_tick_labels,
            showgrid=True,
            gridwidth=1,
            gridcolor="rgba(200,200,200,0.3)",
            zeroline=False,
        ),
        yaxis=dict(
            title="Score contribution",
            showgrid=True,
            gridwidth=1,
            gridcolor="rgba(200,200,200,0.3)",
            zeroline=True,
            zerolinewidth=1,
            zerolinecolor=C_BORDER,
        ),
        plot_bgcolor=C_SECTION,
        paper_bgcolor=C_BG,
        hovermode="closest",
        uirevision="live-plot",
        barmode="relative",
        height=800,
        margin=dict(b=100, l=80, r=80, t=100),
        font=dict(family="Arial, sans-serif", size=11),
        legend=dict(
            orientation="v",
            yanchor="top",
            y=0.99,
            xanchor="right",
            x=0.99,
            bgcolor="rgba(255,255,255,0.8)",
            bordercolor=C_BORDER,
            borderwidth=1,
            uirevision="live-plot",
        ),
    )

    # Set axis limits
    fig.update_xaxes(range=[x_min - x_pad, x_max + x_pad])
    fig.update_yaxes(range=[y_min - y_pad, y_max + y_pad])

    # Add zero line
    fig.add_hline(
        y=0, line_dash="solid", line_color=C_BORDER, line_width=1, layer="below"
    )

    # Use Dash for live-updating web view (preserves zoom/pan when possible)
    if DASH_AVAILABLE:
        try:
            app = Dash(__name__, suppress_callback_exceptions=True)

            def _make_plot_state() -> dict:
                visibility = {}
                for trace in fig.data:
                    uid = getattr(trace, "uid", None)
                    if uid:
                        visibility[uid] = getattr(trace, "visible", True)
                return {
                    "xrange": None,
                    "yrange": None,
                    "visibility": visibility,
                    "gen_tick_positions": plot_data["gen_tick_positions"],
                    "gen_tick_labels": plot_data["gen_tick_labels"],
                }

            app.layout = html.Div(
                [
                    dcc.Graph(id="plot", figure=fig, config={"displayModeBar": True}),
                    dcc.Store(id="plot-state", data=_make_plot_state()),
                    dcc.Interval(
                        id="interval",
                        interval=int(LIVE_REFRESH_SECONDS * 1000),
                        n_intervals=0,
                    ),
                ],
                style={"width": "100%", "height": "100%"},
            )

            @app.callback(
                Output("plot-state", "data"),
                [Input("plot", "relayoutData"), Input("plot", "restyleData")],
                [State("plot", "figure"), State("plot-state", "data")],
            )
            def _update_plot_state(relayout, restyle, current_figure, plot_state):
                state = plot_state or _make_plot_state()

                if relayout:
                    if "xaxis.range[0]" in relayout and "xaxis.range[1]" in relayout:
                        state["xrange"] = [
                            relayout["xaxis.range[0]"],
                            relayout["xaxis.range[1]"],
                        ]
                    elif "xaxis.range" in relayout:
                        state["xrange"] = relayout["xaxis.range"]

                    if "yaxis.range[0]" in relayout and "yaxis.range[1]" in relayout:
                        state["yrange"] = [
                            relayout["yaxis.range[0]"],
                            relayout["yaxis.range[1]"],
                        ]
                    elif "yaxis.range" in relayout:
                        state["yrange"] = relayout["yaxis.range"]

                if restyle and current_figure:
                    try:
                        changes, trace_indices = restyle
                    except Exception:
                        changes, trace_indices = {}, []

                    if not isinstance(trace_indices, (list, tuple)):
                        trace_indices = [trace_indices]

                    visible_change = (
                        changes.get("visible") if isinstance(changes, dict) else None
                    )
                    if visible_change is not None:
                        if isinstance(visible_change, (list, tuple)):
                            visible_values = list(visible_change)
                        else:
                            visible_values = [visible_change] * max(
                                1, len(trace_indices)
                            )

                        for idx_pos, trace_index in enumerate(trace_indices):
                            if trace_index is None:
                                continue
                            if trace_index < len(current_figure.get("data", [])):
                                trace_info = current_figure["data"][trace_index]
                                uid = (
                                    trace_info.get("uid")
                                    or trace_info.get("name")
                                    or str(trace_index)
                                )
                                state.setdefault("visibility", {})[uid] = (
                                    visible_values[
                                        min(idx_pos, len(visible_values) - 1)
                                    ]
                                )

                return state

            @app.callback(
                Output("plot", "figure"),
                Input("interval", "n_intervals"),
                State("plot-state", "data"),
            )
            def _update(n_intervals, plot_state):
                try:
                    updated = load_all_trials()
                    use_records = updated if updated else records

                    new_test_names = _collect_all_test_names(use_records)
                    new_plot_data = compute_plot_data(use_records, new_test_names)

                    new_bar_traces = _build_bar_traces(
                        use_records, new_plot_data, new_test_names
                    )
                    new_hover = _build_hover_overlay(
                        use_records, new_plot_data, new_test_names, bar_width
                    )
                    new_final = _build_final_ticks(new_plot_data, bar_width)
                    new_avg_traces = _build_avg_traces(new_plot_data, new_test_names)

                    new_fig = go.Figure(
                        data=new_bar_traces + [new_hover, new_final] + new_avg_traces
                    )
                    # copy layout settings from original figure
                    new_fig.update_layout(fig.layout)

                    plot_state = plot_state or {}
                    visibility_map = plot_state.get("visibility", {})
                    for trace in new_fig.data:
                        uid = getattr(trace, "uid", None)
                        if uid and uid in visibility_map:
                            trace.visible = visibility_map[uid]

                    xr = plot_state.get("xrange")
                    yr = plot_state.get("yrange")

                    # Recalculate ticks based on current zoom range using current data
                    gen_ticks = new_plot_data["gen_tick_positions"]
                    gen_labels = new_plot_data["gen_tick_labels"]
                    filtered_vals, filtered_labels = _calculate_smart_ticks(
                        gen_ticks, gen_labels, xr
                    )
                    if filtered_vals:
                        new_fig.update_xaxes(
                            tickvals=filtered_vals, ticktext=filtered_labels
                        )

                    if xr:
                        new_fig.update_xaxes(range=xr)
                    if yr:
                        new_fig.update_yaxes(range=yr)

                    return new_fig
                except Exception as exc:
                    import traceback

                    print(f"[warn] Dash update failed: {exc}")
                    print(traceback.format_exc())
                    return fig

            # Run the Dash server (blocks until stopped)
            print("[plot] Dash server starting at http://127.0.0.1:8050")

            # Auto-open browser in a separate thread (allow server to start first)
            def open_browser():
                time.sleep(1.5)
                try:
                    # Try webbrowser first
                    webbrowser.open("http://127.0.0.1:8050")
                except Exception:
                    try:
                        # Fallback: use subprocess on Windows
                        if sys.platform == "win32":
                            subprocess.Popen(
                                ["start", "http://127.0.0.1:8050"], shell=True
                            )
                    except Exception:
                        pass  # Silently fail if both methods don't work

            browser_thread = threading.Thread(target=open_browser, daemon=True)
            browser_thread.start()

            # Run Dash server in production mode with proper error handling
            try:
                # Try Dash run first
                try:
                    app.run(
                        host="127.0.0.1", port=8050, debug=False, use_reloader=False
                    )
                except KeyError as ke:
                    if "WERKZEUG_SERVER_FD" in str(ke):
                        # Clear all WERKZEUG environment variables and try Flask directly
                        for key in list(os.environ.keys()):
                            if "WERKZEUG" in key:
                                os.environ.pop(key, None)
                        print(
                            "[info] Retrying server with cleaned Werkzeug environment..."
                        )
                        app.run(
                            host="127.0.0.1", port=8050, debug=False, use_reloader=False
                        )
                    else:
                        raise
            except OSError as e:
                if "Address already in use" in str(e):
                    print(
                        f"[error] Port 8050 is already in use. Is the server already running?"
                    )
                else:
                    print(f"[error] Failed to start Dash server: {e}")
            except Exception as e:
                print(f"[error] Unexpected error starting Dash server: {e}")
                import traceback

                print(traceback.format_exc())

        except Exception as e:
            print(f"[error] Failed to initialize Dash app: {e}")
            import traceback

            print(traceback.format_exc())
    else:
        print(
            "[warn] Dash not available — falling back to static figure (open manually)."
        )
        fig.show()
