"""
orchestrator.py — Main optimization loop and trial generation.

Entry point for the CMA-ES gripper shape optimization. Coordinates geometry generation,
SOFA simulation launching, progress tracking, and score collection across generations.

Strategy per generation:
  1. For each trial (serially): generate geometry, copy visual STL, render preview, launch SOFA
  2. Each SOFA instance runs in parallel — launched right after its geometry is ready
  3. Wait for all SOFA instances to finish, read scores
  4. Write a summary.json with avg/best/worst score for the generation
  5. Write a progress.json with overall progress for the UI progress bar
  6. Report scores → Optuna updates CMA-ES distribution
"""

import shutil
import sys
import threading
import time
from statistics import median_low
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_SRC_ROOT = _SCRIPT_DIR.parent
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

import optuna

from optimization.optimize_config import (
    FAILED_PREVIEW_IMAGE_CANDIDATES,
    GATED_TEST_NAMES,
    GEN_PROGRESS_POLL_INTERVAL,
    HARD_FAIL_SCORE,
    LAB_ROOT,
    MAX_ACTIVE_SOFA_PROCS,
    N_GENERATIONS,
    N_PARALLEL,
    N_REPEATS,
    PREVIEWS_DIR,
    RUN_PLAN,
    SELECTED_TEST_NAMES,
    SELECTED_TEST_WEIGHTS,
    TRIALS_DIR,
    build_env,
)
from labtests.registry import get_test_spec
from optimization.optimize_geometry import (
    GeometryExportFailureError,
    GeometryExportTimeoutError,
    generate_stl_for_trial,
    params_from_trial,
    render_stl_preview,
    resolve_failed_preview_image,
)
from optimization.optimize_scoring import (
    cleanup_generation_status_files,
    init_trial_state,
    read_trial_run,
    read_trial_state,
    update_trial_run,
    write_gen_summary,
    write_progress,
)
from optimization.optimize_sofa import (
    launch_sofa,
    wait_for_geometry_slot,
)
from optimization.optimize_utils import (
    cleanup_collision_stls,
    reset_trials_dir,
)
from optimization.algorithm import _finalize_trial_score, build_cmaes_study
from optimization.state import TrialState, _save_trial_checkpoint
from labtests.random_cube_pick.carryover import save_seed_indices


def generation_progress_fraction(trial_state_paths_by_trial: list[Path]) -> float:
    """Estimate generation progress from per-run frame progress only.

    Args:
        trial_state_paths_by_trial: One trial_state.json path per trial.

    Returns:
        Generation progress as a fraction in [0, 1].
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
    """Continuously write frame-only generation progress until stopped.

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


