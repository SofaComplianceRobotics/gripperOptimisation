"""
analyze_io.py — Data loading and I/O for trial and generation results.

Loads trial results from trial_state.json files in the trials directory and
aggregates them into convenient data structures for analysis and visualization.
"""

import json
import statistics
from pathlib import Path

from analyze_config import (
    TRIALS_DIR,
    HARD_FAIL_SCORE,
    SCORE_AGGREGATION,
)


def _normalized_weighted_score(test_scores: dict) -> float:
    """Recompute the final score out of 100 from per-test breakdown data.

    Formula: Σ min(aggregate_score_i / max_score_i, 1.0) * weight_pct_i

    Falls back gracefully when max_score or weight_pct is missing so that
    older trial_state.json files (written before this change) still load.

    Args:
        test_scores: The test_scores dict from trial_state.json, keyed by test
            name. Each value is a dict with aggregate_score, weight_pct, and
            optionally max_score.

    Returns:
        Weighted normalized score in [0, 100].
    """
    total = 0.0
    total_weight = 0.0
    for info in test_scores.values():
        if not isinstance(info, dict):
            continue
        raw_score = info.get("aggregate_score", 0.0) or 0.0
        max_score = float(info.get("max_score") or 0.0)
        weight_pct = float(info.get("weight_pct", 0.0) or 0.0)

        if max_score > 0:
            normalized = min(float(raw_score) / max_score, 1.0)
        else:
            # Legacy fallback: treat score as already normalized (old data).
            normalized = float(raw_score)

        total += normalized * weight_pct
        total_weight += weight_pct

    # If weights don't sum to ~100 (e.g. old data without weight_pct), fall back
    # to a plain weighted mean scaled to 100.
    if total_weight > 0 and abs(total_weight - 100.0) > 1.0:
        total = (total / total_weight) * 100.0

    return total


def load_all_trials() -> list[dict]:
    """Load every trial_state.json from the trials directory into flat dicts.

    Returns:
        list[dict]: One record per trial, sorted by generation then trial index.
            Each record includes score, fail status, per-test breakdown, and a
            chronological ``chron`` counter used as the X-axis in plots.
    """
    records = []
    chron = 0

    for gen_dir in sorted(TRIALS_DIR.glob("gen_*")):
        gen_index = int(gen_dir.name.split("_")[1])
        for trial_dir in sorted(gen_dir.glob("trial_*")):
            trial_index = int(trial_dir.name.split("_")[1])

            trial_state_path = trial_dir / "trial_state.json"
            if not trial_state_path.exists():
                continue

            try:
                trial_state = json.loads(trial_state_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(trial_state, dict):
                continue

            terminal_states = {
                "done",
                "failed",
                "error",
                "pruned",
                "skipped",
                "cancelled",
            }

            trial_level_state = str(trial_state.get("state", "")).lower()
            is_complete = trial_level_state in terminal_states
            failed = trial_level_state in {
                "failed",
                "error",
                "pruned",
                "skipped",
                "cancelled",
            }
            fail_reason = str(trial_state.get("outcome", "") or "").lower()

            runs = trial_state.get("runs", [])
            if not isinstance(runs, list):
                runs = []

            run_scores = []
            for run in runs:
                if not isinstance(run, dict):
                    continue
                raw_score = run.get("score")
                if isinstance(raw_score, (int, float)):
                    run_scores.append(float(raw_score))

            valid = run_scores  # all numeric scores, including 0.0 and negatives

            # Prefer top-level aggregate_score, fall back to mean of run scores.
            if trial_state.get("aggregate_score") is not None:
                score = float(trial_state["aggregate_score"])
            elif valid:
                score = (
                    statistics.mean(valid)
                    if SCORE_AGGREGATION != "median"
                    else statistics.median(valid)
                )
            else:
                score = 0.0

            raw_final = trial_state.get("final_score")
            if isinstance(raw_final, (int, float)):
                final_score = float(raw_final)
            else:
                final_score = score

            # Use top-level test_scores if present and complete.
            test_scores = trial_state.get("test_scores") or None

            # If not present, reconstruct from runs using test_weights.
            # Skip reconstruction for failed trials: they have no max_score context,
            # so any reconstruction would treat raw scores as normalized fractions
            # and produce wildly inflated contributions.
            if not test_scores and runs and not failed:
                test_weights: dict = trial_state.get("test_weights") or {}
                test_max_scores: dict = trial_state.get("test_max_scores") or {}
                test_run_scores: dict[str, list[float]] = {}
                for run in runs:
                    if not isinstance(run, dict):
                        continue
                    tname = run.get("test_name")
                    raw = run.get("score")
                    if tname and isinstance(raw, (int, float)):
                        test_run_scores.setdefault(tname, []).append(float(raw))

                if test_run_scores:
                    # Use ALL expected test names from the run plan so that
                    # partial (still-running) trials get correct weight fractions
                    # instead of 100% going to only the completed tests.
                    all_run_test_names = {
                        r.get("test_name")
                        for r in runs
                        if isinstance(r, dict) and r.get("test_name")
                    }
                    total_weight = sum(
                        test_weights.get(t, 1.0) for t in all_run_test_names
                    ) or 1.0
                    test_scores = {}
                    for tname, tscores in test_run_scores.items():
                        agg = (
                            statistics.mean(tscores)
                            if SCORE_AGGREGATION != "median"
                            else statistics.median(tscores)
                        )
                        wpct = (
                            (test_weights.get(tname, 1.0) / total_weight * 100.0)
                            if total_weight
                            else 0.0
                        )
                        max_s = float(test_max_scores.get(tname) or 0.0)
                        test_scores[tname] = {
                            "run_count": len(tscores),
                            "run_scores": tscores,
                            "aggregate_score": agg,
                            "median_score": statistics.median(tscores),
                            "run_total": len(tscores),
                            "weight_pct": wpct,
                            "max_score": max_s,
                        }

            # Recompute final_score using the normalized weighted formula.
            # This ensures the displayed score is always out of 100 regardless
            # of whether the trial_state was written by old or new code.
            if test_scores:
                final_score = _normalized_weighted_score(test_scores)
                score = final_score

            records.append(
                {
                    "gen_index": gen_index,
                    "trial_index": trial_index,
                    "gen_name": gen_dir.name,
                    "trial_name": trial_dir.name,
                    "score": score,
                    "final_score": final_score,
                    "failed": failed,
                    "fail_reason": fail_reason,
                    "outcome_reason": fail_reason,
                    "n_runs": len(valid),
                    "run_scores": valid,
                    "all_run_scores": run_scores,
                    "test_scores": test_scores,
                    "is_complete": is_complete,
                    "chron": chron,
                }
            )
            chron += 1

    return records


def load_gen_summaries() -> list[dict]:
    """Load generation summaries from summary.json files.

    Returns:
        list[dict]: Summary records by generation.
    """
    summaries = []
    for gen_dir in sorted(TRIALS_DIR.glob("gen_*")):
        summary_path = gen_dir / "summary.json"
        if not summary_path.exists():
            continue
        try:
            data = json.loads(summary_path.read_text())
            summaries.append(
                {
                    "gen_index": data["gen"],
                    "avg_score": data["avg_score"],
                    "best_score": data["best_score"],
                    "n_trials": data.get("n_trials"),
                    "n_valid": data.get("n_valid"),
                }
            )
        except Exception:
            continue
    return summaries
