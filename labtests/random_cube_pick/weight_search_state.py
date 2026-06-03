"""State-shape and attempt-manipulation helpers for weight search.

This module contains helpers that normalise the persisted ladder state and
provide utilities to append or update attempt records. The functions are
designed to work on plain dict objects that are read from or written to
JSON storage.
"""

import time
from pathlib import Path
from typing import List

from .weight_search_common import _CUBE_SIZE_CYCLE


def _slot_key(run_slot: int) -> str:
    """Return a stable key string for a run slot."""
    return str(int(run_slot))


def _ensure_state_shape(state: dict, weight_levels: List[float]) -> dict:
    """Ensure the top-level shape and default fields exist in ``state``.

    This function mutates and returns ``state``. It is safe to call with an
    empty dict and will populate reasonable defaults for slots and ladder
    bounds.
    """
    slots = state.get("slots")
    if not isinstance(slots, dict):
        slots = {}

    for slot_index, size in enumerate(_CUBE_SIZE_CYCLE, start=1):
        key = _slot_key(slot_index)
        slot_state = slots.get(key)
        if not isinstance(slot_state, dict):
            slot_state = {}
        slot_state.setdefault("cube_scale", list(size))
        slot_state.setdefault("low_index", 0)
        slot_state.setdefault("high_index", len(weight_levels) - 1)
        slot_state.setdefault("last_index", None)
        slot_state.setdefault("last_weight", None)
        slot_state.setdefault("last_outcome", None)
        slot_state.setdefault("last_score", None)
        slot_state.setdefault("attempts", [])
        slot_state.setdefault("updated_at", 0.0)
        slots[key] = slot_state

    state["version"] = 1
    state["slots"] = slots
    state.setdefault("weight_min", weight_levels[0])
    state.setdefault("weight_max", weight_levels[-1])
    state.setdefault("weight_step", 0.02)
    state.setdefault("updated_at", 0.0)
    return state


def _resolve_slot_state(state: dict, run_slot: int, weight_levels: List[float]) -> dict:
    """Return a slot-specific dict, creating defaults when needed."""
    state = _ensure_state_shape(state, weight_levels)
    slots = state["slots"]
    key = _slot_key(run_slot)
    slot_state = slots.get(key)
    if not isinstance(slot_state, dict):
        slot_state = {
            "cube_scale": list(
                _CUBE_SIZE_CYCLE[(run_slot - 1) % len(_CUBE_SIZE_CYCLE)]
            ),
            "low_index": 0,
            "high_index": len(weight_levels) - 1,
            "last_index": None,
            "last_weight": None,
            "last_outcome": None,
            "last_score": None,
            "attempts": [],
            "updated_at": 0.0,
        }
        slots[key] = slot_state
    return slot_state


def _reset_state_for_generation(
    weight_levels: List[float], generation_id: int | None
) -> dict:
    """Create a fresh state dict prepared for a new generation.

    Args:
        weight_levels (List[float]): The full ladder of weight values.
        generation_id (int|None): Optional generation identifier to record.

    Returns:
        dict: Newly constructed state shape with empty attempt lists.
    """
    state: dict = {
        "version": 1,
        "generation": generation_id,
        "slots": {},
        "weight_min": weight_levels[0],
        "weight_max": weight_levels[-1],
        "weight_step": 0.02,
        "updated_at": time.time(),
    }
    for slot_index, size in enumerate(_CUBE_SIZE_CYCLE, start=1):
        slot_state = {
            "cube_scale": list(size),
            "low_index": 0,
            "high_index": len(weight_levels) - 1,
            "last_index": None,
            "last_weight": None,
            "last_outcome": None,
            "last_score": None,
            "attempts": [],
            "updated_at": 0.0,
        }
        state["slots"][str(slot_index)] = slot_state
    return state


def _append_attempt(
    slot_state: dict, *, index: int, weight: float, outcome: str
) -> None:
    """Append a new attempt record into a slot state's "attempts" list."""
    attempts = slot_state.get("attempts")
    if not isinstance(attempts, list):
        attempts = []
    attempts.append(
        {
            "index": int(index),
            "weight": float(weight),
            "outcome": outcome,
            "updated_at": time.time(),
        }
    )
    slot_state["attempts"] = attempts


def _update_latest_pending_attempt(
    slot_state: dict, *, index: int, outcome: str, score: float | None
) -> None:
    """Update the latest pending attempt that matches ``index`` with a result.

    If no pending attempt exists for ``index`` a new record is appended.
    """
    attempts = slot_state.get("attempts")
    if not isinstance(attempts, list):
        attempts = []

    for attempt in reversed(attempts):
        if not isinstance(attempt, dict):
            continue
        if int(attempt.get("index", -1)) != int(index):
            continue
        if str(attempt.get("outcome", "")).lower() == "pending":
            attempt["outcome"] = outcome
            attempt["score"] = score
            attempt["updated_at"] = time.time()
            slot_state["attempts"] = attempts
            return

    attempts.append(
        {
            "index": int(index),
            "weight": None,
            "outcome": outcome,
            "score": score,
            "updated_at": time.time(),
        }
    )
    slot_state["attempts"] = attempts


def _segment_state_for_index(
    *, index: int, low_index: int, high_index: int, attempts: list[dict]
) -> str:
    """Return a string describing the visual state for a ladder index.

    The returned values are textual keys used by the UI to pick labels and
    colors (e.g. "tested_success", "deduced_failure", "pending").
    """
    for attempt in reversed(attempts):
        if not isinstance(attempt, dict):
            continue
        if int(attempt.get("index", -1)) != int(index):
            continue
        outcome = str(attempt.get("outcome", "")).lower()
        if outcome == "success":
            return "tested_success"
        if outcome == "failure":
            return "tested_failure"
        if outcome == "pending":
            return "pending"

    if index < low_index:
        return "deduced_success"
    if index > high_index:
        return "deduced_failure"
    return "unknown"
