"""
optimize_scoring.py — Score reading, aggregation, progress tracking, and result reporting.

Handles collection of simulation results and
aggregation into generation summaries and progress updates for the UI.
"""

import json
import os
import statistics
import time
import errno
from pathlib import Path

from optimize_config import (
    HARD_FAIL_SCORE,
    PROGRESS_FILE,
    N_PARALLEL,
    N_GENERATIONS,
    N_REPEATS,
    GEN_PROGRESS_POLL_INTERVAL,
    SELECTED_TEST_NAMES,
    SELECTED_TEST_WEIGHTS,
    RUN_PLAN,
    TRIALS_DIR,
)


def write_run_status(path: Path, data: dict) -> None:
    """Write one run status JSON file for the live monitor window.

    Uses atomic file operations to prevent partially written/empty files.

    Args:
        path: Status file path.
        data: Status payload.
    """
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    _replace_with_retry(tmp_path, path)


def _acquire_lock(lock_path: Path, timeout_s: float = 5.0) -> bool:
    """Acquire a simple cross-process file lock using exclusive create."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return True
        except FileExistsError:
            time.sleep(0.01)
        except Exception:
            return False
    return False


def _release_lock(lock_path: Path) -> None:
    """Delete the file lock, silently ignoring errors."""
    try:
        if lock_path.exists():
            lock_path.unlink()
    except Exception:
        pass


def _read_json_safe(path: Path) -> dict:
    """Read a JSON file and return a dict, returning {} on any error."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _replace_with_retry(tmp: Path, path: Path, timeout_s: float = 1.0) -> None:
    """Replace `path` with `tmp` with retries to handle Windows permission errors.

    On Windows, replacing a file can fail with PermissionError if another
    process briefly holds the file open. Retry for a short timeout before
    raising.
    """
    deadline = time.time() + float(timeout_s)
    last_exc: Exception | None = None
    while True:
        try:
            # Prefer Path.replace which uses os.replace under the hood.
            tmp.replace(path)
            return
        except PermissionError as e:
            last_exc = e
            if time.time() >= deadline:
                break
            time.sleep(0.02)
            continue
        except OSError as e:
            # Handle specific Windows access errors similarly.
            last_exc = e
            if e.errno in (errno.EACCES, errno.EPERM) and time.time() < deadline:
                time.sleep(0.02)
                continue
            break
    # Last resort: try os.replace directly once more (will raise original error)
    try:
        os.replace(str(tmp), str(path))
        return
    except Exception:
        if last_exc:
            raise last_exc
        raise


def init_trial_state(
    path: Path,
    *,
    gen_index: int,
    trial_index: int,
    run_plan: list[tuple[str, int, int]],
    test_weights: dict | None = None,
    test_max_scores: dict | None = None,
) -> None:
    """Create one trial_state.json with all run slots pre-populated."""
    runs = []
    for run_index, (test_name, test_run_index, test_run_total) in enumerate(
        run_plan, start=1
    ):
        runs.append(
            {
                "run": run_index,
                "test_name": test_name,
                "test_run_index": test_run_index,
                "test_run_total": test_run_total,
                "run_label": f"{test_name} {test_run_index}/{test_run_total}",
                "state": "not-started",
                "current_frame": 0,
                "total_frames": None,
                "sim_time": 0.0,
                "score": None,
                "reason": "",
                "updated_at": time.time(),
            }
        )

    payload = {
        "gen": gen_index,
        "trial": trial_index,
        "state": "running",
        "updated_at": time.time(),
        "runs": runs,
        "test_weights": test_weights or {},
        "test_max_scores": test_max_scores or {},
    }
    write_jsonc(path, payload)


