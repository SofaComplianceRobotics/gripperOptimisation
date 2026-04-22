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


def load_all_trials() -> list[dict]:
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

            # --- Completion / failed from top-level state field ---
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

            # --- Scores ---
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

            # Prefer top-level aggregate_score, fall back to mean of run scores
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

            # --- Per-test breakdown ---
            # Use top-level test_scores if present and complete
            test_scores = trial_state.get("test_scores") or None

            # If not present, reconstruct from runs using test_weights
            if not test_scores and runs:
                test_weights: dict = trial_state.get("test_weights") or {}
                test_run_scores: dict[str, list[float]] = {}
                for run in runs:
                    if not isinstance(run, dict):
                        continue
                    tname = run.get("test_name")
                    raw = run.get("score")
                    if tname and isinstance(raw, (int, float)):
                        test_run_scores.setdefault(tname, []).append(float(raw))

                if test_run_scores:
                    total_weight = sum(
                        test_weights.get(t, 1.0) for t in test_run_scores
                    )
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
                        test_scores[tname] = {
                            "run_count": len(tscores),
                            "run_scores": tscores,
                            "aggregate_score": agg,
                            "median_score": statistics.median(tscores),
                            "run_total": len(tscores),
                            "weight_pct": wpct,
                        }
            if test_scores:
                final_score = sum(
                    float(info.get("aggregate_score", 0.0) or 0.0)
                    * (float(info.get("weight_pct", 0.0) or 0.0) / 100.0)
                    for info in test_scores.values()
                    if isinstance(info, dict)
                )
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
