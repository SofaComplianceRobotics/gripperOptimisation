"""
Scene: grasp_hold

Standard cube-grasp-and-lift benchmark.
Direct mode: replays a recorded motor trajectory, scores by hold time.

What this file owns:
  - RECORD_FILE path
  - cube_scale ([8, 8, 8] — the standard grasp cube)
  - createScene() wiring

Everything else (env-var config, plugins, controller logic) comes from core.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_scene_paths() -> tuple[Path, Path, Path, Path]:
    """Resolve and insert script/src/app/lab paths into sys.path if missing.

    Returns:
        Tuple of (script_dir, src_root, app_root, lab_root).
    """
    script_dir = Path(__file__).resolve().parent
    src_root = next(
        (
            candidate
            for candidate in (script_dir, *script_dir.parents)
            if (candidate / "labtests").is_dir()
        ),
        script_dir.parents[1],
    )
    app_root = src_root.parent
    lab_root = app_root.parent
    for candidate in (str(lab_root), str(app_root), str(src_root)):
        if candidate not in sys.path:
            sys.path.insert(0, candidate)
    return script_dir, src_root, app_root, lab_root


SCRIPT_DIR, SRC_ROOT, APP_ROOT, LAB_ROOT = _ensure_scene_paths()

RECORD_FILE = str(
    LAB_ROOT / "runtime" / "recordings" / "grasp_hold" / "motor_recording.json"
)
DT = 0.01


def createScene(rootnode):
    """Build the grasp_hold direct-mode scene with motor playback and scoring."""
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
        cube_scale=[8, 8, 8],
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