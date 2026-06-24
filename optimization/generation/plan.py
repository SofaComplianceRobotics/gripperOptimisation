"""Trial planning helpers for generation execution.

This module handles generation-local decisions that do not belong in the main
runner: gated-test checks, pruning, and seed index calculation.
"""

from __future__ import annotations

from pathlib import Path

from optimization.config import GATED_TEST_NAMES, RUN_PLAN
from optimization._trial_state import (
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