def update_trial_run(path: Path, run_index: int, patch: dict) -> None:
    """Atomically update one run slot in trial_state.json."""
    lock_path = path.with_suffix(path.suffix + ".lock")
    if not _acquire_lock(lock_path):
        return
    try:
        data = _read_json_safe(path)
        runs = data.get("runs")
        if not isinstance(runs, list):
            runs = []
        while len(runs) < run_index:
            runs.append({"run": len(runs) + 1})
        slot = runs[run_index - 1]
        if not isinstance(slot, dict):
            slot = {"run": run_index}
        slot.update(patch)
        slot["run"] = run_index
        slot["updated_at"] = time.time()
        runs[run_index - 1] = slot
        data["runs"] = runs
        data["updated_at"] = time.time()

        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        _replace_with_retry(tmp, path)
    finally:
        _release_lock(lock_path)


def read_trial_run(path: Path, run_index: int) -> dict | None:
    """Read one run slot from trial_state.json."""
    data = _read_json_safe(path)
    runs = data.get("runs")
    if not isinstance(runs, list) or run_index <= 0 or run_index > len(runs):
        return None
    slot = runs[run_index - 1]
    return slot if isinstance(slot, dict) else None


def read_trial_state(path: Path) -> dict:
    """Read trial_state.json as a dict."""
    return _read_json_safe(path)


def update_trial_summary(path: Path, patch: dict) -> None:
    """Atomically update top-level trial summary fields in trial_state.json."""
    lock_path = path.with_suffix(path.suffix + ".lock")
    if not _acquire_lock(lock_path):
        return
    try:
        data = _read_json_safe(path)
        data.update(patch)
        data["updated_at"] = time.time()
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        _replace_with_retry(tmp, path)
    finally:
        _release_lock(lock_path)


def write_jsonc(path: Path, data: dict) -> None:
    """Write a dict as plain JSON to a .jsonc file.

    Args:
        path: Destination file path.
        data: Data to serialize.
    """
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def write_gen_summary(gen_dir: Path, gen_index: int, scores: list[float]) -> None:
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
    payload = {
        "gen_current": gen_index,
        "gen_total": N_GENERATIONS,
        "trials_per_gen": N_PARALLEL,
        "runs_per_trial": N_REPEATS,
        "test_names": list(SELECTED_TEST_NAMES),
        # Weights as integer percentages for easy consumption by the monitor.
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
        "best_score": round(max(all_scores), 4) if all_scores else None,
        "avg_score": (
            round(sum(all_scores) / len(all_scores), 4) if all_scores else None
        ),
        "started_at": 0.0,  # Will be overridden by caller in main loop
        "updated_at": time.time(),
    }

    PROGRESS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def cleanup_generation_status_files(gen_dir: Path) -> None:
    """Retain per-run status files so the live monitor shows finished runs on reopen."""
    return


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
) -> tuple[float, float, float, float]:
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
        Tuple of (aggregate_score, consistency_penalty, final_score, median_score).
        ``consistency_penalty`` is always 0.0 (removed). ``final_score`` equals
        ``aggregate_score``. ``median_score`` is the raw un-normalized median.
    """
    if not valid_scores:
        return 0.0, 0.0, 0.0, 0.0

    avg_score = sum(valid_scores) / len(valid_scores)
    median_score = statistics.median(valid_scores)

    if aggregation == "sum":
        aggregate_score = sum(valid_scores)
        consistency_penalty = 0.0
        final_score = aggregate_score
        return aggregate_score, consistency_penalty, final_score, median_score

    if aggregation == "exponential_coverage":
        # Reward grippers that can handle ALL cube sizes, not just one.
        # Each additional cube grasped multiplies the score by 10:
        #   1 cube  → sum × 1
        #   2 cubes → sum × 10
        #   3 cubes → sum × 100
        # This makes specialising for one cube far worse than grasping all three.
        n_grasped = len(valid_scores)
        multiplier = 10 ** (n_grasped - 1) if n_grasped > 0 else 0.0
        aggregate_score = sum(valid_scores) * multiplier
        return aggregate_score, 0.0, aggregate_score, median_score

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
        # Default: mean (rewards occasional strong outcomes)
        aggregate_score = avg_score

    consistency_penalty = 0.0
    final_score = aggregate_score
    return aggregate_score, consistency_penalty, final_score, median_score
