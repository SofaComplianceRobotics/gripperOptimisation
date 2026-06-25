"""
scoring.py — Score aggregation, normalization, and progress reporting.

File I/O primitives live in optimization._scoring_io.
Trial state CRUD lives in optimization._trial_state.
"""

import json
import statistics
import time

from optimization.config import (
    GEN_PROGRESS_POLL_INTERVAL,
    HARD_FAIL_SCORE,
    N_GENERATIONS,
    N_PARALLEL,
    N_REPEATS,
    PROGRESS_FILE,
    RUN_PLAN,
    SELECTED_TEST_NAMES,
    SELECTED_TEST_WEIGHTS,
    TRIALS_DIR,
)
from optimization._scoring_io import write_jsonc


def normalize_test_score(score: float, max_score: float) -> float:
    """Normalize a raw test score to [0.0, 1.0] by dividing by its declared maximum.

    Scores above the maximum are clamped to 1.0 rather than penalized.

    Args:
        score: Raw score from the simulation.
        max_score: The declared maximum possible score for this test.

    Returns:
        Normalized score in [0.0, 1.0].
    """
    if max_score <= 0:
        return 0.0
    return min(score / max_score, 1.0)


def aggregate_trial_scores(
    valid_scores: list[float],
    weights: dict[str, float] | None = None,
    names: list[str] | None = None,
    max_scores: dict[str, float] | None = None,
    aggregation: str = "mean",
) -> tuple[float, float, float]:
    """Aggregate multiple scores using the configured method.

    When ``weights``, ``names``, and ``max_scores`` are all provided, computes
    the final score out of 100 using:

        final = Σ  min(score_i / max_score_i, 1.0)  *  weight_pct_i

    where ``weight_pct_i`` is the integer percentage weight (e.g. 20 for 20%),
    so the result is on a 0–100 scale. When aggregating repeated runs of the
    same test, omit weights and max_scores — plain mean/median is used instead.

    Args:
        valid_scores: Valid scores to aggregate.
        weights: Per-test weight fractions (values sum to 1.0). Keys must match
            ``names`` if provided.
        names: Test names corresponding to each score in ``valid_scores``.
            Required when ``weights`` is given.
        max_scores: Per-test maximum possible raw score. Required for
            normalization when ``weights`` is given.

    Returns:
        Tuple of (aggregate_score, final_score, median_score). ``final_score``
        equals ``aggregate_score``. ``median_score`` is the raw un-normalized median.
    """
    if not valid_scores:
        return 0.0, 0.0, 0.0

    avg_score = sum(valid_scores) / len(valid_scores)
    median_score = statistics.median(valid_scores)

    if aggregation == "sum":
        aggregate_score = sum(valid_scores)
        return aggregate_score, aggregate_score, median_score

    if aggregation == "exponential_coverage":
        # Reward grippers that can handle ALL cube sizes, not just one.
        # Each additional cube grasped multiplies the score by 1.5:
        #   1 cube  → sum × 1
        #   2 cubes → sum × 1.5
        #   3 cubes → sum × 2.25
        # Use s > 0 (not just s != -inf) — a failed run can return 0.0 and must
        # not be counted as a successful grasp.
        n_grasped = sum(1 for s in valid_scores if s > 0)
        multiplier = 1.5 ** (n_grasped - 1) if n_grasped > 0 else 0.0
        aggregate_score = sum(valid_scores) * multiplier
        return aggregate_score, aggregate_score, median_score

    # Weighted + normalized aggregation — only when combining per-test scores.
    if (
        weights is not None
        and names is not None
        and max_scores is not None
        and len(names) == len(valid_scores)
        and all(name in weights for name in names)
        and all(name in max_scores for name in names)
    ):
        # Each term: normalize score to [0,1] then multiply by weight percentage (sums to 100).
        aggregate_score = sum(
            normalize_test_score(score, max_scores[name]) * (weights[name] * 100)
            for score, name in zip(valid_scores, names)
        )
    elif aggregation == "median":
        aggregate_score = median_score
    else:
        aggregate_score = avg_score

    return aggregate_score, aggregate_score, median_score


def write_gen_summary(gen_dir, gen_index: int, scores: list[float]) -> None:
    """Compute and write a summary.json for the generation with avg, best, and worst scores.

    All scores are already normalized to [0, 100].

    Args:
        gen_dir: The generation directory where summary.json will be written.
        gen_index: Current generation number.
        scores: All trial final_scores for this generation (out of 100).
    """
    valid_scores = [s for s in scores if s not in (float("-inf"), None)]

    summary = {
        "gen": gen_index,
        "n_trials": len(scores),
        "n_valid": len(valid_scores),
        "avg_score": (
            round(sum(valid_scores) / len(valid_scores), 4) if valid_scores else None
        ),
        "best_score": round(max(valid_scores), 4) if valid_scores else None,
        "worst_score": round(min(valid_scores), 4) if valid_scores else None,
    }
    write_jsonc(gen_dir / "summary.json", summary)
    avg_str = (
        f"{summary['avg_score']:.2f}" if summary["avg_score"] is not None else "n/a"
    )
    best_str = (
        f"{summary['best_score']:.2f}" if summary["best_score"] is not None else "n/a"
    )
    print(
        f"[summary] Gen {gen_index:04d} — "
        f"avg: {avg_str}/100  best: {best_str}/100  "
        f"({len(valid_scores)}/{len(scores)} trials)"
    )


def write_progress(
    gen_index: int, trials_done_in_gen: float, all_scores: list[float]
) -> None:
    """Write current optimization progress to progress.json for the UI monitor to poll.

    Args:
        gen_index: Current generation number (1-based).
        trials_done_in_gen: How many trial-equivalents have completed in the current generation.
        all_scores: Every score collected so far across all generations.
    """
    trials_done_in_gen = max(0.0, min(float(N_PARALLEL), float(trials_done_in_gen)))
    total_done = (gen_index - 1) * N_PARALLEL + trials_done_in_gen
    total = N_GENERATIONS * N_PARALLEL
    valid_scores = [s for s in all_scores if s not in (float("-inf"), None)]

    payload = {
        "gen_current": gen_index,
        "gen_total": N_GENERATIONS,
        "trials_per_gen": N_PARALLEL,
        "runs_per_trial": N_REPEATS,
        "test_names": list(SELECTED_TEST_NAMES),
        "test_weights": {
            name: round(frac * 100) for name, frac in SELECTED_TEST_WEIGHTS.items()
        },
        "run_plan": [
            {
                "test_name": test_name,
                "test_run_index": test_run_index,
                "test_run_total": test_run_total,
                "run_label": f"{test_name} {test_run_index}/{test_run_total}",
            }
            for test_name, test_run_index, test_run_total in RUN_PLAN
        ],
        "tests_per_trial": len(SELECTED_TEST_NAMES),
        "trial_current": total_done,
        "trial_total": total,
        "pct": round(100 * total_done / total, 1),
        "best_score": round(max(valid_scores), 4) if valid_scores else None,
        "avg_score": (
            round(sum(valid_scores) / len(valid_scores), 4) if valid_scores else None
        ),
        "started_at": 0.0,  # Will be overridden by caller in main loop
        "updated_at": time.time(),
    }

    PROGRESS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
