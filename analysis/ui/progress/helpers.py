"""Progress state helpers — state logic and cache management."""

from data.cache import _load_trial_state, TRIALS_DIR

# ── Caches ─────────────────────────────────────────────────────
_MAX_SCORE_CACHE: dict[str, float] = {}


def _get_test_max_score(test_name: str) -> float:
    """Return the maximum score configured for a named test.

    Args:
        test_name: Name of the test to query.

    Returns:
        The configured maximum score (defaults to 1.0 on error).
    """
    if not test_name:
        return 1.0
    if test_name in _MAX_SCORE_CACHE:
        return _MAX_SCORE_CACHE[test_name]
    try:
        from labtests.registry import get_test_catalog

        catalog = get_test_catalog()
        spec = catalog.get(test_name)
        result = spec.max_score if spec else 1.0
    except Exception:
        result = 1.0
    _MAX_SCORE_CACHE[test_name] = result
    return result


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
    if state in {"running", "launching"}:
        return "#0270ff"
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
