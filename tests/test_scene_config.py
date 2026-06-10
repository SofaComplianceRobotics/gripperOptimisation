"""Unit tests for labtests/core/scene_config.py — env resolution with defaults.

Scenes must build a full PlaybackConfig with NO env vars set (standalone
launch), and every value forwarded by an env var must override its default.
Uses pytest's monkeypatch fixture: setenv/delenv changes are automatically
undone after each test, so tests can't leak environment into each other.
"""

from pathlib import Path

import pytest

from labtests.core import scene_defaults as defaults
from labtests.core.scene_config import OptunaMeta, PlaybackConfig
from names import GRIPPER_COLLISION_STL

LAB_ROOT = Path(__file__).resolve().parents[1]

ENV_VARS = (
    "SHAPEOPT_FRICTION_COEF",
    "EARLY_STOP_SIM_TIME",
    "FLOOR_Y_THRESHOLD",
    "FLOOR_Y_BUFFER",
    "PICKUP_Y_THRESHOLD",
    "DROP_PENALTY",
    "OVERLOAD_MAX_TIME",
    "CUBE_MASS_START",
    "CUBE_MASS_MAX",
    "CUBE_MASS_RAMP_TIME",
    "EARLY_CONTACT_PENALTY",
    "NO_PICKUP_PENALTY",
    "UNDERCUBE_PENALTY",
    "ENABLE_UNDERCUBE_CHECK",
    "OPTUNA_STL_PATH",
    "OPTUNA_TRIAL_STATE_PATH",
)


@pytest.fixture
def clean_env(monkeypatch):
    """Remove all scene-related env vars for the duration of one test."""
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    return monkeypatch


class TestPlaybackConfigDefaults:
    def test_builds_without_any_env_vars(self, clean_env):
        cfg = PlaybackConfig.from_env(LAB_ROOT)
        assert cfg.friction_coef == defaults.FRICTION_COEF
        assert cfg.cube_mass_start == defaults.CUBE_MASS_START
        assert cfg.cube_mass_max == defaults.CUBE_MASS_MAX
        assert cfg.drop_penalty == defaults.DROP_PENALTY
        assert cfg.enable_undercube_check is defaults.ENABLE_UNDERCUBE_CHECK
        assert cfg.floor_center_y == defaults.FLOOR_CENTER_Y

    def test_default_mesh_path_uses_name_contract(self, clean_env):
        cfg = PlaybackConfig.from_env(LAB_ROOT)
        assert cfg.gripper_mesh_path.endswith(GRIPPER_COLLISION_STL)

    def test_optuna_meta_defaults_to_no_trial(self, clean_env):
        meta = OptunaMeta.from_env()
        assert meta.trial_state_path is None
        assert meta.run_info == {"gen": 0, "trial": 0, "run": 0}


class TestPlaybackConfigOverrides:
    def test_float_env_var_overrides_default(self, clean_env):
        clean_env.setenv("CUBE_MASS_MAX", "2.5")
        cfg = PlaybackConfig.from_env(LAB_ROOT)
        assert cfg.cube_mass_max == 2.5
        # Untouched values still come from defaults.
        assert cfg.cube_mass_start == defaults.CUBE_MASS_START

    def test_friction_override(self, clean_env):
        clean_env.setenv("SHAPEOPT_FRICTION_COEF", "0.9")
        assert PlaybackConfig.from_env(LAB_ROOT).friction_coef == 0.9

    def test_bool_env_var_overrides_default(self, clean_env):
        clean_env.setenv("ENABLE_UNDERCUBE_CHECK", "1")
        assert PlaybackConfig.from_env(LAB_ROOT).enable_undercube_check is True
        clean_env.setenv("ENABLE_UNDERCUBE_CHECK", "0")
        assert PlaybackConfig.from_env(LAB_ROOT).enable_undercube_check is False

    def test_stl_path_override(self, clean_env):
        clean_env.setenv("OPTUNA_STL_PATH", r"C:\somewhere\trial_7_collision.stl")
        cfg = PlaybackConfig.from_env(LAB_ROOT)
        assert cfg.gripper_mesh_path == r"C:\somewhere\trial_7_collision.stl"

    def test_optuna_meta_reads_trial_identity(self, clean_env):
        clean_env.setenv("OPTUNA_TRIAL_STATE_PATH", r"C:\state.json")
        clean_env.setenv("OPTUNA_RUN_SLOT", "2")
        clean_env.setenv("OPTUNA_GEN", "5")
        clean_env.setenv("OPTUNA_TRIAL", "13")
        clean_env.setenv("OPTUNA_RUN", "1")
        meta = OptunaMeta.from_env()
        assert meta.trial_state_path == r"C:\state.json"
        assert meta.run_slot == 2
        assert meta.run_info == {"gen": 5, "trial": 13, "run": 1}


def test_early_stop_default_scales_with_dt():
    from geometry.timing_config import DT_DIRECT

    assert defaults.EARLY_STOP_SIM_TIME == 2.0 * (DT_DIRECT / 0.02)