"""
Scene: random_cube_pick

Variant of grasp_hold: same motor recording, same fail/score rules, but:
  - cube size cycles across 3 runs (driven by OPTUNA_RUN_SLOT)
    - cube mass follows a deterministic binary-search ladder per size
    - each successful pickup scores 1 to 10 points based on the selected weight
    - the final trial score is the sum of the 3 size scores, capped at 30

What this file owns:
    - Cube size cycling and deterministic mass resolution
    - SHAPEOPT_CUBE_WEIGHT_MIN/MAX/STEP env vars
    - PlaybackController overrides (fixed mass, ladder-point scoring)
  - createScene() wiring

Everything else (env-var config, plugins, controller logic) comes from core.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(
    0, str(next(c for c in Path(__file__).parents if (c / "labtests").is_dir()))
)
from labtests.core.scene_paths import ensure_scene_paths
from labtests.random_cube_pick.carryover import load_seed_indices
from labtests.random_cube_pick.weight_search import (
    DEFAULT_WEIGHT_MAX,
    DEFAULT_WEIGHT_MIN,
    DEFAULT_WEIGHT_STEP,
    CubeSearchSpec,
    boundary_score_for_index,
    build_search_snapshot,
    record_cube_result,
    select_cube_spec,
    weight_points_for_index,
)

SCRIPT_DIR, SRC_ROOT, APP_ROOT, LAB_ROOT = ensure_scene_paths(__file__)

from core.timing_config import DT_DIRECT as DT

RECORD_FILE = str(
    LAB_ROOT / "runtime" / "recordings" / "random_cube_pick" / "motor_recording.json"
)


def createScene(rootnode):
    """Build the random_cube_pick scene: cycling cube sizes and ladder-point scoring."""
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

    weight_min = float(
        os.environ.get("SHAPEOPT_CUBE_WEIGHT_MIN", str(DEFAULT_WEIGHT_MIN))
    )
    weight_max = float(
        os.environ.get("SHAPEOPT_CUBE_WEIGHT_MAX", str(DEFAULT_WEIGHT_MAX))
    )
    weight_step = float(
        os.environ.get("SHAPEOPT_CUBE_WEIGHT_STEP", str(DEFAULT_WEIGHT_STEP))
    )
    seed_indices = load_seed_indices(LAB_ROOT)

    ladder_state_path = (
        Path(cfg.meta.trial_state_path).with_name("random_cube_pick_weight_search.json")
        if cfg.meta.trial_state_path
        else None
    )

    cube_spec: CubeSearchSpec = select_cube_spec(
        LAB_ROOT,
        cfg.meta.run_slot,
        weight_min=weight_min,
        weight_max=weight_max,
        step_size=weight_step,
        state_path=ladder_state_path,
        seed_index=seed_indices.get(cfg.meta.run_slot),
        generation_id=cfg.meta.gen,
    )
    cube_scale = cube_spec.cube_scale
    cube_mass = cube_spec.cube_mass
    cube_points = weight_points_for_index(cube_spec.weight_index)

    print(
        f"[cube] random_cube_pick slot={cfg.meta.run_slot} gen={cfg.meta.gen} "
        f"scale={cube_scale} mass={cube_mass:.5f}kg points={cube_points} "
        f"(idx={cube_spec.weight_index}, {cube_spec.status})"
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

    original_write_status = writer.write_status

    def write_status(payload: dict) -> None:
        snapshot = build_search_snapshot(
            LAB_ROOT,
            cfg.meta.run_slot,
            weight_min=weight_min,
            weight_max=weight_max,
            step_size=weight_step,
            state_path=ladder_state_path,
            generation_id=cfg.meta.gen,
        )
        merged = {**payload, **snapshot}
        original_write_status(merged)

    writer.write_status = write_status

    Base = make_playback_controller(Sofa.Core.Controller)

    class PlaybackController(Base):
        """Variant of BasePlaybackController with fixed mass and ladder-point scoring."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._ladder_state_path = ladder_state_path

        def _initial_cube_mass(self) -> float:
            return cube_mass

        def _update_overload_mass(self) -> None:
            # Mass is fixed — no ramp keeps the draw fair across runs
            self._set_cube_mass(cube_mass)

        def _finish_run(
            self, score: float | None, reason: str, *, pruned: bool = False
        ) -> None:
            succeeded = bool(self.was_picked_up and not pruned)
            summary = {}
            try:
                summary = record_cube_result(
                    LAB_ROOT,
                    cube_spec,
                    score=None,
                    succeeded=succeeded,
                    state_path=self._ladder_state_path,
                    generation_id=cfg.meta.gen,
                )
            except Exception as exc:
                print(f"[cube-search] Could not record ladder result: {exc}")

            if summary.get("converged"):
                final_score = float(
                    boundary_score_for_index(int(summary["boundary_index"]))
                )
                original_reason = (
                    f"ladder converged boundary={int(summary['boundary_index']) + 1}"
                )
                self.writer.write_score_and_stop(final_score, original_reason)
                return

            payload = {
                "state": "running",
                "score": None,
                "reason": reason,
                "probe_outcome": "success" if succeeded else "failure",
                "probe_finished": True,
            }
            self.writer.write_status(payload)
            self.rootnode.animate = False
            os.kill(os.getpid(), 9)

        def _on_horizon_complete(self, sim_time: float) -> None:
            self._finish_run(
                None,
                f"horizon complete t={sim_time:.2f}s picked={self.was_picked_up}",
                pruned=not self.was_picked_up,
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
    writer.write_status(
        {
            "cube_mass": cube_mass,
            "cube_scale": cube_scale,
            "weight_points": cube_points,
            "weight_points_max": 10,
            "weight_index": cube_spec.weight_index,
            "weight_levels": cube_spec.weight_levels,
            "weight_search_status": cube_spec.status,
            "weight_step": weight_step,
        }
    )
    return rootnode
