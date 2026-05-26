"""Carryover helpers for random_cube_pick generation seeds."""

from __future__ import annotations

import json
from pathlib import Path

SEED_FILE_NAME = "random_cube_pick_seed_weights.json"


def seed_file_path(lab_root: Path) -> Path:
    return Path(lab_root) / "runtime" / SEED_FILE_NAME


def load_seed_indices(lab_root: Path) -> dict[int, int]:
    path = seed_file_path(lab_root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return {}
        raw = payload.get("seed_indices")
        if not isinstance(raw, dict):
            return {}
        result: dict[int, int] = {}
        for key, value in raw.items():
            try:
                slot = int(key)
                index = int(value)
            except Exception:
                continue
            result[slot] = index
        return result
    except Exception:
        return {}


def save_seed_indices(lab_root: Path, seed_indices: dict[int, int]) -> None:
    path = seed_file_path(lab_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "seed_indices": {str(int(k)): int(v) for k, v in seed_indices.items()},
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
