"""
analyze_plotting.py — Plotly interactive visualization with smooth interactivity.

Creates performance plots with per-test contribution bars (diverging stacked),
rolling averages, and per-generation trends. Preserves zoom/pan during live updates.
"""

# Auto-install plotly if not available
try:
    import plotly.graph_objects as go
    import plotly.io as pio
    from plotly.subplots import make_subplots
except ImportError:
    print("[info] Plotly not found. Installing...")
    import subprocess
    import sys

    subprocess.check_call([sys.executable, "-m", "pip", "install", "plotly", "-q"])
    import plotly.graph_objects as go
    import plotly.io as pio
    from plotly.subplots import make_subplots

    print("[info] Plotly installed successfully.")
try:
    # Dash (for live web-based updates)
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
os.environ["WERKZEUG_RUN_MAIN"] = "true"
# Clear any leftover Werkzeug server FD environment variables
os.environ.pop("WERKZEUG_SERVER_FD", None)
os.environ.pop("WERKZEUG_SERVER_FD_DEF", None)
logging.getLogger("werkzeug").setLevel(logging.ERROR)
logging.getLogger("dash").setLevel(logging.ERROR)
logging.getLogger("dash.dash").setLevel(logging.ERROR)

from analyze_config import CENTERED_AVG_HALF_WINDOW, LIVE_REFRESH_SECONDS
from analyze_io import load_all_trials

# ---------------------------------------------------------------------------
# Colour palette — matches UI.py SLICE_COLORS
# ---------------------------------------------------------------------------
TEST_COLORS = [
    "#404867",  # (matches C_BANNER in UI.py)
    "#6b7aad",
    "#9aa3cc",
    "#2c3e6b",
    "#c0392b",
    "#2ecc71",
    "#e67e22",
    "#9b59b6",
]

NEG_ALPHA = 0.40  # alpha for negative-contribution segments
NEG_HATCH = (
    "////"  # hatch for negative segments (note: Plotly doesn't support hatching)
)

C_BANNER = "#404867"
C_BG = "#ffffff"
C_SECTION = "#fafbfc"
C_BORDER = "#d0d3d8"
C_FINAL = "#c0392b"  # final-score tick colour
C_AVG = "#2ecc71"  # rolling average line
C_BEST = "#e74c3c"  # best-so-far line


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_all_test_names(records: list[dict]) -> list[str]:
    """Return a stable ordered list of every unique test name seen across all records."""
    seen: list[str] = []
    for r in records:
        for name in (r.get("test_scores") or {}).keys():
            if name not in seen:
                seen.append(name)
    return seen


def _test_color(test_name: str, name_order: list[str]) -> str:
    """Return the hex color assigned to a test, consistent across the whole plot."""
    try:
        idx = name_order.index(test_name)
    except ValueError:
        idx = abs(hash(test_name)) % len(TEST_COLORS)
    return TEST_COLORS[idx % len(TEST_COLORS)]


def _compute_contributions(record: dict) -> dict[str, float]:
    """Compute per-test weighted contribution for one trial record.

    contribution_i = normalize(aggregate_score_i) * weight_pct_i

    Falls back gracefully when test_scores is absent (legacy records).
    """
    test_scores: dict = record.get("test_scores") or {}

    if not test_scores:
        return {"score": float(record.get("final_score", record.get("score", 0.0)))}

    contributions: dict[str, float] = {}
    for test_name, test_info in test_scores.items():
        if not isinstance(test_info, dict):
            continue
        agg = float(test_info.get("aggregate_score", 0.0) or 0.0)
        raw_max = test_info.get("max_score")
        # Treat missing/None as legacy (score already normalised); 0.0 means unknown.
        max_score = float(raw_max) if raw_max is not None else 1.0
        wpct = float(test_info.get("weight_pct", 0.0) or 0.0)
        norm = min(agg / max_score, 1.0) if max_score > 0 else 0.0
        contributions[test_name] = norm * wpct

    return (
        contributions
        if contributions
        else {"score": float(record.get("final_score", record.get("score", 0.0)))}
    )


# ---------------------------------------------------------------------------
# Plot-data builder
# ---------------------------------------------------------------------------


