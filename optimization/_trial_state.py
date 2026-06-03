"""CRUD helpers for trial_state.json files."""

import json
import time
from pathlib import Path

from optimization._scoring_io import (
    _acquire_lock,
    _read_json_safe,
    _release_lock,
    _replace_with_retry,
    write_jsonc,
)


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
