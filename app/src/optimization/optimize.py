"""
optimize.py — Optuna + CMA-ES gripper shape optimizer (main orchestrator).

This is the entry point for the optimization loop. It imports specialized modules for
configuration, geometry, SOFA management, and scoring to keep the main logic clean and focused.

Strategy per generation:
  1. For each trial (serially): generate geometry, copy visual STL, render preview, launch SOFA immediately
  2. Each SOFA instance runs in parallel — launched right after its geometry is ready
  3. Wait for all SOFA instances to finish, read scores
  4. Write a summary.json with avg/best/worst score for the generation
  5. Write a progress.json with overall progress for the UI progress bar
  6. Report scores → Optuna updates CMA-ES distribution
"""

import json
import os
import statistics
import sys
import threading
import time
from pathlib import Path

# Setup sys.path BEFORE importing from optimization modules
SCRIPT_DIR = Path(__file__).resolve().parent
SRC_ROOT = SCRIPT_DIR.parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import optuna

# Import all specialized modules
from optimize_config import (
    N_GENERATIONS,
    N_PARALLEL,
    N_REPEATS,
    CMAES_SIGMA0,
    CMAES_STARTUP_TRIALS,
    HARD_FAIL_SCORE,
    LAB_ROOT,
    MAX_ACTIVE_SOFA_PROCS,
    SELECTED_TEST_NAMES,
    SELECTED_TEST_WEIGHTS,
    RUN_PLAN,
    TRIALS_DIR,
    GEN_PROGRESS_POLL_INTERVAL,
    FAILED_PREVIEW_IMAGE_CANDIDATES,
    build_env,
)
from labtests.registry import get_test_spec
from optimize_geometry import (
    GeometryExportTimeoutError,
    GeometryExportFailureError,
    generate_stl_for_trial,
    render_stl_preview,
    params_from_trial,
    resolve_failed_preview_image,
)
from optimize_sofa import (
    launch_sofa,
    active_sofa_process_count,
    wait_for_geometry_slot,
)
from optimize_scoring import (
    write_gen_summary,
    write_progress,
    cleanup_generation_status_files,
    aggregate_trial_scores,
    init_trial_state,
    update_trial_run,
    read_trial_run,
    read_trial_state,
    update_trial_summary,
)
from optimize_utils import (
    reset_trials_dir,
    cleanup_collision_stls,
)

# Global state
TRAINING_STARTED_AT = 0.0


def wait_for_sofa_runs(
    gen_index: int,
    processes: list[tuple],
    all_scores: list[float],
    n_repeats: int,
) -> None:
    """
    Wait for all SOFA subprocesses in a generation and print a live progress bar.

    Inputs:
        gen_index (int): Generation number for status display.
        processes (list[tuple]): List of (trial_index, trial, [(Popen, trial_state_path, run_slot), ...]).
        all_scores (list[float]): Completed-trial scores from previous generations.
        n_repeats (int): Number of repeated runs per trial.

    Returns:
        None
    """
    total_runs = sum(len(runs) for _, _, runs in processes)
    if total_runs == 0:
        return

    completed: set[tuple[int, int]] = set()
    start_time = time.time()
    last_update = 0.0
    bar_width = 28

    while len(completed) < total_runs:
        for trial_i, (_, _, runs) in enumerate(processes):
            for run_i, (p, _, _) in enumerate(runs):
                key = (trial_i, run_i)
                if key in completed:
                    continue
                if p.poll() is not None:
                    completed.add(key)

        now = time.time()
        if now - last_update >= 0.5:
            done = len(completed)
            pct = (100.0 * done) / total_runs
            filled = int(bar_width * done / total_runs)
            bar = "#" * filled + "-" * (bar_width - filled)
            elapsed = now - start_time
            print(
                f"\r[progress] Gen {gen_index:04d} SOFA [{bar}] "
                f"{done}/{total_runs} ({pct:5.1f}%)  elapsed {elapsed:5.1f}s",
                end="",
                flush=True,
            )
            last_update = now

        if len(completed) < total_runs:
            time.sleep(0.2)

    total_elapsed = time.time() - start_time
    print(
        f"\r[progress] Gen {gen_index:04d} SOFA [{'#' * bar_width}] "
        f"{total_runs}/{total_runs} (100.0%)  elapsed {total_elapsed:5.1f}s"
    )