def compute_plot_data(records: list[dict], all_test_names: list[str]) -> dict:
    """Pre-compute all series needed for a full plot redraw.

    Args:
        records: Trial records from analyze_io.load_all_trials().
        all_test_names: Ordered unique test names (from _collect_all_test_names).

    Returns:
        dict with keys: xs, final_scores, failed_mask, is_complete, contributions,
        avg_x, avg_y, best_x, best_y, gen_tick_positions, gen_tick_labels.
    """
    xs = [r["chron"] for r in records]
    contributions = [_compute_contributions(r) for r in records]
    final_scores = [sum(c.values()) for c in contributions]
    failed_mask = [bool(r.get("failed", False)) for r in records]
    is_complete = [bool(r.get("is_complete", True)) for r in records]
    contributions = [_compute_contributions(r) for r in records]

    # Centred rolling average
    avg_x, avg_y = [], []
    for i, r in enumerate(records):
        lo = max(0, i - CENTERED_AVG_HALF_WINDOW)
        hi = min(len(records) - 1, i + CENTERED_AVG_HALF_WINDOW)
        window = records[lo : hi + 1]
        scores = [sum(_compute_contributions(w).values()) for w in window]
        avg_x.append(r["chron"])
        avg_y.append(sum(scores) / len(scores))

    # Best-so-far
    best_x, best_y = [], []
    running_best = None
    for i, r in enumerate(records):
        if not failed_mask[i]:
            fs = final_scores[i]
            if running_best is None or fs > running_best:
                running_best = fs
        if running_best is not None:
            best_x.append(r["chron"])
            best_y.append(running_best)

    # Per-test rolling averages
    per_test_avg: dict[str, tuple[list, list]] = {}
    for test_name in all_test_names:
        avg_x_t, avg_y_t = [], []
        for i, r in enumerate(records):
            lo = max(0, i - CENTERED_AVG_HALF_WINDOW)
            hi = min(len(records) - 1, i + CENTERED_AVG_HALF_WINDOW)
            window_scores = [
                _compute_contributions(records[k]).get(test_name, 0.0)
                for k in range(lo, hi + 1)
            ]
            avg_x_t.append(r["chron"])
            avg_y_t.append(sum(window_scores) / len(window_scores))
        per_test_avg[test_name] = (avg_x_t, avg_y_t)

    # Generation tick marks (one per unique generation boundary)
    gen_tick_positions, gen_tick_labels = [], []
    prev_gen = None
    for r in records:
        if r["gen_index"] != prev_gen:
            gen_tick_positions.append(r["chron"])
            gen_tick_labels.append(str(r["gen_index"]))
        prev_gen = r["gen_index"]

    return {
        "xs": xs,
        "final_scores": final_scores,
        "failed_mask": failed_mask,
        "is_complete": is_complete,
        "contributions": contributions,
        "avg_x": avg_x,
        "avg_y": avg_y,
        "best_x": best_x,
        "best_y": best_y,
        "per_test_avg": per_test_avg,
        "gen_tick_positions": gen_tick_positions,
        "gen_tick_labels": gen_tick_labels,
    }


# ---------------------------------------------------------------------------
# Plotly trace builders
# ---------------------------------------------------------------------------


def _build_bar_traces(
    records: list[dict],
    plot_data: dict,
    all_test_names: list[str],
) -> list[go.Bar]:
    """Build diverging stacked bar traces for Plotly."""
    traces = []
    xs = plot_data["xs"]
    contributions = plot_data["contributions"]
    failed_mask = plot_data["failed_mask"]
    is_complete = plot_data["is_complete"]

    # For each test, create a stacked bar trace (no hover on segments)
    for test_name in all_test_names:
        y_vals = []
        colors_list = []
        opacity_list = []

        for i, (x, contrib, failed, complete) in enumerate(
            zip(xs, contributions, failed_mask, is_complete)
        ):
            val = contrib.get(test_name, 0.0)
            y_vals.append(val)

            # Color and opacity based on state
            color = _test_color(test_name, all_test_names)
            colors_list.append(color)
            alpha = 0.3 if failed else 1.0
            alpha *= 0.5 if not complete else 1.0
            opacity_list.append(alpha)

        trace = go.Bar(
            x=xs,
            y=y_vals,
            name=test_name,
            uid=f"bar-{test_name}",
            marker=dict(
                color=colors_list,
                opacity=opacity_list,
                line=dict(color=_test_color(test_name, all_test_names), width=0.5),
            ),
            hoverinfo="skip",
            showlegend=True,
        )
        traces.append(trace)

    return traces


