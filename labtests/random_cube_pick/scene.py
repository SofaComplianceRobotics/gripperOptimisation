"""
Scene: random_cube_pick

Variant of grasp_hold: identical motor recording, controller, scoring and
overload behaviour, but the cube size changes per run slot. Each of the three
slots lifts one cube size at the standard grasp_hold weight and is scored by
hold time; the trial score is the sum across the three sizes.

What this file owns:
  - CUBE_SIZES (the three cube scales, indexed by run slot)
  - RECORD_FILE path
  - createScene() wiring

Everything else (env-var config, plugins, controller logic, hold-time scoring)
comes from core.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(
    0, str(next(c for c in Path(__file__).parents if (c / "labtests").is_dir()))
)
from launcher.bootstrap import bootstrap_lab

SCRIPT_DIR, SRC_ROOT, APP_ROOT, LAB_ROOT = bootstrap_lab(__file__)

from geometry.timing_config import DT_DIRECT as DT

RECORD_FILE = str(
    LAB_ROOT / "runtime" / "recordings" / "random_cube_pick" / "motor_recording.json"
)

# Cube scales lifted per run, in fixed order. The run is keyed off the per-test
# run index (1/3, 2/3, 3/3), so the size sequence is always 8 → 10 → 12 no
# matter where the test lands in the global run order.
CUBE_SIZES = (
    [8.0, 8.0, 8.0],
    [10.0, 10.0, 10.0],
    [12.0, 12.0, 12.0],
)


def _cube_scale_for_run() -> list:
    """Return the cube scale for this run, ordered 8 → 10 → 12.

    Keyed off LAB_SHAPEOPT_TEST_RUN_INDEX (the 1-based per-test index the
    optimizer sets), so the size depends only on which of the three test runs
    this is — not on the global run slot. Falls back to OPTUNA_RUN_SLOT for
    manual launches, then to the first size if neither is set.
    """
    raw = os.environ.get("LAB_SHAPEOPT_TEST_RUN_INDEX") or os.environ.get(
        "OPTUNA_RUN_SLOT"
    )
    try:
        index = int(raw)
    except (TypeError, ValueError):
        index = 1
    return list(CUBE_SIZES[max(0, index - 1) % len(CUBE_SIZES)])


def createScene(rootnode):
    """Build the random_cube_pick scene: grasp_hold with a per-slot cube size."""
    import Sofa.Core  # type: ignore

    from labtests.core.base_scene import build_base_scene
    from labtests.core.modules.collision_stl import setup as setup_collision
    from labtests.core.modules.cube_floor import setup as setup_cube_floor
    from labtests.core.modules.motor_playback import setup as setup_playback
    from labtests.core.playback_controller import make_playback_controller
    from labtests.core.plugins import add_required_plugins
    from labtests.core.scene_config import PlaybackConfig
    from labtests.core.scoring import ScoreWriter

    cfg = PlaybackConfig.from_env(LAB_ROOT)
    cube_scale = _cube_scale_for_run()

    print(
        f"[cube] random_cube_pick slot={cfg.meta.run_slot} gen={cfg.meta.gen} "
        f"scale={cube_scale} mass={cfg.cube_mass_start} kg"
    )

    nodes = build_base_scene(rootnode, inverse=False, friction=cfg.friction_coef)
    if nodes is None:
        return
    print(f"[contact] friction configured with mu={cfg.friction_coef:.6f}")

    add_required_plugins(nodes.simulation)
    rootnode.dt = DT

    gripper_collision = setup_collision(nodes.emio, cfg.gripper_mesh_path)

    cube_handles = setup_cube_floor(
        nodes.simulation,
        gripper_collision,
        cube_scale=cube_scale,
        cube_mass=cfg.cube_mass_start,
        floor_center_y=cfg.floor_center_y,
        cube_spawn_clearance=cfg.cube_spawn_clearance,
    )

    playback = setup_playback(nodes.emio, RECORD_FILE)

    writer = ScoreWriter(
        rootnode,
        run_info=cfg.meta.run_info,
        trial_state_path=cfg.meta.trial_state_path,
        run_slot=cfg.meta.run_slot,
    )

    Base = make_playback_controller(Sofa.Core.Controller)
    nodes.simulation.addObject(
        Base(
            name="PlaybackController",
            rootnode=rootnode,
            playback=playback,
            cube_handles=cube_handles,
            gripper_collision=gripper_collision,
            writer=writer,
            cfg=cfg,
        )
    )
    return rootnode
