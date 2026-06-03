"""Generation finalization helpers.

This module waits for launched SOFA processes to finish, applies gating and
pruning rules, reports scores, and writes generation summaries.
"""

from __future__ import annotations

import time
from pathlib import Path

import optuna

from labtests.random_cube_pick.carryover import save_seed_indices
from labtests.registry import get_test_spec
from optimization.algorithm import _finalize_trial_score
from optimization.generation.plan import (
    compute_random_cube_pick_seed_indices,
    prune_trial,
    trial_has_ungated_positive_run,
)
from optimization.generation.launch import _relaunch_run
from optimization.config import (
    LAB_ROOT,
    N_REPEATS,
    RUN_PLAN,
    SELECTED_TEST_NAMES,
    SELECTED_TEST_WEIGHTS,
    SOFA_REALTIME_TIMEOUT,
)
from optimization._trial_state import (
    read_trial_run,
    read_trial_state,
    update_trial_run,
)
from optimization.scoring import (
    cleanup_generation_status_files,
    write_gen_summary,
)
from optimization.utils import cleanup_collision_stls
from optimization.state import TrialState


def finalize_generation(
    *,
    gen_index: int,
    study: optuna.Study,
    state: TrialState,
    env: dict,
    gen_dir: Path,
    trial_state_paths_by_trial: list[Path],
    launch_result: dict,
) -> None:
    """Finalize a generation after its trials have been launched.

    Args:
        gen_index: Generation number.
        study: Optuna study used for reporting outcomes.
        state: Shared optimization state.
        env: Environment variables for the SOFA subprocesses.
        gen_dir: Directory for the current generation.
        trial_state_paths_by_trial: Trial state files for the generation.
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

        terminal_run_states = {
            "done",
            "failed",
            "error",
            "pruned",
            "skipped",
            "cancelled",
        }

        while len(finalized) < len(processes):
            for (
                trial_index,
                trial,
                runs,
                launched_run_plan_entries,
                pending_gated_runs,
                trial_state_path,
                collision_stl,
                launch_times_by_slot,
            ) in processes:
                if trial_index in finalized:
                    continue

                trial_has_active_run = False
                now = time.time()
                for run_idx, (proc, _path, run_slot) in enumerate(list(runs)):
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

                    run_data = read_trial_run(trial_state_path, run_slot) or {}
                    run_state = str(run_data.get("state", "")).lower()
                    test_name = str(run_data.get("test_name", ""))

                    if (
                        test_name == "random_cube_pick"
                        and run_state not in terminal_run_states
                    ):
                        test_run_index = int(run_data.get("test_run_index", run_slot))
                        test_run_total = int(run_data.get("test_run_total", 3))
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
                            launched_run_plan_entries=launched_run_plan_entries,
                            env=env,
                        )
                        trial_has_active_run = True

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
                        run_plan_entries=launched_run_plan_entries,
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
                                launched_run_plan_entries=launched_run_plan_entries,
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
                    run_plan_entries=launched_run_plan_entries,
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
                total_runs = sum(len(runs) for _, _, runs, _, _, _, _, _ in processes)
                total_done = sum(
                    sum(1 for p, _, _ in runs if p.poll() is not None)
                    for _, _, runs, _, _, _, _, _ in processes
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
        total_runs = sum(len(runs) for _, _, runs, _, _, _, _, _ in processes)
        print(
            f"\r[progress] Gen {gen_index:04d} SOFA [{'#' * bar_width}] "
            f"{total_runs}/{total_runs} (100.0%)  elapsed {total_elapsed:5.1f}s"
        )

        seeds = compute_random_cube_pick_seed_indices(trial_state_paths_by_trial)
        save_seed_indices(LAB_ROOT, seeds)
        write_gen_summary(gen_dir, gen_index, gen_scores)
        cleanup_generation_status_files(gen_dir)

    finally:
        cleanup_collision_stls(collision_stls_by_trial)
