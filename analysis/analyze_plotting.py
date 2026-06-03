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

import logging
import os

# Suppress Werkzeug and Dash logs
os.environ.pop("WERKZEUG_RUN_MAIN", None)
os.environ.pop("WERKZEUG_SERVER_FD", None)
os.environ.pop("WERKZEUG_SERVER_FD_DEF", None)
logging.getLogger("werkzeug").setLevel(logging.ERROR)
logging.getLogger("dash").setLevel(logging.ERROR)
logging.getLogger("dash.dash").setLevel(logging.ERROR)

from analyze_io import load_all_trials
from plotting.compute import (
    C_BG,
    C_BANNER,
    C_BORDER,
    C_SECTION,
    _calculate_smart_ticks,
    _collect_all_test_names,
    compute_plot_data,
)
from plotting.traces import (
    _build_avg_traces,
    _build_bar_traces,
    _build_final_ticks,
    _build_hover_overlay,
)
from analysis._dash_app import DASH_AVAILABLE, run_dash_app


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

    xs = plot_data["xs"]
    bar_width = max(0.4, (max(xs) - min(xs) + 1) / len(xs) * 0.8) if xs else 0.8

    bar_traces = _build_bar_traces(records, plot_data, all_test_names)
    hover_overlay = _build_hover_overlay(records, plot_data, all_test_names, bar_width)
    final_ticks = _build_final_ticks(plot_data, bar_width)
    avg_traces = _build_avg_traces(plot_data, all_test_names)
    all_traces = bar_traces + [hover_overlay, final_ticks] + avg_traces

    fig = go.Figure(data=all_traces)

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

    gen_ticks = plot_data["gen_tick_positions"]
    gen_labels = plot_data["gen_tick_labels"]
    filtered_tick_vals, filtered_tick_labels = _calculate_smart_ticks(gen_ticks, gen_labels)

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

    fig.update_xaxes(range=[x_min - x_pad, x_max + x_pad])
    fig.update_yaxes(range=[y_min - y_pad, y_max + y_pad])
    fig.add_hline(y=0, line_dash="solid", line_color=C_BORDER, line_width=1, layer="below")

    if DASH_AVAILABLE:
        run_dash_app(fig, records, plot_data, all_test_names, bar_width)
    else:
        print("[warn] Dash not available — falling back to static figure (open manually).")
        fig.show()