def run_generation(
    gen_index: int,
    trials: list,
    study: optuna.Study,
    env: dict,
    state: TrialState,
) -> None:
    """Run one complete generation of the CMA-ES optimization loop.

    Coordinates trial geometry generation, SOFA launching, score collection,
    and trial reporting for all trials in the generation.

    Args:
        gen_index: Generation number.
        trials: List of Optuna trial objects for this generation.
        study: The Optuna study for reporting results.
        env: Environment variables for SOFA subprocesses.
        state: Shared trial state tracking scores and best results.
    """
    gen_dir = TRIALS_DIR / f"gen_{gen_index:04d}"
    gen_dir.mkdir(parents=True, exist_ok=True)

    # (trial_index, trial, launched_runs, launched_run_plan_entries,
    #  pending_gated_runs, trial_state_path, collision_stl)
    processes: list[tuple] = []
    collision_stls_by_trial: dict[int, Path] = {}
    trial_state_paths_by_trial: list[Path] = []

    for trial_index in range(1, N_PARALLEL + 1):
        trial_dir = gen_dir / f"trial_{trial_index:02d}"
        trial_dir.mkdir(exist_ok=True)
        trial_state_path = trial_dir / "trial_state.json"
        init_trial_state(
            trial_state_path,
            gen_index=gen_index,
            trial_index=trial_index,
            run_plan=list(RUN_PLAN),
            test_weights={
                name: round(SELECTED_TEST_WEIGHTS.get(name, 0.0) * 100, 1)
                for name in SELECTED_TEST_NAMES
            },
            test_max_scores=dict(state.test_max_scores),
        )
        trial_state_paths_by_trial.append(trial_state_path)

    progress_stop = threading.Event()
    progress_thread = threading.Thread(
        target=generation_progress_writer,
        args=(gen_index, trial_state_paths_by_trial, state.all_scores, progress_stop),
        daemon=True,
    )
    progress_thread.start()

    prelaunch_scores: list[float] = []
    failed_preview = None
    try:
        failed_preview = resolve_failed_preview_image(FAILED_PREVIEW_IMAGE_CANDIDATES)
    except FileNotFoundError:
        pass

    def _trial_has_ungated_positive_run(trial_state_path: Path) -> bool:
        """Return True when any ungated run in this trial has score > 0."""
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

    def _compute_random_cube_pick_seed_indices() -> dict[int, int]:
        # determine which run slots in the RUN_PLAN correspond to random_cube_pick
        slots_for_test: list[int] = [
            (i + 1)
            for i, (test_name, _, _) in enumerate(RUN_PLAN)
            if str(test_name) == "random_cube_pick"
        ]
        # initialize accumulator lists for each relevant slot
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

            slots = (
                ladder_state.get("slots", {}) if isinstance(ladder_state, dict) else {}
            )
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

    pass

    # --- Geometry generation and SOFA launch loop ---
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
                    f"[sofa] Gen {gen_index:04d} Trial {trial_index:02d} "
                    f"Run {r+1}/{N_REPEATS} [{test_name} {test_run_index}/{test_run_total}]"
                )
                runs.append((p, trial_state_path, r + 1))
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

    # --- Score each trial as soon as all its SOFA runs finish ---
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
            ) in processes:
                if trial_index in finalized:
                    continue

                trial_has_active_run = False
                for run_idx, (proc, _path, run_slot) in enumerate(list(runs)):
                    if proc.poll() is None:
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
                                "reason": "probe complete, relaunching ladder probe",
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
                        runs[run_idx] = (proc, trial_state_path, run_slot)
                        trial_has_active_run = True
                        print(
                            f"[sofa] Gen {gen_index:04d} Trial {trial_index:02d} "
                            f"Run {run_slot}/{N_REPEATS} [{test_name} {test_run_index}/{test_run_total}] relaunch"
                        )

                if trial_has_active_run:
                    continue

                if pending_gated_runs:
                    should_launch_gated_now = _trial_has_ungated_positive_run(
                        trial_state_path
                    )

                    if should_launch_gated_now:
                        print(
                            f"[gate] Gen {gen_index:04d} Trial {trial_index:02d} ungated success detected; launching gated tests."
                        )

                        for run_slot, test_name, test_run_index, test_run_total in list(
                            pending_gated_runs
                        ):
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
                            p = launch_sofa(
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
                            runs.append((p, trial_state_path, run_slot))
                            launched_run_plan_entries.append(
                                (test_name, test_run_index, test_run_total)
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

        # compute and persist seed indices for next generation
        seeds = _compute_random_cube_pick_seed_indices()
        save_seed_indices(LAB_ROOT, seeds)
        write_gen_summary(gen_dir, gen_index, gen_scores)
        cleanup_generation_status_files(gen_dir)

    finally:
        cleanup_collision_stls(collision_stls_by_trial)
        progress_stop.set()
        progress_thread.join(timeout=2.0)


def run_optimization() -> None:
    """Initialize a fresh Optuna CMA-ES study and run all generations."""
    reset_trials_dir()

    db_path = LAB_ROOT / "runtime" / "gripper_opt.db"
    study = build_cmaes_study(db_path)

    env = build_env()
    state = TrialState()
    state.load_test_specs(list(SELECTED_TEST_NAMES))

    for gen in range(1, N_GENERATIONS + 1):
        state.advance_gen()
        write_progress(gen, 0, state.all_scores)

        print(f"\n{'='*50}")
        print(f"Generation {gen}/{N_GENERATIONS}")
        print(f"{'='*50}")

        trials = [study.ask() for _ in range(N_PARALLEL)]
        run_generation(gen, trials, study, env, state)

        try:
            best = study.best_trial
            print(f"[best so far] Trial {best.number} → {best.value:.2f}/100")
        except ValueError:
            print("[best so far] No valid trials yet.")

    print("\nOptimization complete.")
    try:
        best_trial = study.best_trial
        print(f"Best trial:  {best_trial.number}")
        print(f"Best value:  {best_trial.value:.4f}/100")
        print(f"Best params: {best_trial.params}")
    except ValueError:
        print("No valid trials found — all simulations failed.")


if __name__ == "__main__":
    run_optimization()
