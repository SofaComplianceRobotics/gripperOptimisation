"""
Scene: random_cube_pick

Variant of grasp_hold: same motor recording, same fail/score rules, but:
  - cube size cycles across 3 runs (driven by OPTUNA_RUN_SLOT)
  - cube mass is randomised per generation (seeded by OPTUNA_GEN)
  - completing the full horizon scores hold_time + SHAPEOPT_FINISH_BONUS
    instead of being pruned

What this file owns:
  - Cube size cycling and random mass resolution
  - SHAPEOPT_FINISH_BONUS, SHAPEOPT_CUBE_WEIGHT_MIN/MAX env vars
  - PlaybackController overrides (fixed mass, finish-bonus scoring)
  - createScene() wiring

Everything else (env-var config, plugins, controller logic) comes from core.
"""

from __future__ import annotations

import os
import random
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
    LAB_ROOT / "runtime" / "recordings" / "random_cube_pick" / "motor_recording.json"
)
DT = 0.01

# Size cycles over 3 runs, indexed by OPTUNA_RUN_SLOT
_CUBE_SIZE_CYCLE = ([5, 5, 5], [8, 8, 8], [20, 20, 20])


def _resolve_cube_config(
    run_slot: int, gen: int, weight_min: float, weight_max: float
) -> tuple[list[float], float]:
    """Return (cube_scale, cube_mass) for this run slot and generation."""
    cube_scale = list(_CUBE_SIZE_CYCLE[run_slot % 3])
    lo = min(weight_min, weight_max)
    hi = max(weight_min, weight_max)
    cube_mass = random.Random(gen).uniform(lo, hi)
    print(
        f"[cube] random_cube_pick slot={run_slot} gen={gen} "
        f"scale={cube_scale} mass={cube_mass:.5f}kg"
    )
    return cube_scale, cube_mass


def createScene(rootnode):
    """Build the random_cube_pick scene: cycling cube sizes, seeded mass, finish bonus."""
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

    finish_bonus = float(os.environ.get("SHAPEOPT_FINISH_BONUS", "2.0"))
    weight_min = float(os.environ.get("SHAPEOPT_CUBE_WEIGHT_MIN", "0.02"))
    weight_max = float(os.environ.get("SHAPEOPT_CUBE_WEIGHT_MAX", "0.2"))

    cube_scale, cube_mass = _resolve_cube_config(
        cfg.meta.run_slot, cfg.meta.gen, weight_min, weight_max
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
        cube_mass=cube_mass,
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

    class PlaybackController(Base):
        """Variant of BasePlaybackController with fixed mass and a finish bonus."""

        def _initial_cube_mass(self) -> float:
            return cube_mass

        def _update_overload_mass(self) -> None:
            # Mass is fixed — no ramp keeps the draw fair across runs
            self._set_cube_mass(cube_mass)

        def _on_horizon_complete(self, sim_time: float) -> None:
            score = self.hold_time + finish_bonus
            self.writer.write_score_and_stop(
                score,
                f"horizon complete t={sim_time:.2f}s hold_time={self.hold_time:.2f}s "
                f"finish_bonus={finish_bonus:.2f}",
            )

    nodes.simulation.addObject(
        PlaybackController(
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
