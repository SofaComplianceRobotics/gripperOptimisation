"""Performance graph and leaderboard visualization."""

import plotly.graph_objects as go

from .compute import (
    _collect_all_test_names,
    compute_plot_data,
)
from .traces import (
    _build_bar_traces,
    _build_hover_overlay,
    _build_final_ticks,
    _build_avg_traces,
)
from .colors import C_BG


def _build_performance_graph(records: list[dict], summaries: list[dict]) -> go.Figure:
    """Create a Plotly figure summarising per-test performance over trials.

    Args:
        records: Trial records list.
        summaries: Generation summaries list.

    Returns:
        A Plotly `Figure` ready for display.
    """
    if not records:
        return go.Figure().add_annotation(text="No data available")

    try:
        all_test_names = _collect_all_test_names(records)
        plot_data = compute_plot_data(records, all_test_names)

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


def _build_leaderboard_html(records: list[dict]):
    """Construct a leaderboard HTML Div showing top trials.

    Args:
        records: List of trial records.

    Returns:
        A Dash Div containing a table of top trials by score.
    """
    from dash import html

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
