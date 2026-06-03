"""Ladder math, index selection and snapshot rendering helpers.

This module implements the numeric ladder generation for weight levels,
the index-choosing strategy (binary search), and the UI-friendly snapshot
builder used by the dashboard.
"""

import time
from pathlib import Path
from typing import List

from .common import (
    DEFAULT_WEIGHT_MIN,
    DEFAULT_WEIGHT_MAX,
    DEFAULT_WEIGHT_STEP,
)
from .state import _resolve_slot_state, _segment_state_for_index
from .persistence import _read_state, _resolve_state_path


def _build_weight_levels(
    weight_min: float, weight_max: float, step_size: float
) -> List[float]:
    """Construct an ordered list of weight levels from min/max/step.

    The function validates and normalises inputs, returning a list of
    rounded floats suitable for both display and numeric comparison.
    """
    lo = min(float(weight_min), float(weight_max))
    hi = max(float(weight_min), float(weight_max))
    step = abs(float(step_size))
    if step <= 0:
        raise ValueError("weight step must be greater than zero")

    count = int(round((hi - lo) / step))
    if count < 0:
        count = 0

    levels = [round(lo + (i * step), 6) for i in range(count + 1)]
    if not levels:
        levels = [round(lo, 6)]
    levels[-1] = round(hi, 6)
    return levels


def _choose_index(low_index: int, high_index: int, ladder_size: int) -> tuple[int, str]:
    """Choose the next index to probe.

    Returns a tuple ``(index, strategy_name)``. The current strategy is a
    binary-search that returns the midpoint between the low and high bounds.
    When the range is invalid the function reports convergence.
    """
    low_index = max(0, min(int(low_index), ladder_size - 1))
    high_index = max(0, min(int(high_index), ladder_size - 1))

    if high_index < low_index:
        return max(0, min(low_index, ladder_size - 1)), "converged"

    return (low_index + high_index) // 2, "binary_search"


def build_search_snapshot(
    lab_root: Path,
    run_slot: int,
    *,
    weight_min: float = DEFAULT_WEIGHT_MIN,
    weight_max: float = DEFAULT_WEIGHT_MAX,
    step_size: float = DEFAULT_WEIGHT_STEP,
    state_path: Path | None = None,
    generation_id: int | None = None,
) -> dict:
    """Build a compact, UI-friendly snapshot of the current ladder state.

    The returned dictionary contains display-ready fields such as
    ``weight_segments`` (with colours/labels), a short textual summary, the
    currently selected index/value and a small history string.
    """
    weights = _build_weight_levels(weight_min, weight_max, step_size)
    state_path = _resolve_state_path(lab_root, state_path)
    state = _read_state(state_path)
    slot_state = _resolve_slot_state(state, int(run_slot), weights)

    low_index = int(slot_state.get("low_index", 0))
    high_index = int(slot_state.get("high_index", len(weights) - 1))
    attempts = (
        slot_state.get("attempts")
        if isinstance(slot_state.get("attempts"), list)
        else []
    )

    segments = []
    for index, weight in enumerate(weights):
        state_name = _segment_state_for_index(
            index=index, low_index=low_index, high_index=high_index, attempts=attempts
        )
        segments.append(
            {
                "index": index,
                "label": index + 1,
                "weight": weight,
                "state": state_name,
                "state_label": state_name.replace("_", " "),
                "color": "#dee2e6",
                "border_color": "#ced4da",
                "tested": state_name.startswith("tested"),
                "deduced": state_name.startswith("deduced"),
                "pending": state_name == "pending",
                "title": f"{weight:.3f}kg | {state_name.replace('_', ' ')}",
            }
        )

    tested_count = sum(1 for seg in segments if seg["tested"])
    deduced_count = sum(1 for seg in segments if seg["deduced"])
    pending_count = sum(1 for seg in segments if seg["pending"])
    last_index = slot_state.get("last_index")
    current_index = (
        int(last_index) if isinstance(last_index, int) else max(0, low_index)
    )
    current_weight = (
        weights[current_index] if 0 <= current_index < len(weights) else weights[0]
    )
    current_state = str(slot_state.get("last_outcome", "unknown")).lower()

    def _range_text(indices: list[int]) -> str:
        if not indices:
            return ""
        if len(indices) == 1:
            return str(indices[0] + 1)
        start = min(indices) + 1
        end = max(indices) + 1
        return f"{start}-{end}"

    success_indices = [
        seg["index"]
        for seg in segments
        if seg["state"] in {"tested_success", "deduced_success"}
    ]
    failure_indices = [
        seg["index"]
        for seg in segments
        if seg["state"] in {"tested_failure", "deduced_failure"}
    ]
    pending_text = _range_text(
        [idx for idx in range(len(segments)) if segments[idx]["pending"]]
    )

    attempt_history_parts = []
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        index = int(attempt.get("index", -1))
        if index < 0:
            continue
        outcome = str(attempt.get("outcome", "pending")).lower()
        symbol = {"success": "✓", "failure": "✗", "pending": "…"}.get(outcome, "?")
        attempt_history_parts.append(f"{index + 1}{symbol}")

    summary_parts = [
        f"probe {current_index + 1}/{len(weights)} {current_state or 'unknown'}",
        f"tested {tested_count}",
        f"deduced {deduced_count}",
    ]
    if success_indices:
        summary_parts.append(f"success {_range_text(success_indices)}")
    if failure_indices:
        summary_parts.append(f"fail {_range_text(failure_indices)}")
    if pending_text:
        summary_parts.append(f"pending {pending_text}")

    return {
        "weight_min": weights[0],
        "weight_max": weights[-1],
        "weight_step": step_size,
        "weight_levels": weights,
        "weight_level_count": len(weights),
        "weight_selected_index": current_index,
        "weight_selected_value": current_weight,
        "weight_search_low_index": low_index,
        "weight_search_high_index": high_index,
        "weight_search_status": slot_state.get("last_outcome", "pending"),
        "weight_attempts": attempts,
        "weight_attempt_history": ", ".join(attempt_history_parts),
        "weight_segments": segments,
        "weight_segment_summary": " | ".join(summary_parts),
    }
