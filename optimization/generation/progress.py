"""Progress helpers for generation execution.

This module computes the live progress fraction for a generation and writes the
UI progress record while a generation is running.
"""

from __future__ import annotations

import threading
from pathlib import Path

from optimization.optimize_config import GEN_PROGRESS_POLL_INTERVAL, N_PARALLEL
from optimization.optimize_scoring import read_trial_state, write_progress


def generation_progress_fraction(trial_state_paths_by_trial: list[Path]) -> float:
    """Estimate generation progress from per-run frame progress only.

    Args:
        trial_state_paths_by_trial: One trial_state.json path per trial.

    Returns:
        Generation progress as a fraction in the range [0, 1].
    """
    total = 0.0

    for trial_state_path in trial_state_paths_by_trial:
        trial_total = 0.0
        runs = []
        try:
            runs = (read_trial_state(trial_state_path) or {}).get("runs", [])
            if not isinstance(runs, list):
                runs = []
        except Exception:
            runs = []

        for run_data in runs:
            try:
                data = run_data if isinstance(run_data, dict) else {}
                state = str(data.get("state", "")).lower()
                reason = str(data.get("reason", "")).lower()

                if state in {
                    "done",
                    "skipped",
                    "failed",
                    "error",
                    "cancelled",
                    "pruned",
                }:
                    trial_total += 1.0
                    continue

                if data.get("probe_finished") and data.get("score") is None:
                    continue

                cur = float(data.get("current_frame", 0))
                total_frames = data.get("total_frames")
                if isinstance(total_frames, int) and total_frames > 0:
                    trial_total += max(0.0, min(1.0, cur / float(total_frames)))
                elif reason:
                    trial_total += 1.0
            except Exception:
                pass

        if runs:
            total += trial_total / len(runs)

    if not trial_state_paths_by_trial:
        return 0.0

    return max(0.0, min(1.0, total / len(trial_state_paths_by_trial)))


def generation_progress_writer(
    gen_index: int,
    trial_state_paths_by_trial: list[Path],
    all_scores: list[float],
    stop_event: threading.Event,
) -> None:
    """Continuously write generation progress until stopped.

    Args:
        gen_index: Current generation number.
        trial_state_paths_by_trial: Expected trial_state files for the generation.
        all_scores: All collected scores so far.
        stop_event: Signals when to stop writing progress.
    """
    while not stop_event.is_set():
        write_progress(
            gen_index,
            generation_progress_fraction(trial_state_paths_by_trial) * N_PARALLEL,
            all_scores,
        )
        stop_event.wait(GEN_PROGRESS_POLL_INTERVAL)
