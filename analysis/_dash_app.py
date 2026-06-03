"""Dash app setup, live-update callbacks, and server launch for the optimizer plot."""

import subprocess
import sys
import threading
import time
import webbrowser
import os

import plotly.graph_objects as go

try:
    from dash import Dash, dcc, html
    from dash.dependencies import Input, Output, State

    DASH_AVAILABLE = True
except Exception:
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "dash", "-q"])
        from dash import Dash, dcc, html
        from dash.dependencies import Input, Output, State

        DASH_AVAILABLE = True
        print("[info] Dash installed successfully.")
    except Exception as exc:
        print(f"[warn] Dash not available and automatic install failed: {exc}")
        DASH_AVAILABLE = False

from analyze_config import LIVE_REFRESH_SECONDS
from analyze_io import load_all_trials
from plotting.compute import _calculate_smart_ticks, _collect_all_test_names, compute_plot_data
from plotting.traces import (
    _build_avg_traces,
    _build_bar_traces,
    _build_final_ticks,
    _build_hover_overlay,
)


def _open_browser_thread() -> threading.Thread:
    """Return a daemon thread that opens the browser after a short delay."""
    def _open():
        time.sleep(1.5)
        try:
            webbrowser.open("http://127.0.0.1:8050")
        except Exception:
            try:
                if sys.platform == "win32":
                    subprocess.Popen(["start", "http://127.0.0.1:8050"], shell=True)
            except Exception:
                pass

    return threading.Thread(target=_open, daemon=True)


def _run_server(app) -> None:
    """Start the Dash server, handling Werkzeug env edge cases."""
    try:
        app.run(host="127.0.0.1", port=8050, debug=False, use_reloader=False)
    except KeyError as ke:
        if "WERKZEUG_SERVER_FD" in str(ke):
            for key in list(os.environ.keys()):
                if "WERKZEUG" in key:
                    os.environ.pop(key, None)
            print("[info] Retrying server with cleaned Werkzeug environment...")
            app.run(host="127.0.0.1", port=8050, debug=False, use_reloader=False)
        else:
            raise
    except OSError as e:
        if "Address already in use" in str(e):
            print("[error] Port 8050 is already in use. Is the server already running?")
        else:
            print(f"[error] Failed to start Dash server: {e}")
    except Exception as e:
        import traceback
        print(f"[error] Unexpected error starting Dash server: {e}")
        print(traceback.format_exc())


def run_dash_app(fig, records, plot_data, all_test_names, bar_width) -> None:
    """Build and run the Dash live-update app.

    Args:
        fig: Pre-built Plotly figure to display initially.
        records: Trial records for the live-update callback.
        plot_data: Pre-computed plot data dict (xs, contributions, etc.).
        all_test_names: Ordered list of test names.
        bar_width: Bar width used for overlay/tick sizing.
    """
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
                    state["xrange"] = [relayout["xaxis.range[0]"], relayout["xaxis.range[1]"]]
                elif "xaxis.range" in relayout:
                    state["xrange"] = relayout["xaxis.range"]
                if "yaxis.range[0]" in relayout and "yaxis.range[1]" in relayout:
                    state["yrange"] = [relayout["yaxis.range[0]"], relayout["yaxis.range[1]"]]
                elif "yaxis.range" in relayout:
                    state["yrange"] = relayout["yaxis.range"]

            if restyle and current_figure:
                try:
                    changes, trace_indices = restyle
                except Exception:
                    changes, trace_indices = {}, []
                if not isinstance(trace_indices, (list, tuple)):
                    trace_indices = [trace_indices]
                visible_change = changes.get("visible") if isinstance(changes, dict) else None
                if visible_change is not None:
                    visible_values = (
                        list(visible_change)
                        if isinstance(visible_change, (list, tuple))
                        else [visible_change] * max(1, len(trace_indices))
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
                            state.setdefault("visibility", {})[uid] = visible_values[
                                min(idx_pos, len(visible_values) - 1)
                            ]

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

                new_bar_traces = _build_bar_traces(use_records, new_plot_data, new_test_names)
                new_hover = _build_hover_overlay(use_records, new_plot_data, new_test_names, bar_width)
                new_final = _build_final_ticks(new_plot_data, bar_width)
                new_avg_traces = _build_avg_traces(new_plot_data, new_test_names)

                new_fig = go.Figure(data=new_bar_traces + [new_hover, new_final] + new_avg_traces)
                new_fig.update_layout(fig.layout)

                plot_state = plot_state or {}
                visibility_map = plot_state.get("visibility", {})
                for trace in new_fig.data:
                    uid = getattr(trace, "uid", None)
                    if uid and uid in visibility_map:
                        trace.visible = visibility_map[uid]

                xr = plot_state.get("xrange")
                yr = plot_state.get("yrange")

                gen_ticks = new_plot_data["gen_tick_positions"]
                gen_labels = new_plot_data["gen_tick_labels"]
                filtered_vals, filtered_labels = _calculate_smart_ticks(gen_ticks, gen_labels, xr)
                if filtered_vals:
                    new_fig.update_xaxes(tickvals=filtered_vals, ticktext=filtered_labels)
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

        print("[plot] Dash server starting at http://127.0.0.1:8050")
        _open_browser_thread().start()
        _run_server(app)

    except Exception as e:
        import traceback
        print(f"[error] Failed to initialize Dash app: {e}")
        print(traceback.format_exc())
