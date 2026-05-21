"""Shared environment-variable configuration for all ShapeOPT scenes.

The optimizer injects parameters through environment variables so that SOFA
scenes are stateless — a fresh process reads its full config from the
environment at startup. This module centralises all that parsing so each
scene file only needs one call to get a fully populated config object.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from core.timing_config import DT_DIRECT


@dataclass(frozen=True)
class OptunaMeta:
    """Optuna/scoring metadata required by every test.

    Use OptunaMeta.from_env() in createScene() (or at module level after path
    bootstrap).  All tests need these five values to write scores.
    """

    trial_state_path: str | None
    run_slot: int
    gen: int
    trial: int
    run: int

    @classmethod
    def from_env(cls) -> "OptunaMeta":
        """Construct from the standard OPTUNA_* environment variables."""
        return cls(
            trial_state_path=os.environ.get("OPTUNA_TRIAL_STATE_PATH"),
            run_slot=int(os.environ.get("OPTUNA_RUN_SLOT", "0")),
            gen=int(os.environ.get("OPTUNA_GEN", "0")),
            trial=int(os.environ.get("OPTUNA_TRIAL", "0")),
            run=int(os.environ.get("OPTUNA_RUN", "0")),
        )

    @property
    def run_info(self) -> dict:
        """Return a dict with gen/trial/run keys for status payloads."""
        return {"gen": self.gen, "trial": self.trial, "run": self.run}


@dataclass(frozen=True)
class PlaybackConfig:
    """All env-var config for direct-mode (motor-playback) cube-pick tests.

    Call PlaybackConfig.from_env(lab_root) inside createScene().
    Tests read their own additional env vars on top of this.
    The three override points in BasePlaybackController (_initial_cube_mass,
    _update_overload_mass, _on_horizon_complete) let tests change behaviour
    without touching any value here.
    """

    # ── Optuna metadata ───────────────────────────────────────────────────────
    meta: OptunaMeta
    # ── Paths ─────────────────────────────────────────────────────────────────
    gripper_mesh_path: str
    # ── Scene physics ─────────────────────────────────────────────────────────
    friction_coef: float
    floor_center_y: float
    cube_spawn_clearance: float
    cube_spawn_time: float
    cube_prespawn_offset: float
    drop_below_spawn_tol: float
    pickup_above_spawn_tol: float
    # ── Scoring thresholds ────────────────────────────────────────────────────
    early_stop_sim_time: float
    floor_y_threshold: float
    floor_y_buffer: float
    pickup_y_threshold: float
    drop_penalty: float
    overload_max_time: float
    cube_mass_start: float
    cube_mass_max: float
    cube_mass_ramp_time: float
    early_contact_stop_time: float
    early_contact_penalty: float
    no_pickup_penalty: float
    undercube_penalty: float
    undercube_margin: float
    enable_undercube_check: bool

    @classmethod
    def from_env(cls, lab_root: Path) -> "PlaybackConfig":
        """Construct from environment variables, resolving paths relative to lab_root."""
        assets_root = lab_root.parent.parent
        return cls(
            meta=OptunaMeta.from_env(),
            gripper_mesh_path=os.environ.get(
                "OPTUNA_STL_PATH",
                str(
                    assets_root
                    / "data"
                    / "meshes"
                    / "centerparts"
                    / "new_gripper_collision.stl"
                ),
            ),
            friction_coef=float(os.environ.get("SHAPEOPT_FRICTION_COEF", "0.6")),
            floor_center_y=float(os.environ.get("SHAPEOPT_FLOOR_CENTER_Y", "-230.0")),
            cube_spawn_clearance=float(
                os.environ.get("SHAPEOPT_CUBE_SPAWN_CLEARANCE", "10")
            ),
            cube_spawn_time=float(os.environ.get("SHAPEOPT_CUBE_SPAWN_TIME", "0.4")),
            cube_prespawn_offset=float(
                os.environ.get("SHAPEOPT_CUBE_PRESPAWN_OFFSET", "200.0")
            ),
            drop_below_spawn_tol=float(
                os.environ.get("SHAPEOPT_DROP_BELOW_SPAWN_TOL", "0.5")
            ),
            pickup_above_spawn_tol=float(
                os.environ.get("SHAPEOPT_PICKUP_ABOVE_SPAWN_TOL", "1.0")
            ),
            early_stop_sim_time=float(
                os.environ.get("EARLY_STOP_SIM_TIME", str(2.0 * (DT_DIRECT / 0.02)))
            ),
            floor_y_threshold=float(os.environ.get("FLOOR_Y_THRESHOLD", "-245.0")),
            floor_y_buffer=float(os.environ.get("FLOOR_Y_BUFFER", "5.0")),
            pickup_y_threshold=float(os.environ.get("PICKUP_Y_THRESHOLD", "-215.0")),
            drop_penalty=float(os.environ.get("DROP_PENALTY", "50.0")),
            overload_max_time=float(os.environ.get("OVERLOAD_MAX_TIME", "12.0")),
            cube_mass_start=float(os.environ.get("CUBE_MASS_START", "0.02")),
            cube_mass_max=float(os.environ.get("CUBE_MASS_MAX", "1.0")),
            cube_mass_ramp_time=float(os.environ.get("CUBE_MASS_RAMP_TIME", "8.0")),
            early_contact_stop_time=float(
                os.environ.get("EARLY_CONTACT_STOP_TIME", "0.6")
            ),
            early_contact_penalty=float(
                os.environ.get("EARLY_CONTACT_PENALTY", "-1.0")
            ),
            no_pickup_penalty=float(os.environ.get("NO_PICKUP_PENALTY", "0.0")),
            undercube_penalty=float(os.environ.get("UNDERCUBE_PENALTY", "-0.2")),
            undercube_margin=float(os.environ.get("UNDERCUBE_MARGIN", "0.0")),
            enable_undercube_check=os.environ.get("ENABLE_UNDERCUBE_CHECK", "0") == "1",
        )
