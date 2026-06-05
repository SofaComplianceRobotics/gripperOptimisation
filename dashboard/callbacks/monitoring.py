"""Dashboard callbacks for monitoring tabs."""

from __future__ import annotations

from pathlib import Path

import plotly.graph_objects as go
from dash import Input, Output, State, ctx, html

from data.cache import _current_generation_records, _load_data, _read_json
from plotting.bounds import _build_param_bounds_graph
from plotting.performance import _build_leaderboard_html, _build_performance_graph
from ui.progress import (
    _build_progress_grid,
    _build_progress_stats,
    _build_trial_detail,
    _find_earliest_not_done,
)


LAB_ROOT = Path(__file__).resolve().parents[2]
TRIALS_DIR = LAB_ROOT / "runtime" / "trials"


def register_monitoring_callbacks(app) -> None:
    """Register monitoring callbacks: performance graph, progress, bounds, and jump controls."""

    @app.callback(
        Output("trial-detail-panel", "children"),
        Input("performance-graph", "clickData"),
    )
    def on_trial_click(click_data):
        """Show the detail panel for the trial clicked on the performance graph.

        Extracts gen/trial identifiers from the point's customdata, loads the
        corresponding ``trial_state.json``, and builds the detail panel HTML.

        Args:
            click_data: Plotly clickData dict; each point carries
                ``customdata = [score, gen_name, trial_name]``.

        Returns:
            Dash HTML component with trial detail, or an empty Div if no data.
        """
        if not click_data:
            return html.Div()
        try:
            point = click_data["points"][0]
            cd = point.get("customdata")
            if not cd or len(cd) < 3:
                return html.Div()
            gen_name, trial_name = cd[1], cd[2]  # customdata layout: [score, gen_name, trial_name]
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

    @app.callback(
        [
            Output("performance-graph", "figure"),
            Output("leaderboard-table", "children"),
        ],
        Input("tabs", "value"),
        Input("performance-interval", "n_intervals"),
    )
    def update_performance(tab, _):
        """Rebuild the performance graph and leaderboard for the performance tab.

        Returns empty components when a different tab is active to avoid
        rebuilding expensive graphs on every interval tick.

        Args:
            tab: Currently active tab value string.
            _: Interval tick (unused).

        Returns:
            Tuple of (Plotly Figure, leaderboard HTML component).
        """
        records, summaries = _load_data()
        if tab != "performance":
            return go.Figure(), html.Div()
        fig = _build_performance_graph(records, summaries)
        leaderboard = _build_leaderboard_html(records)
        return fig, leaderboard

    @app.callback(
        Output("param-bounds-graph", "figure"),
        Input("bounds-interval", "n_intervals"),
    )
    def update_bounds(_):
        """Rebuild the parameter bounds heatmap.

        Args:
            _: Interval tick (unused).

        Returns:
            Plotly Figure for the param bounds graph.
        """
        return _build_param_bounds_graph(show_heatmap=True)

    @app.callback(
        [Output("progress-stats", "children"), Output("progress-grid", "children")],
        Input("progress-interval", "n_intervals"),
    )
    def update_progress(_):
        """Rebuild the progress stats and trial grid for the current generation.

        Args:
            _: Interval tick (unused).

        Returns:
            Tuple of (stats HTML component, grid HTML component).
        """
        records, summaries = _load_data()
        current_records = _current_generation_records(records)
        stats = _build_progress_stats(current_records, records)
        grid = _build_progress_grid(current_records)
        return stats, grid

    @app.callback(
        Output("jump-running-target-store", "data"),
        Input("jump-running-trial", "n_clicks"),
        Input("progress-interval", "n_intervals"),
        State("jump-auto-enabled", "data"),
    )
    def update_jump_target(_clicks, _intervals, auto_enabled):
        """Compute the DOM id of the earliest in-progress trial to scroll to.

        Called on both manual button click and interval tick. On interval tick,
        skips the lookup when auto-jump is disabled to avoid unnecessary work.

        Args:
            _clicks: Jump button click count.
            _intervals: Interval tick count.
            auto_enabled: Bool store value controlling auto-scroll behaviour.

        Returns:
            Dict with keys ``target_id`` (str or None) and ``auto`` (bool).
        """
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