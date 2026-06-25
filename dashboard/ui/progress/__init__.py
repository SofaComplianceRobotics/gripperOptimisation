"""Progress widgets for the analysis dashboard.

This package provides helper functions and UI builders used by the
monitoring callbacks. Helpers perform state lookups and compute scoring
values, while builder functions return ready-to-render Dash components for
the dashboard.

Module contents:
    _get_run_max_score, _state_color, _run_progress_pct, _get_live_score,
    _get_trial_actual_state, _find_earliest_not_done, _RUN_MAX_SCORE_CACHE,
    _build_progress_card, _build_trial_detail, _build_progress_stats,
    _build_progress_grid
"""

from .helpers import (
    _get_run_max_score,
    _state_color,
    _run_progress_pct,
    _get_live_score,
    _get_trial_actual_state,
    _find_earliest_not_done,
    _RUN_MAX_SCORE_CACHE,
)
from .builders import (
    _build_progress_card,
)
from .panels import _build_trial_detail, _build_progress_stats, _build_progress_grid

__all__ = [
    "_get_run_max_score",
    "_state_color",
    "_run_progress_pct",
    "_get_live_score",
    "_get_trial_actual_state",
    "_find_earliest_not_done",
    "_RUN_MAX_SCORE_CACHE",
    "_build_progress_card",
    "_build_trial_detail",
    "_build_progress_stats",
    "_build_progress_grid",
]
