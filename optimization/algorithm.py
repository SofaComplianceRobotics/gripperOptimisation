"""Core optimization algorithm: CMA-ES study setup and trial score computation."""

import sys
from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parent.parent
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

import optuna

from optimization.optimize_config import (
    CMAES_SIGMA0,
    CMAES_STARTUP_TRIALS,
    HARD_FAIL_SCORE,
    N_PARALLEL,
    PARAM_SPECS,
)
from optimization.optimize_scoring import (
    aggregate_trial_scores,
    read_trial_run,
    update_trial_summary,
)


def build_cmaes_study(db_path: Path) -> optuna.Study:
    """Create a fresh Optuna CMA-ES study backed by a SQLite database.

    Deletes any existing database at db_path before creating the study.

    Args:
        db_path: Path to the SQLite database file for Optuna storage.

    Returns:
        Configured Optuna study ready to receive trials.
    """
    if db_path.exists():
        db_path.unlink()
        print(f"[reset] Deleted {db_path.name}")

    sampler = optuna.samplers.CmaEsSampler(
        popsize=N_PARALLEL,
        sigma0=CMAES_SIGMA0,
        n_startup_trials=CMAES_STARTUP_TRIALS,
        consider_pruned_trials=True,
        x0={
            spec["name"]: spec["default"]
            for spec in PARAM_SPECS
            if not (spec["min"] == 0 and spec["max"] == 0)
        },
    )
    storage = optuna.storages.RDBStorage(f"sqlite:///{db_path}")
    return optuna.create_study(
        study_name="gripper_shape_v1",
        sampler=sampler,
        direction="maximize",
        storage=storage,
    )


def _compute_next_parameters(study: optuna.Study) -> "optuna.trial.Trial":
    """Generate parameters for the next trial using the CMA-ES sampler.

    Args:
        study: Active Optuna study.

    Returns:
        A new Optuna trial with sampled parameter values.
    """
    return _apply_mutations(study)


def _apply_mutations(study: optuna.Study) -> "optuna.trial.Trial":
    """Sample the next candidate via CMA-ES Gaussian mutation.

    Gaussian perturbations around the current distribution mean are applied
    internally by Optuna's CmaEsSampler on each study.ask() call.

    Args:
        study: Active Optuna study.

    Returns:
        A new Optuna trial with mutated parameter values.
    """
    return study.ask()


def _select_best_parents(
    study: optuna.Study, n: int
) -> "list[optuna.trial.FrozenTrial]":
    """Return the top-n completed trials ranked by score.

    Used to inspect which parameter sets CMA-ES is converging toward.

    Args:
        study: Active Optuna study.
        n: Number of top performers to return.

    Returns:
        List of up to n FrozenTrial objects in descending score order.
    """
    completed = [t for t in study.trials if t.value is not None]
    return sorted(completed, key=lambda t: t.value or float("-inf"), reverse=True)[:n]


def _finalize_trial_score(
    trial_index: int,
    trial: "optuna.trial.Trial",
    runs: list[tuple],
    trial_state_path: Path,
    run_plan_entries: list[tuple],
    study: optuna.Study,
    test_aggregations: dict[str, str],
    test_max_scores: dict[str, float],
    test_weights: dict[str, float],
    test_names: list[str],
    gen_index: int,
) -> float:
    """Compute the final score for a completed trial and report it to Optuna.

    Reads per-run scores from filesystem, aggregates them per test, then combines
    across tests using configured weights. Calls study.tell() and writes the
    trial summary to disk.

    Args:
        trial_index: 1-based trial index within the generation.
        trial: Optuna trial object to report results to.
        runs: List of (Popen, trial_state_path, run_slot) for this trial's SOFA runs.
        trial_state_path: Path to this trial's trial_state.json.
        run_plan_entries: Ordered list of (test_name, run_index, run_total) tuples.
        study: Active Optuna study.
        test_aggregations: Per-test score aggregation method (e.g. "mean", "sum").
        test_max_scores: Per-test maximum possible raw score.
        test_weights: Per-test weight fractions (values sum to 1.0).
        test_names: Ordered list of selected test names.
        gen_index: Current generation number for summary fields.

    Returns:
        Final trial score out of 100, or HARD_FAIL_SCORE on any failure.
    """
    run_scores = []
    for _p, _path, run_slot in runs:
        run_data = read_trial_run(trial_state_path, run_slot) or {}
        raw = run_data.get("score")
        run_scores.append(float(raw) if isinstance(raw, (int, float)) else float("-inf"))

    if any(s == float("-inf") for s in run_scores):
        final_score = HARD_FAIL_SCORE
        study.tell(trial, final_score)
        print(f"[score] trial_{trial_index:02d} → {final_score:.2f} (generation failure)")
        update_trial_summary(
            trial_state_path,
            {"state": "failed", "final_score": final_score, "outcome": "generation failure"},
        )
        return final_score

    valid_scores = [s for s in run_scores if s != float("-inf")]
    if not valid_scores:
        final_score = HARD_FAIL_SCORE
        study.tell(trial, final_score)
        update_trial_summary(
            trial_state_path,
            {"state": "failed", "final_score": final_score, "outcome": "no valid run scores"},
        )
        return final_score

    # Aggregate scores per test so a multi-run test still contributes one score.
    test_names_in_order: list[str] = []
    per_test_scores: list[float] = []
    per_test_details: dict[str, dict] = {}

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
        test_aggregate, _, _, test_median = aggregate_trial_scores(
            valid_for_test,
            aggregation=test_aggregations.get(test_name, "mean"),
        )
        max_score = test_max_scores.get(test_name, 1.0)
        per_test_scores.append(test_aggregate)
        per_test_details[test_name] = {
            "run_count": len(valid_for_test),
            "run_scores": [round(s, 4) for s in scores_for_test],
            "aggregate_score": round(test_aggregate, 4),
            "median_score": round(test_median, 4),
            "run_total": test_run_total,
            "max_score": max_score,
            "weight_pct": round(test_weights.get(test_name, 0.0) * 100, 1),
            "normalized_score": round(
                min(test_aggregate / max_score, 1.0) if max_score > 0 else 0.0, 4
            ),
        }

    if not per_test_scores:
        final_score = HARD_FAIL_SCORE
        study.tell(trial, final_score)
        update_trial_summary(
            trial_state_path,
            {"state": "failed", "final_score": final_score, "outcome": "no valid per-test scores"},
        )
        return final_score

    # Combine per-test scores: Σ min(score_i / max_i, 1.0) * weight_pct_i → out of 100.
    aggregate_score, _, final_score, median_score = aggregate_trial_scores(
        per_test_scores,
        weights=test_weights,
        names=test_names_in_order,
        max_scores=test_max_scores,
    )
    study.tell(trial, final_score)

    trial_stats = {
        "trial": trial_index,
        "gen": gen_index,
        "state": "done",
        "n_runs": len(valid_scores),
        "test_names": list(test_names),
        "test_weights": {
            name: round(test_weights.get(name, 0.0) * 100, 1) for name in test_names
        },
        "test_max_scores": {name: test_max_scores.get(name, 1.0) for name in test_names},
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
        f"\n[score] trial_{trial_index:02d} → {final_score:.2f}/100 "
        f"(weighted_normalized_agg: {aggregate_score:.2f})"
    )
    return final_score
