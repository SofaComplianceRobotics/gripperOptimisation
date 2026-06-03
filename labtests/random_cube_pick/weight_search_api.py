"""Public API for selecting candidates and recording results.

This module exposes the two higher-level functions used by the scene and the
dashboard: ``select_cube_spec`` returns the next candidate to run, while
``record_cube_result`` persists the outcome and updates ladder bounds.
"""

import time
from pathlib import Path

from .weight_search_common import CubeSearchSpec
from .weight_search_common import (
    DEFAULT_WEIGHT_MIN,
    DEFAULT_WEIGHT_MAX,
    DEFAULT_WEIGHT_STEP,
)
from .weight_search_persistence import (
    _acquire_lock,
    _lock_path,
    _read_state,
    _release_lock,
    _resolve_state_path,
    _write_state,
)
from .weight_search_state import (
    _append_attempt,
    _resolve_slot_state,
    _reset_state_for_generation,
    _update_latest_pending_attempt,
)
from .weight_search_ladder import _build_weight_levels, _choose_index


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
    """Return the next cube size/weight pair for one run slot.

    The function uses a simple filesystem lock to coordinate concurrent
    callers and persists the chosen candidate as a pending attempt so the
    result can be recorded later by ``record_cube_result``.
    """
    weights = _build_weight_levels(weight_min, weight_max, step_size)
    state_path = _resolve_state_path(lab_root, state_path)
    lock_path = _lock_path(state_path)

    if not _acquire_lock(lock_path):
        # If we cannot acquire the lock, return a fallback candidate drawn from
        # the default search range so the caller can continue without blocking.
        cube_scale = list([8.0, 8.0, 8.0][(int(run_slot) - 1) % 1])
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
                "cube_scale": list([8.0, 8.0, 8.0][(int(run_slot) - 1) % 1]),
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

    Args:
        lab_root (Path): Root of the lab workspace where the state file lives.
        spec (CubeSearchSpec): The candidate spec returned by ``select_cube_spec``.
        score (float|None): Numeric score for the run (None if not available).
        succeeded (bool|None): Optional explicit success flag. When None the
            function computes success as ``score > 0``.

    Returns:
        dict: Summary containing low/high indexes, convergence flag and the
            path to the persisted state file.
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
        state["slots"][str(spec.run_slot)] = slot_state
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
