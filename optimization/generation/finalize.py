"""Generation finalization helpers.

This module waits for launched SOFA processes to finish, applies gating and
pruning rules, reports scores, and writes generation summaries.
"""

from __future__ import annotations

import time
from pathlib import Path

import optuna

from optimization.algorithm import _finalize_trial_score
from optimization.generation.plan import (
    prune_trial,
    trial_has_ungated_positive_run,
)
from optimization.generation.launch import _relaunch_run
from optimization.geom_pipeline import render_stl_preview
from optimization.config import (
    RUN_PLAN,
    SELECTED_TEST_NAMES,
    SELECTED_TEST_WEIGHTS,
    SOFA_REALTIME_TIMEOUT,
)
from optimization._trial_state import (
    read_trial_state,
    update_trial_run,
)
from optimization.scoring import write_gen_summary
from optimization.utils import cleanup_collision_stls
from optimization.state import TrialState


def finalize_generation(
    *,
    gen_index: int,
    study: optuna.Study,
    state: TrialState,
    env: dict,
    gen_dir: Path,
    launch_result: dict,
) -> None:
    """Finalize a generation after its trials have been launched.

    Args:
        gen_index: Generation number.
        study: Optuna study used for reporting outcomes.
        state: Shared optimization state.
        env: Environment variables for the SOFA subprocesses.
        gen_dir: Directory for the current generation.
        launch_result: Output from launch_generation_trials.
    """
    processes = launch_result["processes"]
    collision_stls_by_trial = launch_result["collision_stls_by_trial"]
    prelaunch_scores = launch_result["prelaunch_scores"]

    try:
        finalized: set[int] = set()
        gen_scores = prelaunch_scores.copy()
        bar_width = 28
        start_time = time.time()
        last_print = 0.0

        while len(finalized) < len(processes):
            for (
                trial_index,
                trial,
                runs,
                pending_gated_runs,
                trial_state_path,
                collision_stl,
                launch_times_by_slot,
            ) in processes:
                if trial_index in finalized:
                    continue

                trial_has_active_run = False
                now = time.time()
                for proc, _path, run_slot in list(runs):
                    if proc.poll() is None:
                        launch_ts = launch_times_by_slot.get(run_slot)
                        if (
                            launch_ts is not None
                            and now - launch_ts > SOFA_REALTIME_TIMEOUT
                        ):
                            prune_trial(
                                gen_index,
                                trial_index,
                                trial_state_path,
                                runs,
                                f"SOFA wall-clock timeout after {SOFA_REALTIME_TIMEOUT:.0f}s",
                            )
                            trial_has_active_run = True
                            break

                        trial_has_active_run = True
                        continue

                    # Crashed/non-terminal runs are left as-is: they score -inf
                    # and floor to 0 within their own test at finalization.

                if trial_has_active_run:
                    continue

                trial_state = read_trial_state(trial_state_path)
                if str(trial_state.get("state", "")).lower() == "pruned":
                    finalized.add(trial_index)

                    final_score = _finalize_trial_score(
                        trial_index=trial_index,
                        trial=trial,
                        runs=runs,
                        trial_state_path=trial_state_path,
                        study=study,
                        test_aggregations=state.test_aggregations,
                        test_max_scores=state.test_max_scores,
                        test_weights=SELECTED_TEST_WEIGHTS,
                        test_names=list(SELECTED_TEST_NAMES),
                        gen_index=gen_index,
                    )
                    gen_scores.append(final_score)
                    state.record_score(final_score)
                    continue

                if pending_gated_runs:
                    if trial_has_ungated_positive_run(trial_state_path):
                        print(
                            f"[gate] Gen {gen_index:04d} Trial {trial_index:02d} ungated success detected; launching gated tests."
                        )

                        for run_slot, test_name, test_run_index, test_run_total in list(
                            pending_gated_runs
                        ):
                            _relaunch_run(
                                gen_index=gen_index,
                                trial_index=trial_index,
                                run_slot=run_slot,
                                test_name=test_name,
                                test_run_index=test_run_index,
                                test_run_total=test_run_total,
                                trial_state_path=trial_state_path,
                                collision_stl=collision_stl,
                                launch_times_by_slot=launch_times_by_slot,
                                runs=runs,
                                env=env,
                            )
                        pending_gated_runs.clear()
                        continue

                    for run_slot, _test_name, _test_run_index, _test_run_total in list(
                        pending_gated_runs
                    ):
                        update_trial_run(
                            trial_state_path,
                            run_slot,
                            {
                                "state": "skipped",
                                "current_frame": 0,
                                "total_frames": None,
                                "sim_time": 0.0,
                                "score": None,
                                "reason": "gated_test_skipped_until_ungated_success",
                            },
                        )
                    pending_gated_runs.clear()

                finalized.add(trial_index)

                final_score = _finalize_trial_score(
                    trial_index=trial_index,
                    trial=trial,
                    runs=runs,
                    trial_state_path=trial_state_path,
                    study=study,
                    test_aggregations=state.test_aggregations,
                    test_max_scores=state.test_max_scores,
                    test_weights=SELECTED_TEST_WEIGHTS,
                    test_names=list(SELECTED_TEST_NAMES),
                    gen_index=gen_index,
                )
                gen_scores.append(final_score)
                state.record_score(final_score)

            now = time.time()
            if now - last_print >= 0.5:
                total_runs = sum(len(runs) for _, _, runs, _, _, _, _ in processes)
                total_done = sum(
                    sum(1 for p, _, _ in runs if p.poll() is not None)
                    for _, _, runs, _, _, _, _ in processes
                )
                pct = (100.0 * total_done / total_runs) if total_runs else 100.0
                filled = (
                    int(bar_width * total_done / total_runs)
                    if total_runs
                    else bar_width
                )
                bar = "#" * filled + "-" * (bar_width - filled)
                elapsed = now - start_time
                print(
                    f"\r[progress] Gen {gen_index:04d} SOFA [{bar}] "
                    f"{total_done}/{total_runs} ({pct:5.1f}%)  elapsed {elapsed:5.1f}s",
                    end="",
                    flush=True,
                )
                last_print = now

            if len(finalized) < len(processes):
                time.sleep(0.2)

        total_elapsed = time.time() - start_time
        total_runs = sum(len(runs) for _, _, runs, _, _, _, _ in processes)
        print(
            f"\r[progress] Gen {gen_index:04d} SOFA [{'#' * bar_width}] "
            f"{total_runs}/{total_runs} (100.0%)  elapsed {total_elapsed:5.1f}s"
        )

        # Render trial previews now — every SOFA process for this generation
        # has exited, so pyvista's offscreen OpenGL no longer overlaps SOFA's
        # GL initialization. Doing this mid-generation deadlocks SOFA startup
        # on Windows (WGL contention), which is why it is deferred to here.
        preview_tasks = launch_result.get("preview_tasks", [])
        failed_preview = launch_result.get("failed_preview")
        if preview_tasks:
            print(
                f"[preview] Gen {gen_index:04d} rendering {len(preview_tasks)} "
                f"trial preview(s)"
            )
            for visual_stl_copy, trial_index in preview_tasks:
                trial_dir = gen_dir / f"trial_{trial_index:02d}"
                render_stl_preview(
                    visual_stl_copy, trial_dir, gen_index, trial_index, failed_preview
                )

        write_gen_summary(gen_dir, gen_index, gen_scores)

    finally:
        cleanup_collision_stls(collision_stls_by_trial)
