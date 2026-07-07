"""Headless optimization entry point.

Run directly (``python optimize.py``) or via the dashboard's Run button.
Test selection/weights come from the OPT_* environment when the dashboard
set them; a bare CLI run uses the catalog's default-selected tests.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parent
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

# Avoid leaking host Python runtime settings into SofaPython3 child processes.
for _key in (
    "PYTHONHOME",
    "PYTHONSTARTUP",
    "PYTHONUSERBASE",
    "PYTHONEXECUTABLE",
    "__PYVENV_LAUNCHER__",
):
    os.environ.pop(_key, None)

from sofaopt import run_optimization
from sofaopt.core import envkeys
from sofaopt.core.runconfig import RunConfig

from sofaopt_project import PROJECT


def _default_config() -> RunConfig:
    """Selection from the environment when set, else the default-selected tests."""
    if os.environ.get(envkeys.SELECTED_TESTS, "").strip():
        return RunConfig.from_env(PROJECT)
    defaults = [t.name for t in PROJECT.tests if t.default_selected]
    return RunConfig.from_project(PROJECT, selected_names=defaults or None)


if __name__ == "__main__":
    run_optimization(PROJECT, _default_config())
