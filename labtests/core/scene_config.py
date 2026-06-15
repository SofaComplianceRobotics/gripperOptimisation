"""Shared configuration objects for all ShapeOPT scenes.

Scenes are stateless: a fresh SOFA process builds its full config at startup
from labtests/core/scene_defaults.py, with optional per-process overrides
through environment variables (set by the optimizer for trial metadata, or
by hand for one-off experiments). This module centralises that resolution so
each scene file only needs one call to get a fully populated config object.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from labtests.core import scene_defaults as defaults
from names import CENTERPARTS_DIRNAME, GRIPPER_COLLISION_STL


def _env_float(name: str, default: float) -> float:
    """Read a float env var, falling back to the given default."""
    raw = os.environ.get(name)
    return default if raw is None else float(raw)


def _env_bool(name: str, default: bool) -> bool:
    """Read a "1"/"0" env var, falling back to the given default."""
    raw = os.environ.get(name)
    return default if raw is None else raw == "1"


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
    playback_time_scale: float
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
                    / CENTERPARTS_DIRNAME
                    / GRIPPER_COLLISION_STL
                ),
            ),
            friction_coef=_env_float("SHAPEOPT_FRICTION_COEF", defaults.FRICTION_COEF),
            playback_time_scale=_env_float(
                "PLAYBACK_TIME_SCALE", defaults.PLAYBACK_TIME_SCALE
            ),
            floor_center_y=defaults.FLOOR_CENTER_Y,
            cube_spawn_clearance=defaults.CUBE_SPAWN_CLEARANCE,
            cube_spawn_time=defaults.CUBE_SPAWN_TIME,
            cube_prespawn_offset=defaults.CUBE_PRESPAWN_OFFSET,
            drop_below_spawn_tol=defaults.DROP_BELOW_SPAWN_TOL,
            pickup_above_spawn_tol=defaults.PICKUP_ABOVE_SPAWN_TOL,
            early_stop_sim_time=_env_float(
                "EARLY_STOP_SIM_TIME", defaults.EARLY_STOP_SIM_TIME
            ),
            floor_y_threshold=_env_float(
                "FLOOR_Y_THRESHOLD", defaults.FLOOR_Y_THRESHOLD
            ),
            floor_y_buffer=_env_float("FLOOR_Y_BUFFER", defaults.FLOOR_Y_BUFFER),
            pickup_y_threshold=_env_float(
                "PICKUP_Y_THRESHOLD", defaults.PICKUP_Y_THRESHOLD
            ),
            drop_penalty=_env_float("DROP_PENALTY", defaults.DROP_PENALTY),
            overload_max_time=_env_float(
                "OVERLOAD_MAX_TIME", defaults.OVERLOAD_MAX_TIME
            ),
            cube_mass_start=_env_float("CUBE_MASS_START", defaults.CUBE_MASS_START),
            cube_mass_max=_env_float("CUBE_MASS_MAX", defaults.CUBE_MASS_MAX),
            cube_mass_ramp_time=_env_float(
                "CUBE_MASS_RAMP_TIME", defaults.CUBE_MASS_RAMP_TIME
            ),
            early_contact_stop_time=defaults.EARLY_CONTACT_STOP_TIME,
            early_contact_penalty=_env_float(
                "EARLY_CONTACT_PENALTY", defaults.EARLY_CONTACT_PENALTY
            ),
            no_pickup_penalty=_env_float(
                "NO_PICKUP_PENALTY", defaults.NO_PICKUP_PENALTY
            ),
            undercube_penalty=_env_float(
                "UNDERCUBE_PENALTY", defaults.UNDERCUBE_PENALTY
            ),
            undercube_margin=defaults.UNDERCUBE_MARGIN,
            enable_undercube_check=_env_bool(
                "ENABLE_UNDERCUBE_CHECK", defaults.ENABLE_UNDERCUBE_CHECK
            ),
        )
