"""Shared pytest setup for all lab_shapeOPT tests.

pytest imports this file before any test module. Three jobs:

1. Put the lab root on sys.path so `import geometry.params` etc. resolve
   when pytest is run from anywhere.
2. Provide dummy values for the env vars that optimization/config.py
   requires at import time. Unit tests never launch SOFA, so the values
   only need to exist, not point anywhere real.
3. Register a stub `cadquery` module: geometry/transforms/quaternion.py
   imports cadquery but only uses it as a type annotation, and the real
   package targets Python 3.10 which cannot load in this test venv.
"""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

# optimization/config.py reads these with os.environ[...] at module level,
# so they must exist before any test imports it. setdefault keeps real
# values if the shell already has them.
_ENV_DEFAULTS = {
    "SOFA_ROOT": str(LAB_ROOT / "_test_dummy_sofa"),
    "SOFA_PYTHON_PATH": str(LAB_ROOT / "_test_dummy_sofa" / "python"),
    "RUNSOFA_EXE": str(LAB_ROOT / "_test_dummy_sofa" / "runSofa.exe"),
    "SOFA_GUI": "batch",
    "SOFA_SITE_PACKAGES": str(LAB_ROOT / "_test_dummy_sofa" / "site-packages"),
    "HARD_FAIL_SCORE": "0.0",
}
for _key, _value in _ENV_DEFAULTS.items():
    os.environ.setdefault(_key, _value)

# Minimal stand-in for the cadquery package. Only the Workplane attribute
# is needed: quaternion.py references cq.Workplane in a signature.
if "cadquery" not in sys.modules:
    _cadquery_stub = types.ModuleType("cadquery")
    _cadquery_stub.Workplane = object
    sys.modules["cadquery"] = _cadquery_stub
