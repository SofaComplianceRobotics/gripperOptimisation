"""Traces: Plotly trace builders and graph construction functions."""

import plotly.graph_objects as go

from .colors import C_AVG, C_BEST, C_FINAL
from .compute import (
    _calculate_smart_ticks,
    _compute_contributions,
    _test_color,
)

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

    # customdata[0] = hover HTML, customdata[1] = gen_name, customdata[2] = trial_name
    customdata = [
        [
            hover_texts[i],
            records[i].get("gen_name", ""),
            records[i].get("trial_name", ""),
        ]
        for i in range(len(records))
    ]

    trace = go.Bar(
        x=xs,
        y=y_vals,
        base=0,
        width=[bar_width] * len(xs),
        marker=dict(color="rgba(0,0,0,0)", line=dict(width=0)),
        customdata=customdata,
        hovertemplate="%{customdata[0]}<extra></extra>",
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
        visible="legendonly",  # Hidden by default
        showlegend=True,
    )
    return trace


def _build_avg_traces(plot_data: dict, all_test_names: list[str]) -> list[go.Scatter]:
    """Build rolling average and best-so-far traces."""
    traces = []

    # Rolling average
    avg_x, avg_y = plot_data["avg_x"], plot_data["avg_y"]
    if avg_x:
        from dashboard.analyze_config import CENTERED_AVG_HALF_WINDOW

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
