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
        trial_state_path = os.environ.get("OPTUNA_TRIAL_STATE_PATH")
        if trial_state_path is None:
            return cls(trial_state_path=None, run_slot=0, gen=0, trial=0, run=0)
        return cls(
            trial_state_path=trial_state_path,
            run_slot=int(os.environ["OPTUNA_RUN_SLOT"]),
            gen=int(os.environ["OPTUNA_GEN"]),
            trial=int(os.environ["OPTUNA_TRIAL"]),
            run=int(os.environ["OPTUNA_RUN"]),
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
            friction_coef=float(os.environ["SHAPEOPT_FRICTION_COEF"]),
            floor_center_y=-230.0,
            cube_spawn_clearance=10.0,
            cube_spawn_time=0.4,
            cube_prespawn_offset=200.0,
            drop_below_spawn_tol=0.5,
            pickup_above_spawn_tol=1.0,
            early_stop_sim_time=float(os.environ["EARLY_STOP_SIM_TIME"]),
            floor_y_threshold=float(os.environ["FLOOR_Y_THRESHOLD"]),
            floor_y_buffer=float(os.environ["FLOOR_Y_BUFFER"]),
            pickup_y_threshold=float(os.environ["PICKUP_Y_THRESHOLD"]),
            drop_penalty=float(os.environ["DROP_PENALTY"]),
            overload_max_time=float(os.environ["OVERLOAD_MAX_TIME"]),
            cube_mass_start=float(os.environ["CUBE_MASS_START"]),
            cube_mass_max=float(os.environ["CUBE_MASS_MAX"]),
            cube_mass_ramp_time=float(os.environ["CUBE_MASS_RAMP_TIME"]),
            early_contact_stop_time=0.6,
            early_contact_penalty=float(os.environ["EARLY_CONTACT_PENALTY"]),
            no_pickup_penalty=float(os.environ["NO_PICKUP_PENALTY"]),
            undercube_penalty=float(os.environ["UNDERCUBE_PENALTY"]),
            undercube_margin=0.0,
            enable_undercube_check=os.environ["ENABLE_UNDERCUBE_CHECK"] == "1",
        )
