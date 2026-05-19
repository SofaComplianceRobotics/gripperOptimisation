"""Performance tab — Performance graphs and leaderboard."""

from dash import dcc, html

from analyze_config import LIVE_REFRESH_SECONDS


def build_performance_tab() -> html.Div:
    """Build the Performance tab layout.

    Returns:
        A Dash `Div` containing performance graphs and leaderboard area.
    """
    return html.Div(
        [
            html.H3("Performance", className="mb-3"),
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
