"""
Scene: random_cube_pick

Variant of grasp_hold where the cube size cycles across runs and the
mass is randomised per generation.

This scene is identical to grasp_hold in structure — the only difference
is the env-var defaults set below, which the PlaybackController in
grasp_hold/scene.py already reads and handles via SHAPEOPT_TEST_MODE.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

def _ensure_scene_paths() -> tuple[Path, Path, Path, Path]:
    script_dir = Path(__file__).resolve().parent
    src_root = next(
        (candidate for candidate in (script_dir, *script_dir.parents) if (candidate / "labtests").is_dir()),
        script_dir.parents[1],
    )
    app_root = src_root.parent
    lab_root = app_root.parent
    for candidate in (str(lab_root), str(app_root), str(src_root)):
        if candidate not in sys.path:
            sys.path.insert(0, candidate)
    return script_dir, src_root, app_root, lab_root


SCRIPT_DIR, SRC_ROOT, APP_ROOT, LAB_ROOT = _ensure_scene_paths()

# Activate random-cube mode before the shared scene reads env vars
os.environ.setdefault("SHAPEOPT_TEST_MODE", "random_cube_pick")
os.environ.setdefault("LAB_SHAPEOPT_RECORDING_TARGET", "random_cube_pick")
os.environ.setdefault("SHAPEOPT_FINISH_BONUS", "2.0")

# Delegate entirely — no duplication
from labtests.grasp_hold.scene import createScene as createScene  # noqa: F401, E402
