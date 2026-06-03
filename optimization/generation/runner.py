"""Generation execution for the optimization loop.

This module coordinates per-generation setup and delegates the heavy lifting to
the launch and finalize helpers.
"""

from __future__ import annotations

import threading

import optuna

from optimization.generation.finalize import finalize_generation
from optimization.generation.launch import launch_generation_trials
from optimization.generation.progress import generation_progress_writer
from optimization.optimize_config import (
    N_PARALLEL,
    RUN_PLAN,
    SELECTED_TEST_NAMES,
    SELECTED_TEST_WEIGHTS,
    TRIALS_DIR,
)
from optimization._trial_state import init_trial_state
from optimization.state import TrialState


def run_generation(
    gen_index: int,
    trials: list,
    study: optuna.Study,
    env: dict,
    state: TrialState,
) -> None:
    """Run one complete generation of the CMA-ES optimization loop.

    Args:
        gen_index: Generation number.
        trials: Optuna trial objects for this generation.
        study: Optuna study used for reporting outcomes.
        env: Environment variables for the SOFA subprocesses.
        state: Shared optimization state.
    """
    gen_dir = TRIALS_DIR / f"gen_{gen_index:04d}"
    gen_dir.mkdir(parents=True, exist_ok=True)

    trial_state_paths_by_trial = []
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

    try:
        launch_result = launch_generation_trials(
            gen_index=gen_index,
            trials=trials,
            study=study,
            env=env,
            state=state,
            gen_dir=gen_dir,
            trial_state_paths_by_trial=trial_state_paths_by_trial,
        )
        finalize_generation(
            gen_index=gen_index,
            study=study,
            state=state,
            env=env,
            gen_dir=gen_dir,
            trial_state_paths_by_trial=trial_state_paths_by_trial,
            launch_result=launch_result,
        )
    finally:
        progress_stop.set()
        progress_thread.join(timeout=2.0)