def _build_hover_overlay(
    records: list[dict],
    plot_data: dict,
    all_test_names: list[str],
    bar_width: float,
) -> go.Bar:
    """Build an invisible bar overlay so hover works across the whole trial bar."""
    xs = plot_data["xs"]
    contributions = plot_data["contributions"]
    hover_texts = []
    y_vals = []

    for i, contrib in enumerate(contributions):
        r = records[i]
        gen = r.get("gen_index", "?")
        trial_id = r.get("trial_id", i)
        final_score = sum(contrib.values())

        detail_lines = [
            f"<b>Gen {gen} | Trial {trial_id}</b>",
            f"<b>Total Score: {final_score:.4f}</b>",
            "─────────────────",
        ]
        for tn in all_test_names:
            score = contrib.get(tn, 0.0)
            detail_lines.append(f"{tn}: {score:.4f}")

        hover_texts.append("<br>".join(detail_lines))
        y_vals.append(final_score)

    trace = go.Bar(
        x=xs,
        y=y_vals,
        base=0,
        width=[bar_width] * len(xs),
        marker=dict(color="rgba(0,0,0,0)", line=dict(width=0)),
        customdata=hover_texts,
        hovertemplate="%{customdata}<extra></extra>",
        hoverlabel=dict(
            bgcolor="#d7ecff",
            bordercolor="#9ec5fe",
            font=dict(color="#16324f"),
        ),
        showlegend=False,
        name="hover",
        uid="hover-overlay",
    )
    return trace


def _build_final_ticks(plot_data: dict, bar_width: float) -> go.Scatter:
    """Build short horizontal tick segments (one per trial) showing final score.

    Uses a single Scatter trace with NaN separators so segments are not connected.
    """
    xs = plot_data["xs"]
    final_scores = plot_data["final_scores"]
    x_segments = []
    y_segments = []

    halfw = bar_width / 2.0
    for x, s in zip(xs, final_scores):
        x_segments.extend([x - halfw, x + halfw, None])
        y_segments.extend([s, s, None])

    trace = go.Scatter(
        x=x_segments,
        y=y_segments,
        mode="lines",
        name="Final score",
        uid="final-score",
        line=dict(color=C_FINAL, width=2),
        hoverinfo="skip",
        showlegend=True,
    )
    return trace


def _build_avg_traces(plot_data: dict, all_test_names: list[str]) -> list[go.Scatter]:
    """Build rolling average and best-so-far traces."""
    traces = []

    # Rolling average
    avg_x, avg_y = plot_data["avg_x"], plot_data["avg_y"]
    if avg_x:
        trace_avg = go.Scatter(
            x=avg_x,
            y=avg_y,
            mode="lines",
            name=f"Rolling avg (±{CENTERED_AVG_HALF_WINDOW})",
            uid="rolling-avg",
            line=dict(color=C_AVG, width=2, dash="dash"),
            hoverinfo="skip",
            showlegend=True,
        )
        traces.append(trace_avg)

    # Best-so-far
    best_x, best_y = plot_data["best_x"], plot_data["best_y"]
    if best_x:
        trace_best = go.Scatter(
            x=best_x,
            y=best_y,
            mode="lines",
            name="Best so far",
            uid="best-so-far",
            line=dict(color=C_BEST, width=2),
            hoverinfo="skip",
            showlegend=True,
        )
        traces.append(trace_best)

    # Per-test rolling averages
    per_test_avg = plot_data.get("per_test_avg", {})
    for test_name in all_test_names:
        if test_name in per_test_avg:
            t_x, t_y = per_test_avg[test_name]
            if t_x:
                trace_t = go.Scatter(
                    x=t_x,
                    y=t_y,
                    mode="lines",
                    name=f"~{test_name} avg",
                    uid=f"avg-{test_name}",
                    line=dict(
                        color=_test_color(test_name, all_test_names),
                        width=1.5,
                        dash="dashdot",
                    ),
                    hoverinfo="skip",
                    visible="legendonly",  # Hidden by default
                    showlegend=True,
                )
                traces.append(trace_t)

    return traces


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

    fig.update_layout(
        title={
            "text": "Gripper Optimization — Per-Test Contributions",
            "font": {"size": 18, "color": C_BANNER},
            "x": 0.5,
            "xanchor": "center",
        },
        xaxis=dict(
            title="Generation",
            tickvals=gen_ticks,
            ticktext=gen_labels,
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
                return {"xrange": None, "yrange": None, "visibility": visibility}

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
