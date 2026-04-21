"""
analyze_io.py — Data loading and I/O for trial and generation results.

Loads trial results from the trials directory and aggregates them into
convenient data structures for analysis and visualization.
"""

import json
import os
import statistics
from pathlib import Path

from analyze_config import (
    TRIALS_DIR,
    CONSISTENCY_PENALTY_COEF,
    HARD_FAIL_SCORE,
    SCORE_AGGREGATION,
)


def load_all_trials() -> list[dict]:
    """Load all trial results, including failures, from the trials directory.
    Computes final_score with consistency penalty using the current runtime settings.

    Returns:
        list[dict]: Trial records in chronological order.
    """
    records = []
    chron = 0
    failed_states = {"failed", "error", "cancelled", "skipped"}

    for gen_dir in sorted(TRIALS_DIR.glob("gen_*")):
        gen_index = int(gen_dir.name.split("_")[1])
        for trial_dir in sorted(gen_dir.glob("trial_*")):
            trial_index = int(trial_dir.name.split("_")[1])

            run_files = sorted(trial_dir.glob("score_run*.json"))
            status_files = sorted(trial_dir.glob("status_run*.json"))

            if not run_files:
                failed_from_status = False
                fail_reason = "no score files"
                trial_stats_path = trial_dir / "trial_stats.json"

                if trial_stats_path.exists():
                    try:
                        trial_stats = json.loads(trial_stats_path.read_text())
                        stats_valid_scores = trial_stats.get("run_scores_valid", [])
                        stats_all_scores = trial_stats.get("run_scores", [])
                        records.append(
                            {
                                "gen_index": gen_index,
                                "trial_index": trial_index,
                                "gen_name": gen_dir.name,
                                "trial_name": trial_dir.name,
                                "score": trial_stats.get(
                                    "aggregate_score", trial_stats.get("avg_score", 0.0)
                                ),
                                "final_score": trial_stats.get("final_score", 0.0),
                                "failed": False,
                                "fail_reason": str(trial_stats.get("outcome", "")),
                                "outcome_reason": str(trial_stats.get("outcome", "")),
                                "n_runs": int(trial_stats.get("n_runs", 0)),
                                "run_scores": [
                                    float(s)
                                    for s in stats_valid_scores
                                    if isinstance(s, (int, float))
                                ],
                                "all_run_scores": [
                                    float(s)
                                    for s in stats_all_scores
                                    if isinstance(s, (int, float))
                                ],
                                "chron": chron,
                            }
                        )
                        chron += 1
                        continue
                    except Exception:
                        pass

                for sf in status_files:
                    try:
                        s = json.loads(sf.read_text())
                    except Exception:
                        continue
                    state = str(s.get("state", "")).lower()
                    reason = str(s.get("reason", "")).lower()
                    if state in failed_states or "geometry export failed" in reason:
                        failed_from_status = True
                        if reason:
                            fail_reason = reason
                        break

                if failed_from_status or trial_dir.exists():
                    records.append(
                        {
                            "gen_index": gen_index,
                            "trial_index": trial_index,
                            "gen_name": gen_dir.name,
                            "trial_name": trial_dir.name,
                            "score": 0.0,
                            "final_score": 0.0,
                            "failed": True,
                            "fail_reason": fail_reason,
                            "outcome_reason": fail_reason,
                            "n_runs": 0,
                            "run_scores": [],
                            "all_run_scores": [],
                            "chron": chron,
                        }
                    )
                    chron += 1
                continue

            run_scores = []
            for sf in run_files:
                try:
                    payload = json.loads(sf.read_text())
                    run_scores.append(float(payload.get("score", payload["score"])))
                except Exception as e:
                    continue

            valid = [s for s in run_scores if s != float("-inf")]
            failed = len(valid) == 0
            score = (
                statistics.median(valid)
                if valid and SCORE_AGGREGATION == "median"
                else (statistics.mean(valid) if valid else 0.0)
            )
            outcome_reason = ""

            for sf in status_files:
                try:
                    s = json.loads(sf.read_text())
                except Exception:
                    continue
                reason = str(s.get("reason", "")).strip()
                if reason:
                    outcome_reason = reason
                    break

            final_score = score
            if valid and not failed:
                consistency_penalty = CONSISTENCY_PENALTY_COEF * (
                    max(valid) - min(valid)
                )
                final_score = score - consistency_penalty
            else:
                final_score = 0.0

            trial_stats_path = trial_dir / "trial_stats.json"
            if trial_stats_path.exists():
                try:
                    trial_stats = json.loads(trial_stats_path.read_text())
                    score = trial_stats.get(
                        "aggregate_score", trial_stats.get("avg_score", score)
                    )
                    final_score = trial_stats.get("final_score", final_score)
                except Exception:
                    pass

            records.append(
                {
                    "gen_index": gen_index,
                    "trial_index": trial_index,
                    "gen_name": gen_dir.name,
                    "trial_name": trial_dir.name,
                    "score": score,
                    "final_score": final_score,
                    "failed": failed,
                    "fail_reason": outcome_reason.lower() if failed else "",
                    "outcome_reason": outcome_reason.lower(),
                    "n_runs": len(valid),
                    "run_scores": valid,
                    "all_run_scores": run_scores,
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
