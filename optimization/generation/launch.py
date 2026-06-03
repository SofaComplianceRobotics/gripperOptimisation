"""Generation launch helpers.

This module prepares each trial, exports geometry, starts SOFA processes, and
records launch-time failures.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import optuna

from labtests.registry import get_test_spec
from optimization.config import (
    FAILED_PREVIEW_IMAGE_CANDIDATES,
    GATED_TEST_NAMES,
    HARD_FAIL_SCORE,
    MAX_ACTIVE_SOFA_PROCS,
    N_REPEATS,
    PREVIEWS_DIR,
    RUN_PLAN,
    SELECTED_TEST_NAMES,
    SELECTED_TEST_WEIGHTS,
)
from optimization.geometry import (
    GeometryExportFailureError,
    GeometryExportTimeoutError,
    generate_stl_for_trial,
    params_from_trial,
    render_stl_preview,
    resolve_failed_preview_image,
)
from optimization._trial_state import update_trial_run
from optimization.sofa import launch_sofa, wait_for_geometry_slot
from optimization.state import TrialState, _save_trial_checkpoint


def _relaunch_run(
    *,
    gen_index: int,
    trial_index: int,
    run_slot: int,
    test_name: str,
    test_run_index: int,
    test_run_total: int,
    trial_state_path: Path,
    collision_stl: Path,
    launch_times_by_slot: dict[int, float],
    runs: list[tuple],
    launched_run_plan_entries: list[tuple],
    env: dict,
) -> None:
    """Launch one run again and update the in-memory tracking lists.

    Args:
        gen_index: Generation number.
        trial_index: Trial number inside the generation.
        run_slot: Run slot within the trial.
        test_name: Name of the test to relaunch.
        test_run_index: 1-based index inside the test.
        test_run_total: Total number of runs for the test.
        trial_state_path: Path to the trial_state.json file.
        collision_stl: Collision STL used for the launch.
        launch_times_by_slot: Per-slot launch timestamp map.
        runs: Active run records for this trial.
        launched_run_plan_entries: Entries used to finalize the trial score.
        env: Environment variables for the SOFA subprocesses.
    """
    test_spec = get_test_spec(test_name)
    update_trial_run(
        trial_state_path,
        run_slot,
        {
            "state": "launching",
            "current_frame": 0,
            "total_frames": None,
            "sim_time": 0.0,
            "score": None,
            "reason": "",
        },
    )
    proc = launch_sofa(
        test_spec.scene_file,
        test_name,
        test_run_index,
        test_run_total,
        collision_stl,
        trial_state_path,
        run_slot,
        gen_index,
        trial_index,
        run_slot,
        env,
    )
    print(
        f"[sofa] Gen {gen_index:04d} Trial {trial_index:02d} "
        f"Run {run_slot}/{N_REPEATS} [{test_name} {test_run_index}/{test_run_total}]"
    )
    runs.append((proc, trial_state_path, run_slot))
    launch_times_by_slot[run_slot] = time.time()
    launched_run_plan_entries.append((test_name, test_run_index, test_run_total))


def launch_generation_trials(
    *,
    gen_index: int,
    trials: list,
    study: optuna.Study,
    env: dict,
    state: TrialState,
    gen_dir: Path,
    trial_state_paths_by_trial: list[Path],
) -> dict:
    """Launch all trials for one generation.

    Args:
        gen_index: Generation number.
        trials: Optuna trial objects for this generation.
        study: Optuna study used for reporting outcomes.
        env: Environment variables for the SOFA subprocesses.
        state: Shared optimization state.
        gen_dir: Directory for the current generation.
        trial_state_paths_by_trial: Trial state paths for the generation.

    Returns:
        A dictionary containing launch metadata for the finalize phase.
    """
    processes: list[tuple] = []
    collision_stls_by_trial: dict[int, Path] = {}
    prelaunch_scores: list[float] = []

    failed_preview = None
    try:
        failed_preview = resolve_failed_preview_image(FAILED_PREVIEW_IMAGE_CANDIDATES)
    except FileNotFoundError:
        pass

    for i, trial in enumerate(trials):
        trial_index = i + 1
        trial_dir = gen_dir / f"trial_{trial_index:02d}"
        trial_dir.mkdir(exist_ok=True)

        wait_for_geometry_slot(processes, MAX_ACTIVE_SOFA_PROCS, gen_index, trial_index)

        full_config = params_from_trial(trial)

        try:
            collision_stl, visual_stl_copy = generate_stl_for_trial(
                trial_dir, full_config
            )
            trial_state_path = trial_dir / "trial_state.json"
            render_stl_preview(
                visual_stl_copy, trial_dir, gen_index, trial_index, failed_preview
            )

            runs = []
            launched_run_plan_entries: list[tuple[str, int, int]] = []
            pending_gated_runs: list[tuple[int, str, int, int]] = []
            launch_times_by_slot: dict[int, float] = {}
            for r, (test_name, test_run_index, test_run_total) in enumerate(RUN_PLAN):
                if test_name in GATED_TEST_NAMES:
                    pending_gated_runs.append(
                        (r + 1, test_name, test_run_index, test_run_total)
                    )
                    update_trial_run(
                        trial_state_path,
                        r + 1,
                        {
                            "state": "pending",
                            "current_frame": 0,
                            "total_frames": None,
                            "sim_time": 0.0,
                            "score": None,
                            "reason": "gated_test_waiting_for_ungated_success",
                        },
                    )
                    continue

                test_spec = get_test_spec(test_name)
                update_trial_run(
                    trial_state_path,
                    r + 1,
                    {
                        "state": "launching",
                        "current_frame": 0,
                        "total_frames": None,
                        "sim_time": 0.0,
                        "score": None,
                        "reason": "",
                    },
                )
                proc = launch_sofa(
                    test_spec.scene_file,
                    test_name,
                    test_run_index,
                    test_run_total,
                    collision_stl,
                    trial_state_path,
                    r + 1,
                    gen_index,
                    trial_index,
                    r + 1,
                    env,
                )
                launch_times_by_slot[r + 1] = time.time()
                print(
                    f"[sofa] Gen {gen_index:04d} Trial {trial_index:02d} "
                    f"Run {r + 1}/{N_REPEATS} [{test_name} {test_run_index}/{test_run_total}]"
                )
                runs.append((proc, trial_state_path, r + 1))
                launched_run_plan_entries.append(
                    (test_name, test_run_index, test_run_total)
                )

            collision_stls_by_trial[trial_index] = collision_stl
            processes.append(
                (
                    trial_index,
                    trial,
                    runs,
                    launched_run_plan_entries,
                    pending_gated_runs,
                    trial_state_path,
                    collision_stl,
                    launch_times_by_slot,
                )
            )

        except (GeometryExportTimeoutError, GeometryExportFailureError) as e:
            if failed_preview:
                try:
                    local_path = trial_dir / "preview.png"
                    shutil.copy2(failed_preview, local_path)
                    flat_name = f"gen_{gen_index:04d}_trial_{trial_index:02d}.png"
                    shutil.copy2(local_path, PREVIEWS_DIR / flat_name)
                except Exception as preview_err:
                    print(
                        f"[warn] Failed placeholder preview for Gen {gen_index:04d} "
                        f"Trial {trial_index:02d}: {preview_err}"
                    )

            trial_state_path = trial_dir / "trial_state.json"
            for r in range(len(RUN_PLAN)):
                update_trial_run(
                    trial_state_path,
                    r + 1,
                    {"state": "failed", "score": None, "reason": str(e)},
                )
            print(f"[error] Gen {gen_index:04d} Trial {trial_index:02d}: {e}")
            study.tell(trial, HARD_FAIL_SCORE)
            _save_trial_checkpoint(
                trial_state_path,
                {
                    "state": "failed",
                    "final_score": HARD_FAIL_SCORE,
                    "outcome": f"geometry export failed: {type(e).__name__}",
                },
            )
            prelaunch_scores.append(HARD_FAIL_SCORE)
            state.record_score(HARD_FAIL_SCORE)

        except Exception as e:
            print(f"[error] Gen {gen_index:04d} Trial {trial_index:02d}: {e}")
            study.tell(trial, HARD_FAIL_SCORE)
            trial_state_path = trial_dir / "trial_state.json"
            for r in range(len(RUN_PLAN)):
                update_trial_run(
                    trial_state_path,
                    r + 1,
                    {"state": "failed", "score": None, "reason": str(e)},
                )
            _save_trial_checkpoint(
                trial_state_path,
                {
                    "state": "failed",
                    "final_score": HARD_FAIL_SCORE,
                    "outcome": f"runtime failure: {type(e).__name__}",
                },
            )
            prelaunch_scores.append(HARD_FAIL_SCORE)
            state.record_score(HARD_FAIL_SCORE)

    return {
        "processes": processes,
        "collision_stls_by_trial": collision_stls_by_trial,
        "prelaunch_scores": prelaunch_scores,
        "failed_preview": failed_preview,
    }
