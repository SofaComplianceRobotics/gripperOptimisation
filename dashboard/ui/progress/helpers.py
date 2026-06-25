"""Progress state helpers — state logic and cache management."""

from dashboard.data.cache import TRIALS_DIR, _load_trial_state

# ── Caches ─────────────────────────────────────────────────────
_RUN_MAX_SCORE_CACHE: dict[str, float] = {}


def _get_run_max_score(test_name: str) -> float:
    """Return the maximum score a single run of a test can reach.

    The catalog's ``max_score`` is the test-total ceiling. For ``sum``
    aggregated tests (e.g. random_cube_pick, which sums hold-time over its
    per-size runs) that total spans every run, so a single run's bar must be
    scaled by the per-run ceiling ``max_score / run_count`` instead — which is
    ``recorded_duration + overload - early_stop`` for one sim. Other
    aggregations score each run against the full ceiling, so the total is used
    as-is.

    Args:
        test_name: Name of the test to query.

    Returns:
        The per-run maximum score (defaults to 1.0 on error).
    """
    if not test_name:
        return 1.0
    if test_name in _RUN_MAX_SCORE_CACHE:
        return _RUN_MAX_SCORE_CACHE[test_name]
    try:
        from labtests.registry import get_test_catalog

        spec = get_test_catalog().get(test_name)
        if spec is None:
            result = 1.0
        elif spec.score_aggregation == "sum" and spec.run_count > 1:
            result = spec.max_score / spec.run_count
        else:
            result = spec.max_score
    except Exception:
        result = 1.0
    _RUN_MAX_SCORE_CACHE[test_name] = result
    return result


# Human-readable labels for the per-run lifecycle states. Keys are the raw
# state strings written into trial_state.json by the optimization pipeline and
# the SOFA scenes; values are what the progress tab shows. Anything not listed
# falls back to the raw state with dashes turned into spaces.
_RUN_STATE_LABELS = {
    "not-started": "queued",
    "queued": "queued",
    "pending": "gated — waiting for ungated run",
    "waiting-slot": "waiting for SOFA slot",
    "generating-geometry": "generating geometry",
    "rendering-preview": "rendering preview",
    "launching": "launching SOFA",
    "running": "running",
    "done": "done",
    "failed": "failed",
    "error": "error",
    "pruned": "pruned",
    "skipped": "skipped",
    "cancelled": "cancelled",
}

# States that mean "actively doing work" (blue), as opposed to waiting in a
# queue (amber) or terminal (green/red/grey).
_ACTIVE_STATES = {
    "running",
    "launching",
    "generating-geometry",
    "rendering-preview",
}
_WAITING_STATES = {"waiting-slot"}


def _run_state_label(state: str) -> str:
    """Return a human-readable label for a raw run/trial state string.

    Args:
        state: Raw state string from trial_state.json.

    Returns:
        Friendly label suitable for display in the progress tab.
    """
    key = str(state or "").lower()
    return _RUN_STATE_LABELS.get(key, key.replace("-", " ") or "unknown")


def _state_color(state: str) -> str:
    """Return a color hex code representing a run/trial state.

    Args:
        state: State string (e.g. 'running', 'done', 'failed').

    Returns:
        Hex color string for UI display.
    """
    state = state.lower()
    if state in {"done"}:
        return "#2f9e44"
    if state in _ACTIVE_STATES:
        return "#0270ff"
    if state in _WAITING_STATES:
        return "#f08c00"
    if state in {"failed", "error", "pruned", "skipped", "cancelled"}:
        return "#e03131"
    return "#868e96"


def _run_progress_pct(run: dict) -> float:
    """Compute a progress percentage for a run from current/total frames.

    Args:
        run: Run dict containing `current_frame` and `total_frames`.

    Returns:
        Percentage 0.0-100.0 estimating progress.
    """
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


def _get_live_score(run: dict) -> tuple[float | None, bool]:
    """Return a live score estimate for a run and whether it's final.

    Args:
        run: Run dict possibly containing `score` or `hold_time`.

    Returns:
        Tuple (value, is_final) where value is numeric or None.
    """
    score = run.get("score")
    if isinstance(score, (int, float)):
        return float(score), True
    hold_time = run.get("hold_time")
    if isinstance(hold_time, (int, float)):
        return float(hold_time), False
    return None, False


def _get_trial_actual_state(trial_record: dict) -> str:
    """Determine the canonical state for a trial, considering stored runs.

    Args:
        trial_record: Trial summary record from filesystem.

    Returns:
        Canonical state string (waiting/running/done/failed/etc.).
    """
    raw_state = _load_trial_state(trial_record)
    if raw_state is None and not trial_record.get("is_complete"):
        return "waiting"
    trial_state = raw_state or {}
    runs = trial_state.get("runs") if isinstance(trial_state.get("runs"), list) else []

    state = str(
        trial_state.get("state")
        or ("done" if trial_record.get("is_complete") else "running")
    ).lower()

    terminal = {"done", "failed", "error", "pruned", "skipped", "cancelled"}
    if (
        state not in terminal
        and runs
        and all(
            str(r.get("state", "")).lower() in terminal
            for r in runs
            if isinstance(r, dict)
        )
    ):
        state = "done"

    return state


def _find_earliest_not_done(records: list[dict]) -> str | None:
    """Return the DOM id for the earliest trial that is not in a terminal state.

    Args:
        records: List of trial records to search.

    Returns:
        The trial-card id string or None if none found.
    """
    terminal = {"done", "failed", "error", "pruned", "skipped", "cancelled"}
    for record in records:
        state = _get_trial_actual_state(record)
        if state not in terminal:
            return f"trial-card-{record.get('gen_index', 0):04d}-{record.get('trial_index', 0):04d}"
    return None
