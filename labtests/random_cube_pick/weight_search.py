"""Deterministic weight search for the random_cube_pick benchmark.

The helper keeps one binary-search ladder per cube size. The scene asks for the
next size/weight before building the cube, then records the final outcome when
the run ends.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

STATE_FILE_NAME = "random_cube_pick_weight_search.json"
DEFAULT_WEIGHT_MIN = 0.02
DEFAULT_WEIGHT_MAX = 0.2
DEFAULT_WEIGHT_STEP = 0.02

_CUBE_SIZE_CYCLE = (
    [8.0, 8.0, 8.0],
    [10.0, 10.0, 10.0],
    [20.0, 20.0, 20.0],
)


@dataclass(frozen=True)
class CubeSearchSpec:
    """Chosen size/weight for one run slot."""

    run_slot: int
    cube_scale: list[float]
    cube_mass: float
    weight_index: int
    weight_levels: list[float]
    lower_index: int
    upper_index: int
    status: str


def weight_points_for_index(weight_index: int) -> int:
    """Return the 1-based ladder score for a selected weight index."""
    return max(0, int(weight_index) + 1)


def boundary_score_for_index(weight_index: int) -> int:
    """Return the score earned by confirming a successful ladder boundary."""
    return weight_points_for_index(weight_index) if weight_index >= 0 else 0


def _segment_state_label(state: str) -> str:
    state = state.lower()
    return {
        "tested_success": "tested success",
        "tested_failure": "tested failure",
        "deduced_success": "deduced success",
        "deduced_failure": "deduced failure",
        "pending": "pending",
        "unknown": "unknown",
    }.get(state, state)


def _segment_state_color(state: str) -> str:
    state = state.lower()
    return {
        "tested_success": "#2f9e44",
        "deduced_success": "#d3f9d8",
        "tested_failure": "#e03131",
        "deduced_failure": "#ffc9c9",
        "pending": "#339af0",
        "unknown": "#dee2e6",
    }.get(state, "#dee2e6")


def _segment_state_border(state: str) -> str:
    state = state.lower()
    return {
        "tested_success": "#2b8a3e",
        "deduced_success": "#8ce99a",
        "tested_failure": "#c92a2a",
        "deduced_failure": "#ffa8a8",
        "pending": "#1c7ed6",
        "unknown": "#ced4da",
    }.get(state, "#ced4da")


def _state_path(lab_root: Path) -> Path:
    return Path(lab_root) / "runtime" / STATE_FILE_NAME


def _resolve_state_path(lab_root: Path, state_path: Path | None = None) -> Path:
    if state_path is not None:
        return Path(state_path)
    return _state_path(lab_root)


def _lock_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".lock")


def _acquire_lock(lock_path: Path, timeout_s: float = 5.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return True
        except FileExistsError:
            time.sleep(0.01)
        except Exception:
            return False
    return False


def _release_lock(lock_path: Path) -> None:
    try:
        if lock_path.exists():
            lock_path.unlink()
    except Exception:
        pass


def _read_state(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _write_state(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def _build_weight_levels(
    weight_min: float, weight_max: float, step_size: float
) -> list[float]:
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


def _slot_key(run_slot: int) -> str:
    return str(int(run_slot))


def _ensure_state_shape(state: dict, weight_levels: list[float]) -> dict:
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
    state.setdefault("weight_step", DEFAULT_WEIGHT_STEP)
    state.setdefault("updated_at", 0.0)
    return state


def _resolve_slot_state(state: dict, run_slot: int, weight_levels: list[float]) -> dict:
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
    weight_levels: list[float],
    generation_id: int | None,
) -> dict:
    state: dict = {
        "version": 1,
        "generation": generation_id,
        "slots": {},
        "weight_min": weight_levels[0],
        "weight_max": weight_levels[-1],
        "weight_step": DEFAULT_WEIGHT_STEP,
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
        state["slots"][_slot_key(slot_index)] = slot_state
    return state


def _append_attempt(
    slot_state: dict, *, index: int, weight: float, outcome: str
) -> None:
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
    *,
    index: int,
    low_index: int,
    high_index: int,
    attempts: list[dict],
) -> str:
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
    """Build a compact, UI-friendly snapshot of the current ladder state."""
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
    tested_indices = {
        int(a.get("index", -1))
        for a in attempts
        if isinstance(a, dict)
        and str(a.get("outcome", "")).lower() in {"success", "failure"}
    }
    pending_indices = {
        int(a.get("index", -1))
        for a in attempts
        if isinstance(a, dict) and str(a.get("outcome", "")).lower() == "pending"
    }

    segments = []
    for index, weight in enumerate(weights):
        state_name = _segment_state_for_index(
            index=index,
            low_index=low_index,
            high_index=high_index,
            attempts=attempts,
        )
        segments.append(
            {
                "index": index,
                "label": index + 1,
                "weight": weight,
                "state": state_name,
                "state_label": _segment_state_label(state_name),
                "color": _segment_state_color(state_name),
                "border_color": _segment_state_border(state_name),
                "tested": state_name.startswith("tested"),
                "deduced": state_name.startswith("deduced"),
                "pending": state_name == "pending",
                "title": f"{weight:.3f}kg | {_segment_state_label(state_name)}",
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
    pending_text = _range_text([idx for idx in pending_indices if idx >= 0])
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


def _choose_index(low_index: int, high_index: int, ladder_size: int) -> tuple[int, str]:
    low_index = max(0, min(int(low_index), ladder_size - 1))
    high_index = max(0, min(int(high_index), ladder_size - 1))

    if high_index < low_index:
        return max(0, min(low_index, ladder_size - 1)), "converged"

    return (low_index + high_index) // 2, "binary_search"


def select_cube_spec(
    lab_root: Path,
    run_slot: int,
    *,
    weight_min: float = DEFAULT_WEIGHT_MIN,
    weight_max: float = DEFAULT_WEIGHT_MAX,
    step_size: float = DEFAULT_WEIGHT_STEP,
    state_path: Path | None = None,
    seed_index: int | None = None,
    generation_id: int | None = None,
) -> CubeSearchSpec:
    """Return the next cube size/weight pair for one run slot."""
    weights = _build_weight_levels(weight_min, weight_max, step_size)
    state_path = _resolve_state_path(lab_root, state_path)
    lock_path = _lock_path(state_path)

    if not _acquire_lock(lock_path):
        cube_scale = list(_CUBE_SIZE_CYCLE[(int(run_slot) - 1) % len(_CUBE_SIZE_CYCLE)])
        index, status = _choose_index(0, len(weights) - 1, len(weights))
        return CubeSearchSpec(
            run_slot=int(run_slot),
            cube_scale=cube_scale,
            cube_mass=weights[index],
            weight_index=index,
            weight_levels=weights,
            lower_index=0,
            upper_index=len(weights) - 1,
            status=f"lock_fallback:{status}",
        )

    try:
        state = _read_state(state_path)
        if generation_id is not None and int(state.get("generation", -1)) != int(
            generation_id
        ):
            state = _reset_state_for_generation(weights, generation_id)
        slot_state = _resolve_slot_state(state, int(run_slot), weights)
        state["generation"] = generation_id

        low_index = int(slot_state.get("low_index", -1))
        high_index = int(slot_state.get("high_index", len(weights) - 1))
        attempts = (
            slot_state.get("attempts")
            if isinstance(slot_state.get("attempts"), list)
            else []
        )
        if (
            not attempts
            and isinstance(seed_index, int)
            and 0 <= seed_index < len(weights)
        ):
            index = int(seed_index)
            status = "seeded"
        else:
            index, status = _choose_index(low_index, high_index, len(weights))

        slot_state.update(
            {
                "cube_scale": list(
                    _CUBE_SIZE_CYCLE[(int(run_slot) - 1) % len(_CUBE_SIZE_CYCLE)]
                ),
                "last_index": index,
                "last_weight": weights[index],
                "last_outcome": "pending",
                "last_score": None,
                "attempts": slot_state.get("attempts", []),
                "updated_at": time.time(),
            }
        )
        _append_attempt(
            slot_state, index=index, weight=weights[index], outcome="pending"
        )
        state["updated_at"] = time.time()
        _write_state(state_path, state)

        return CubeSearchSpec(
            run_slot=int(run_slot),
            cube_scale=list(slot_state["cube_scale"]),
            cube_mass=weights[index],
            weight_index=index,
            weight_levels=weights,
            lower_index=low_index,
            upper_index=high_index,
            status=status,
        )
    finally:
        _release_lock(lock_path)


def record_cube_result(
    lab_root: Path,
    spec: CubeSearchSpec,
    *,
    score: float | None,
    succeeded: bool | None = None,
    state_path: Path | None = None,
    generation_id: int | None = None,
) -> dict:
    """Persist the result of one run back into the ladder state.

    Returns a compact summary describing whether the ladder has converged and
    which index is the current boundary candidate.
    """
    if succeeded is None:
        succeeded = bool(score is not None and score > 0.0)

    state_path = _resolve_state_path(lab_root, state_path)
    lock_path = _lock_path(state_path)
    if not _acquire_lock(lock_path):
        return

    try:
        state = _read_state(state_path)
        if generation_id is not None and int(state.get("generation", -1)) != int(
            generation_id
        ):
            state = _reset_state_for_generation(spec.weight_levels, generation_id)
        slot_state = _resolve_slot_state(state, spec.run_slot, spec.weight_levels)
        state["generation"] = generation_id

        low_index = int(slot_state.get("low_index", -1))
        high_index = int(slot_state.get("high_index", len(spec.weight_levels) - 1))

        if succeeded:
            low_index = min(
                len(spec.weight_levels), max(low_index, spec.weight_index + 1)
            )
        else:
            high_index = max(-1, min(high_index, spec.weight_index - 1))

        _update_latest_pending_attempt(
            slot_state,
            index=spec.weight_index,
            outcome="success" if succeeded else "failure",
            score=score,
        )

        slot_state.update(
            {
                "low_index": low_index,
                "high_index": high_index,
                "last_index": spec.weight_index,
                "last_weight": spec.cube_mass,
                "last_outcome": "success" if succeeded else "failure",
                "last_score": score,
                "updated_at": time.time(),
            }
        )
        state["updated_at"] = time.time()
        state["slots"][_slot_key(spec.run_slot)] = slot_state
        _write_state(state_path, state)
        return {
            "low_index": low_index,
            "high_index": high_index,
            "converged": bool(high_index < low_index),
            "boundary_index": high_index,
            "state_path": str(state_path),
        }
    finally:
        _release_lock(lock_path)
    return {
        "low_index": int(spec.lower_index),
        "high_index": int(spec.upper_index),
        "converged": False,
        "boundary_index": int(spec.lower_index),
        "state_path": str(state_path),
    }