def generation_progress_fraction(trial_state_paths_by_trial: list[Path]) -> float:
    """
    Estimate generation progress from per-run frame progress only.

    Inputs:
        trial_state_paths_by_trial (list[Path]): One trial_state.json path per trial.

    Returns:
        float: Generation progress as a fraction in [0, 1].
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
    """
    Continuously write frame-only generation progress until stopped.

    Inputs:
        gen_index (int): Current generation number.
        trial_state_paths_by_trial (list[Path]): Expected trial_state files for the generation.
        all_scores (list[float]): All collected scores so far.
        stop_event (threading.Event): Signals when to stop writing progress.

    Returns:
        None
    """
    while not stop_event.is_set():
        write_progress(
            gen_index,
            generation_progress_fraction(trial_state_paths_by_trial) * N_PARALLEL,
            all_scores,
        )
        stop_event.wait(GEN_PROGRESS_POLL_INTERVAL)


def run_generation(
    gen_index: int,
    trials: list,
    study: optuna.Study,
    env: dict,
    all_scores: list[float],
) -> None:
    """
    Run one complete generation of the CMA-ES optimization loop.

    Coordinates trial geometry generation, SOFA launching, score collection,
    and trial reporting.

    Inputs:
        gen_index (int): Generation number.
        trials (list): List of Optuna trial objects for this generation.
        study (optuna.Study): The Optuna study for reporting results.
        env (dict): Environment variables for SOFA subprocesses.
        all_scores (list[float]): Accumulator for all scores across generations.

    Returns:
        None
    """
    gen_dir = TRIALS_DIR / f"gen_{gen_index:04d}"
    gen_dir.mkdir(parents=True, exist_ok=True)

    processes = (
        []
    )  # list of (trial_index, trial, [(Popen, trial_state_path, run_slot), ...])
    collision_stls_by_trial: dict[int, Path] = {}
    trial_state_paths_by_trial: list[Path] = []

    # Pre-create one trial_state.json per trial with deterministic run slots.
    for trial_index in range(1, N_PARALLEL + 1):
        trial_dir = gen_dir / f"trial_{trial_index:02d}"
        trial_dir.mkdir(exist_ok=True)
        trial_state_path = trial_dir / "trial_state.json"
        init_trial_state(
            trial_state_path,
            gen_index=gen_index,
            trial_index=trial_index,
            run_plan=list(RUN_PLAN),
        )
        trial_state_paths_by_trial.append(trial_state_path)

    progress_stop = threading.Event()
    progress_thread = threading.Thread(
        target=generation_progress_writer,
        args=(gen_index, trial_state_paths_by_trial, all_scores, progress_stop),
        daemon=True,
    )
    progress_thread.start()

    prelaunch_scores: list[float] = []
    failed_preview = None
    try:
        failed_preview = resolve_failed_preview_image(FAILED_PREVIEW_IMAGE_CANDIDATES)
    except FileNotFoundError:
        pass

    # --- Geometry generation and SOFA launch loop ---
    for i, trial in enumerate(trials):
        trial_index = i + 1
        trial_dir = gen_dir / f"trial_{trial_index:02d}"
        trial_dir.mkdir(exist_ok=True)

        wait_for_geometry_slot(processes, MAX_ACTIVE_SOFA_PROCS, gen_index, trial_index)

        shape_params = params_from_trial(trial)
        from optimize_config import RING_FIXED, MESH_FIXED

        full_config = {**RING_FIXED, **shape_params, **MESH_FIXED}

        try:
            collision_stl, visual_stl_copy = generate_stl_for_trial(
                trial_dir, full_config
            )
            trial_state_path = trial_dir / "trial_state.json"
            render_stl_preview(
                visual_stl_copy, trial_dir, gen_index, trial_index, failed_preview
            )

            runs = []
            for r, (test_name, test_run_index, test_run_total) in enumerate(RUN_PLAN):
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
                p = launch_sofa(
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
                print(
                    f"[sofa] Gen {gen_index:04d} Trial {trial_index:02d} Run {r+1}/{N_REPEATS} [{test_name} {test_run_index}/{test_run_total}]"
                )
                runs.append((p, trial_state_path, r + 1))

            collision_stls_by_trial[trial_index] = collision_stl
            processes.append((trial_index, trial, runs))

        except (GeometryExportTimeoutError, GeometryExportFailureError) as e:
            if failed_preview:
                try:
                    # Publish the failed preview directly
                    trial_dir = gen_dir / f"trial_{trial_index:02d}"
                    local_path = trial_dir / "preview.png"
                    import shutil

                    shutil.copy2(failed_preview, local_path)
                    from optimize_config import PREVIEWS_DIR

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
                    {
                        "state": "failed",
                        "score": None,
                        "reason": str(e),
                    },
                )

            print(f"[error] Gen {gen_index:04d} Trial {trial_index:02d}: {e}")
            study.tell(trial, HARD_FAIL_SCORE)
            update_trial_summary(
                trial_state_path,
                {
                    "state": "failed",
                    "final_score": HARD_FAIL_SCORE,
                    "outcome": f"geometry export failed: {type(e).__name__}",
                },
            )
            prelaunch_scores.append(HARD_FAIL_SCORE)
            all_scores.append(HARD_FAIL_SCORE)
        except Exception as e:
            print(f"[error] Gen {gen_index:04d} Trial {trial_index:02d}: {e}")
            study.tell(trial, HARD_FAIL_SCORE)
            trial_state_path = trial_dir / "trial_state.json"
            for r in range(len(RUN_PLAN)):
                update_trial_run(
                    trial_state_path,
                    r + 1,
                    {
                        "state": "failed",
                        "score": None,
                        "reason": str(e),
                    },
                )
            update_trial_summary(
                trial_state_path,
                {
                    "state": "failed",
                    "final_score": HARD_FAIL_SCORE,
                    "outcome": f"runtime failure: {type(e).__name__}",
                },
            )
            prelaunch_scores.append(HARD_FAIL_SCORE)
            all_scores.append(HARD_FAIL_SCORE)

    # --- Wait for all SOFA instances and collect scores ---
    try:
        wait_for_sofa_runs(gen_index, processes, all_scores, N_REPEATS)

        gen_scores = prelaunch_scores.copy()

        def _is_pruned_status(status_data: dict | None) -> bool:
            if not isinstance(status_data, dict):
                return False
            state = str(status_data.get("state", "")).lower()
            reason = str(status_data.get("reason", "")).lower()
            return (
                state == "pruned"
                or "pruned" in reason
                or "test horizon complete" in reason
                or "glitched through floor after pickup" in reason
            )

        # Collect scores from all trials
        for trial_index, trial, runs in processes:
            trial_dir = gen_dir / f"trial_{trial_index:02d}"
            trial_state_path = trial_dir / "trial_state.json"
            run_scores = []
            run_plan_entries = list(RUN_PLAN)

            for run_number, (p, _trial_state_path, run_slot) in enumerate(
                runs, start=1
            ):
                run_data = read_trial_run(trial_state_path, run_slot) or {}
                raw_score = run_data.get("score")
                score = (
                    float(raw_score)
                    if isinstance(raw_score, (int, float))
                    else float("-inf")
                )
                run_scores.append(score)
                test_name, _, _ = run_plan_entries[run_number - 1]

            # Check for failures and pruning
            if any(score == float("-inf") for score in run_scores):
                final_score = HARD_FAIL_SCORE
                study.tell(trial, final_score)
                print(
                    f"[score] trial_{trial_index:02d} → {final_score:.2f} "
                    f"(generation failure)"
                )
                gen_scores.append(final_score)
                all_scores.append(final_score)
                update_trial_summary(
                    trial_state_path,
                    {
                        "state": "failed",
                        "final_score": final_score,
                        "outcome": "generation failure",
                    },
                )
                continue

            valid_scores = [s for s in run_scores if s != float("-inf")]

            if not valid_scores:
                final_score = HARD_FAIL_SCORE
                study.tell(trial, final_score)
                gen_scores.append(final_score)
                all_scores.append(final_score)
                update_trial_summary(
                    trial_state_path,
                    {
                        "state": "failed",
                        "final_score": final_score,
                        "outcome": "no valid run scores",
                    },
                )
                continue

            # Aggregate scores per test first so a 3-run test still contributes one
            # score to the overall trial.
            test_names_in_order = []
            per_test_scores: list[float] = []
            per_test_details: dict[str, dict[str, float | list[float]]] = {}
            for test_name, _, test_run_total in run_plan_entries:
                if test_name in per_test_details:
                    continue
                scores_for_test = [
                    s
                    for (t_name, _, _), s in zip(run_plan_entries, run_scores)
                    if t_name == test_name
                ]
                valid_for_test = [s for s in scores_for_test if s != float("-inf")]
                if not valid_for_test:
                    continue
                test_names_in_order.append(test_name)
                # Aggregate repeated runs for a single test — no weighting here,
                # weights only apply when combining across different tests.
                test_aggregate, _, _, test_median = aggregate_trial_scores(
                    valid_for_test
                )
                per_test_scores.append(test_aggregate)
                per_test_details[test_name] = {
                    "run_count": len(valid_for_test),
                    "run_scores": [round(s, 4) for s in scores_for_test],
                    "aggregate_score": round(test_aggregate, 4),
                    "median_score": round(test_median, 4),
                    "run_total": test_run_total,
                    "weight_pct": round(
                        SELECTED_TEST_WEIGHTS.get(test_name, 0.0) * 100, 1
                    ),
                }

            if not per_test_scores:
                final_score = HARD_FAIL_SCORE
                study.tell(trial, final_score)
                gen_scores.append(final_score)
                all_scores.append(final_score)
                update_trial_summary(
                    trial_state_path,
                    {
                        "state": "failed",
                        "final_score": final_score,
                        "outcome": "no valid per-test scores",
                    },
                )
                continue

            # Combine per-test scores into one trial score using the user-defined
            # weights.
            aggregate_score, _, final_score, median_score = aggregate_trial_scores(
                per_test_scores,
                weights=SELECTED_TEST_WEIGHTS,
                names=test_names_in_order,
            )
            study.tell(trial, final_score)

            # Write trial summary directly into trial_state.json
            trial_stats = {
                "trial": trial_index,
                "gen": gen_index,
                "state": "done",
                "n_runs": len(valid_scores),
                "test_names": list(SELECTED_TEST_NAMES),
                "test_weights": {
                    name: round(SELECTED_TEST_WEIGHTS.get(name, 0.0) * 100, 1)
                    for name in SELECTED_TEST_NAMES
                },
                "run_test_names": [name for name, _, _ in run_plan_entries],
                "test_scores": per_test_details,
                "avg_score": round(sum(valid_scores) / len(valid_scores), 4),
                "median_score": round(median_score, 4),
                "aggregate_score": round(aggregate_score, 4),
                "best_run": round(max(valid_scores), 4),
                "worst_run": round(min(valid_scores), 4),
                "final_score": round(final_score, 4),
                "run_scores": [round(s, 4) for s in run_scores],
            }
            update_trial_summary(trial_state_path, trial_stats)

            print(
                f"[score] trial_{trial_index:02d} → {final_score:.2f} "
                f"(weighted_agg: {aggregate_score:.2f}"
            )

            gen_scores.append(final_score)
            all_scores.append(final_score)

        write_gen_summary(gen_dir, gen_index, gen_scores)
        cleanup_generation_status_files(gen_dir)

    finally:
        cleanup_collision_stls(collision_stls_by_trial)
        progress_stop.set()
        progress_thread.join(timeout=2.0)


def main() -> None:
    """
    Entry point: initialize a fresh Optuna CMA-ES study and run all generations.

    Inputs:
        None

    Returns:
        None
    """
    global TRAINING_STARTED_AT

    reset_trials_dir()
    TRAINING_STARTED_AT = time.time()

    db_path = LAB_ROOT / "runtime" / "gripper_opt.db"
    if db_path.exists():
        db_path.unlink()
        print(f"[reset] Deleted {db_path.name}")

    sampler_kwargs = {
        "popsize": N_PARALLEL,
        "sigma0": CMAES_SIGMA0,
        "n_startup_trials": CMAES_STARTUP_TRIALS,
        "consider_pruned_trials": True,
        "x0": {
            "pincer_profile_width": 5.0,
            "pincer_profile_height": 10.0,
            "pincer_path_scale": 0.4,
            "p0_hout_dist": 0.0,
            "p0_hout_angle_deg": 0.0,
            "p1_dist": 80.0,
            "p1_angle_deg": -40.0,
            "p1_hin_dist": 0.0,
            "p1_hin_angle_deg": 0.0,
            "leg_attachement_tilt_angle": -15.0,
        },
    }
    sampler = optuna.samplers.CmaEsSampler(**sampler_kwargs)

    storage = optuna.storages.RDBStorage(f"sqlite:///{db_path}")
    study = optuna.create_study(
        study_name="gripper_shape_v1",
        sampler=sampler,
        direction="maximize",
        storage=storage,
    )

    env = build_env()
    all_scores: list[float] = []

    for gen in range(1, N_GENERATIONS + 1):
        write_progress(gen, 0, all_scores)

        print(f"\n{'='*50}")
        print(f"Generation {gen}/{N_GENERATIONS}")
        print(f"{'='*50}")

        trials = [study.ask() for _ in range(N_PARALLEL)]
        run_generation(gen, trials, study, env, all_scores)

        try:
            best = study.best_trial
            print(f"[best so far] Trial {best.number} → {best.value:.2f}")
        except ValueError:
            print("[best so far] No valid trials yet.")

    print("\nOptimization complete.")
    try:
        best_trial = study.best_trial
        print(f"Best trial:  {best_trial.number}")
        print(f"Best value:  {best_trial.value:.4f}")
        print(f"Best params: {best_trial.params}")
    except ValueError:
        print("No valid trials found — all simulations failed.")


if __name__ == "__main__":
    main()
