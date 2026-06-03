"""Trial planning helpers for generation execution.

This module handles generation-local decisions that do not belong in the main
runner: gated-test checks, pruning, and seed index calculation.
"""

from __future__ import annotations

from pathlib import Path
from statistics import median_low

from optimization.optimize_config import GATED_TEST_NAMES, RUN_PLAN
from optimization.optimize_scoring import (
    read_trial_state,
    update_trial_run,
    update_trial_summary,
)


def trial_has_ungated_positive_run(trial_state_path: Path) -> bool:
    """Return whether an ungated run in the trial has a positive score.

    Args:
        trial_state_path: Path to the trial_state.json file.

    Returns:
        True when at least one ungated run has score > 0.
    """
    trial_state = read_trial_state(trial_state_path)
    runs = trial_state.get("runs", []) if isinstance(trial_state, dict) else []
    if not isinstance(runs, list):
        return False

    for run in runs:
        if not isinstance(run, dict):
            continue
        test_name = str(run.get("test_name", ""))
        if test_name in GATED_TEST_NAMES:
            continue
        raw = run.get("score")
        if isinstance(raw, (int, float)) and float(raw) > 0.0:
            return True

    return False


def compute_random_cube_pick_seed_indices(
    trial_state_paths_by_trial: list[Path],
) -> dict[int, int]:
    """Compute median seed indices for random_cube_pick slots across trials.

    Args:
        trial_state_paths_by_trial: Trial state files for the generation.

    Returns:
        Mapping of slot number to the median recorded index.
    """
    slots_for_test: list[int] = [
        i + 1
        for i, (test_name, _, _) in enumerate(RUN_PLAN)
        if str(test_name) == "random_cube_pick"
    ]
    slot_values: dict[int, list[int]] = {slot: [] for slot in slots_for_test}

    for trial_state_path in trial_state_paths_by_trial:
        ladder_state_path = trial_state_path.with_name(
            "random_cube_pick_weight_search.json"
        )
        seen_slots: set[int] = set()
        try:
            ladder_state = read_trial_state(ladder_state_path)
        except Exception:
            ladder_state = {}

        slots = ladder_state.get("slots", {}) if isinstance(ladder_state, dict) else {}
        if isinstance(slots, dict):
            for slot_key, slot_state in slots.items():
                try:
                    slot = int(slot_key)
                except Exception:
                    continue
                if slot not in slot_values or not isinstance(slot_state, dict):
                    continue
                raw_index = slot_state.get("last_index")
                if isinstance(raw_index, int):
                    slot_values[slot].append(int(raw_index))
                    seen_slots.add(slot)

        trial_state = read_trial_state(trial_state_path)
        runs = trial_state.get("runs", []) if isinstance(trial_state, dict) else []
        if not isinstance(runs, list):
            continue

        for run in runs:
            if not isinstance(run, dict):
                continue
            if str(run.get("test_name", "")) != "random_cube_pick":
                continue
            run_slot = int(run.get("run", 0) or 0)
            if run_slot not in slot_values or run_slot in seen_slots:
                continue
            raw_index = run.get("weight_selected_index")
            if not isinstance(raw_index, int):
                raw_index = run.get("weight_index")
            if isinstance(raw_index, int):
                slot_values[run_slot].append(int(raw_index))

    seeds: dict[int, int] = {}
    for slot, values in slot_values.items():
        if values:
            seeds[slot] = int(median_low(sorted(values)))
    return seeds


def prune_trial(
    gen_index: int,
    trial_index: int,
    trial_state_path: Path,
    runs: list[tuple],
    reason: str,
) -> None:
    """Mark a trial as pruned and stop its active SOFA runs.

    Args:
        gen_index: Generation number.
        trial_index: Trial index within the generation.
        trial_state_path: Path to the trial_state.json file.
        runs: Active run tuples in the form (process, path, slot).
        reason: Pruning reason to record.
    """
    for proc, _path, _run_slot in runs:
        if proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass

    for run_slot in range(1, len(RUN_PLAN) + 1):
        update_trial_run(
            trial_state_path,
            run_slot,
            {
                "state": "pruned",
                "current_frame": 0,
                "total_frames": None,
                "sim_time": 0.0,
                "score": None,
                "reason": reason,
            },
        )

    update_trial_summary(
        trial_state_path,
        {
            "state": "pruned",
            "outcome": reason,
            "final_score": None,
        },
    )

    print(f"[prune] Gen {gen_index:04d} Trial {trial_index:02d}: {reason}")
