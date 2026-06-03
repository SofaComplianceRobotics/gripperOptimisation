"""Optimization entry point.

This script initializes the CMA-ES study, prepares shared runtime state, and
delegates each generation to the generation runner.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_SRC_ROOT = _SCRIPT_DIR.parent
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

import optuna

from optimization.algorithm import build_cmaes_study
from optimization.generation.runner import run_generation
from optimization.config import (
    LAB_ROOT,
    N_GENERATIONS,
    N_PARALLEL,
    SELECTED_TEST_NAMES,
    build_env,
)
from optimization.scoring import write_progress
from optimization.utils import reset_trials_dir
from optimization.state import TrialState


def run_optimization() -> None:
    """Run the full optimization workflow."""
    reset_trials_dir()

    db_path = LAB_ROOT / "runtime" / "gripper_opt.db"
    study = build_cmaes_study(db_path)

    env = build_env()
    state = TrialState()
    state.load_test_specs(list(SELECTED_TEST_NAMES))

    for gen in range(1, N_GENERATIONS + 1):
        state.advance_gen()
        write_progress(gen, 0, state.all_scores)

        print(f"\n{'=' * 50}")
        print(f"Generation {gen}/{N_GENERATIONS}")
        print(f"{'=' * 50}")

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
