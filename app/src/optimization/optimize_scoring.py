"""
optimize_scoring.py — Score reading, aggregation, progress tracking, and result reporting.

Handles collection of simulation results, consistency penalties, and
aggregation into generation summaries and progress updates for the UI.
"""

import json
import statistics
import time
from pathlib import Path

from optimize_config import (
    CONSISTENCY_PENALTY_COEF,
    HARD_FAIL_SCORE,
    PROGRESS_FILE,
    N_PARALLEL,
    N_GENERATIONS,
    N_REPEATS,
    GEN_PROGRESS_POLL_INTERVAL,
    SCORE_AGGREGATION,
    SELECTED_TEST_NAMES,
    RUN_PLAN,
    TRIALS_DIR,
)


def write_run_status(path: Path, data: dict) -> None:
    """
    Write one run status JSON file for the live monitor window.
    Uses atomic file operations to prevent partially written/empty files.

    Inputs:
        path (Path): Status file path.
        data (dict): Status payload.

    Returns:
        None
    """
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def write_jsonc(path: Path, data: dict) -> None:
    """
    Write a dict as plain JSON to a .jsonc file.

    Inputs:
        path (Path): Destination file path.
        data (dict): Data to serialize.

    Returns:
        None
    """
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def read_score(score_path: Path) -> float:
    """
    Read the time_held score written by SOFA's PlaybackController.

    Inputs:
        score_path (Path): Path to the JSON file written by SOFA.

    Returns:
        float: The score value, or -inf if the file is missing or malformed.
    """
    try:
        with open(score_path) as f:
            payload = json.load(f)
            if "score" in payload:
                return float(payload["score"])
            return float(payload["score"])
    except Exception as e:
        print(f"[warn] Could not read score from {score_path}: {e}")
        return float("-inf")


def write_gen_summary(gen_dir: Path, gen_index: int, scores: list[float]) -> None:
    """
    Compute and write a summary.json for the generation with avg, best, and worst scores
    (including consistency-penalized final scores).

    Inputs:
        gen_dir (Path): The generation directory where summary.json will be written.
        gen_index (int): Current generation number.
        scores (list[float]): All trial final_scores for this generation (already consistency-penalized).

    Returns:
        None
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
        f"avg: {avg_str}  best: {best_str}  "
        f"({len(valid_scores)}/{len(scores)} trials) [consistency-adjusted]"
    )


def write_progress(
    gen_index: int, trials_done_in_gen: float, all_scores: list[float]
) -> None:
    """
    Write current optimization progress to progress.json for the UI progress bar to poll.

    Inputs:
        gen_index (int): Current generation number (1-based).
        trials_done_in_gen (float): How many trial-equivalents have progressed in the current generation.
        all_scores (list[float]): Every score collected so far across all generations.

    Returns:
        None
    """
    trials_done_in_gen = max(0.0, min(float(N_PARALLEL), float(trials_done_in_gen)))
    total_done = (gen_index - 1) * N_PARALLEL + trials_done_in_gen
    total = N_GENERATIONS * N_PARALLEL
    payload = {
        "gen_current": gen_index,
        "gen_total": N_GENERATIONS,
        "trials_per_gen": N_PARALLEL,
        "runs_per_trial": N_REPEATS,
        "test_names": list(SELECTED_TEST_NAMES),
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
        "best_score": round(max(all_scores), 4) if all_scores else None,
        "avg_score": (
            round(sum(all_scores) / len(all_scores), 4) if all_scores else None
        ),
        "started_at": 0.0,  # Will be overridden by caller in main loop
        "updated_at": time.time(),
    }

    PROGRESS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def cleanup_generation_status_files(gen_dir: Path) -> None:
    """
    Retain per-run status files so the live monitor can be reopened later and
    still show finished runs.

    Inputs:
        gen_dir (Path): Generation directory.

    Returns:
        None
    """
    return


def aggregate_trial_scores(
    valid_scores: list[float],
) -> tuple[float, float, float, float]:
    """
    Aggregate multiple runs from a trial using configured aggregation method and consistency penalty.

    Inputs:
        valid_scores (list[float]): Valid scores from all runs in the trial.

    Returns:
        tuple[float, float, float, float]:
            - aggregate_score: Mean or median depending on SCORE_AGGREGATION setting
            - consistency_penalty: Penalty for high variance
            - final_score: aggregate_score minus penalty
            - median_score: Median of valid scores
    """
    if not valid_scores:
        return 0.0, 0.0, 0.0, 0.0

    avg_score = sum(valid_scores) / len(valid_scores)
    median_score = statistics.median(valid_scores)

    if SCORE_AGGREGATION == "sum":
        aggregate_score = sum(valid_scores)
        consistency_penalty = 0.0
        final_score = aggregate_score
        return aggregate_score, consistency_penalty, final_score, median_score

    if SCORE_AGGREGATION == "median":
        aggregate_score = median_score
    else:
        # Default to mean to reward occasional strong outcomes
        aggregate_score = avg_score

    # Apply consistency penalty: penalize high variance between runs
    consistency_penalty = CONSISTENCY_PENALTY_COEF * (
        max(valid_scores) - min(valid_scores)
    )
    final_score = aggregate_score - consistency_penalty

    return aggregate_score, consistency_penalty, final_score, median_score
