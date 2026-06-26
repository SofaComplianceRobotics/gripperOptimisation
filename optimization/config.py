"""
config.py — Configuration, constants, and environment setup for gripper optimization.

Centralizes all hardcoded defaults, paths, and tuning parameters to minimize
configuration scatter across the codebase.
"""

import json
import os
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent.parent

from geometry.params import ModelParams, param_specs
from names import CENTERPARTS_DIRNAME
from labtests.registry import get_default_test_names, get_test_spec, parse_test_names

# ─────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────
LAB_ROOT = SRC_ROOT
APP_ROOT = LAB_ROOT

BASE_PARAMS = ModelParams()
ASSETS_ROOT = str(LAB_ROOT.parent.parent)
GENERATE_SCRIPT = str(LAB_ROOT / "generation" / "generate_gripper.py")

SELECTED_TEST_NAMES = parse_test_names(os.environ.get("LAB_SHAPEOPT_TESTS"))
if not SELECTED_TEST_NAMES:
    SELECTED_TEST_NAMES = get_default_test_names()

SELECTED_TEST_SPECS = tuple(get_test_spec(name) for name in SELECTED_TEST_NAMES)
RUN_PLAN: tuple[tuple[str, int, int], ...] = tuple(
    (spec.name, run_index, spec.run_count)
    for spec in SELECTED_TEST_SPECS
    for run_index in range(1, spec.run_count + 1)
)


def _parse_gated_test_names(
    raw: str | None, selected_test_names: list[str]
) -> tuple[str, ...]:
    """Parse LAB_SHAPEOPT_GATED_TESTS into a gated subset of selected tests."""
    if not raw:
        return ()

    selected = set(selected_test_names)
    resolved: list[str] = []
    seen: set[str] = set()
    for part in raw.split(","):
        name = part.strip()
        if not name or name in seen or name not in selected:
            continue
        resolved.append(name)
        seen.add(name)
    return tuple(resolved)


# ─────────────────────────────────────────────
# Per-test weights
# ─────────────────────────────────────────────
def _parse_test_weights(raw: str | None, test_names: list[str]) -> dict[str, float]:
    """Parse LAB_SHAPEOPT_TEST_WEIGHTS into a normalized {test_name: fraction} dict.

    The env var is expected to be a JSON object whose values are integer
    percentages that sum to 100 (as produced by the UI). If the variable is
    absent, malformed, or the keys don't match the selected tests, equal
    weights are used as fallback.

    Args:
        raw: Raw value of LAB_SHAPEOPT_TEST_WEIGHTS.
        test_names: Canonical list of selected test names.

    Returns:
        Mapping of test_name to weight fraction (sums to 1.0).
    """
    n = len(test_names)
    equal = {name: 1.0 / n for name in test_names} if n else {}

    if not raw:
        return equal

    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            return equal
        # Verify all selected tests are present; ignore extra keys.
        if not all(name in parsed for name in test_names):
            return equal
        total = sum(float(parsed[name]) for name in test_names)
        if total <= 0:
            return equal
        return {name: float(parsed[name]) / total for name in test_names}
    except Exception:
        return equal


SELECTED_TEST_WEIGHTS: dict[str, float] = _parse_test_weights(
    os.environ.get("LAB_SHAPEOPT_TEST_WEIGHTS"),
    list(SELECTED_TEST_NAMES),
)

GATED_TEST_NAMES: tuple[str, ...] = _parse_gated_test_names(
    os.environ.get("LAB_SHAPEOPT_GATED_TESTS"),
    list(SELECTED_TEST_NAMES),
)

# Where per-generation/trial working dirs live
TRIALS_DIR = LAB_ROOT / "runtime" / "trials"

# Flat folder containing one preview PNG per trial, easy to scroll through
PREVIEWS_DIR = TRIALS_DIR / "previews"

# Placeholder preview used whenever a trial produces no usable shape.
FAILED_PREVIEW_IMAGE_CANDIDATES: tuple[Path, ...] = (
    LAB_ROOT / "failed_generations.png",
    LAB_ROOT / "failed_generation.png",
)

# Written after every trial so the UI progress bar can poll it
PROGRESS_FILE = TRIALS_DIR / "progress.json"

# Where generate_gripper.py deposits its STL outputs
CENTERPARTS_DIR = LAB_ROOT.parent.parent / "data" / "meshes" / CENTERPARTS_DIRNAME

# ─────────────────────────────────────────────
# SOFA Runtime Configuration
# ─────────────────────────────────────────────
SOFA_ROOT = os.environ["SOFA_ROOT"]
SOFA_PYTHON_PATH = os.environ["SOFA_PYTHON_PATH"]
RUNSOFA_EXE = os.environ["RUNSOFA_EXE"]

# Interpreter for generation/optimization subprocesses. Always the emio-labs
# bundled Python, never sys.executable: a machine may have its own Python on
# PATH that starts the dashboard, and its gmsh/cadquery can differ or fail to
# load. Falls back to the current interpreter only if the bundled one is absent.
import sys as _sys

SOFA_PYTHON_EXE = os.path.join(SOFA_PYTHON_PATH, "python.exe")
if not os.path.isfile(SOFA_PYTHON_EXE):
    SOFA_PYTHON_EXE = _sys.executable


# ─────────────────────────────────────────────
# CMA-ES Optimizer Settings
# ─────────────────────────────────────────────
N_PARALLEL = 5  # number of parallel SOFA instances (and thus trials) per generation
if N_PARALLEL < 4:
    raise ValueError("N_PARALLEL must be at least 4 for CMA-ES to remain valid.")
N_REPEATS = len(RUN_PLAN)
N_GENERATIONS = 400  # how many CMA-ES generations to run
# total trials = N_GENERATIONS * N_PARALLEL

HEADLESS = True
SOFA_GUI = os.environ["SOFA_GUI"].strip().lower()

STL_DELETE_DELAY = 30  # seconds after SOFA launch before deleting collision STL
PRINT_CLEANUP_LOGS = False  # avoid interleaving with live progress bar output
GEN_PROGRESS_POLL_INTERVAL = 0.25  # seconds between frame-progress writes
GEOMETRY_EXPORT_TIMEOUT = 20.0  # seconds before generate_gripper.py is considered stuck
MAX_ACTIVE_SOFA_PROCS = 12  # throttle to avoid starving geometry export
CMAES_STARTUP_TRIALS = 10  # random warm-up before CMA-ES adaptation
CMAES_SIGMA0 = 0.3  # initial global step size (exploration pressure)
HARD_FAIL_SCORE = float(os.environ["HARD_FAIL_SCORE"])  # generation-failure score
# ─────────────────────────────────────────────
# Tunable Parameter Specifications
#
# All optimisable parameters are defined in geometry/params.py via field metadata:
#   • metadata={"opt": {"type": "float", "min": X, "max": Y}}  — active
#   • metadata={"opt": {"type": "float", "min": 0, "max": 0}}  — frozen (default used)
#
# To add, remove, or re-range a parameter: edit ModelParams in geometry/params.py only.
# ─────────────────────────────────────────────
PARAM_SPECS: list[dict] = param_specs(BASE_PARAMS)

# ─────────────────────────────────────────────
# Simulation Runtime Limits
#
# Scene physics and scoring defaults live in labtests/core/scene_defaults.py
# — scenes read them directly; env vars are optional per-process overrides.
# ─────────────────────────────────────────────
SOFA_REALTIME_TIMEOUT = (
    200.0  # wall-clock seconds before any SOFA run prunes the whole gripper
)
# ─────────────────────────────────────────────
# Global State
# ─────────────────────────────────────────────
TRAINING_STARTED_AT = 0.0
SOFA_JOB_HANDLE = None


def build_env() -> dict:
    """Build environment dict with SOFA, Python, and optimization parameters.

    Returns:
        Environment variables dict ready to pass to subprocess calls.
    """
    env = os.environ.copy()

    # Avoid leaking host Python runtime settings into SofaPython3 child processes.
    for key in (
        "PYTHONHOME",
        "PYTHONSTARTUP",
        "PYTHONUSERBASE",
        "PYTHONEXECUTABLE",
        "__PYVENV_LAUNCHER__",
    ):
        env.pop(key, None)

    env["SOFA_ROOT"] = SOFA_ROOT
    env["SOFAPYTHON3_ROOT"] = SOFA_ROOT

    # Build an explicit runtime PATH for SOFA subprocesses (do not rely on
    # inherited launcher ordering, which may point at incompatible runtimes).
    path_chunks = [
        os.path.join(SOFA_ROOT, "bin", "Release"),
        os.path.join(SOFA_ROOT, "bin", "RelWithDebInfo"),
        os.path.join(SOFA_ROOT, "bin"),
        SOFA_PYTHON_PATH,
        env.get("PATH", ""),
    ]
    env["PATH"] = ";".join([p for p in path_chunks if p])

    sofa_site_packages = os.environ["SOFA_SITE_PACKAGES"]

    # Critical: do not inherit the parent PYTHONPATH (the EmioLabs launcher's
    # own Python env). SofaPython3 must import from its build's site-packages
    # to avoid startup crashes, so set PYTHONPATH explicitly here.
    env["PYTHONPATH"] = ";".join(
        [
            sofa_site_packages,
            os.path.join(SOFA_ROOT, "plugins", "STLIB"),
            ASSETS_ROOT,
        ]
    )

    env["LAB_SHAPEOPT_TESTS"] = ",".join(SELECTED_TEST_NAMES)
    env["LAB_SHAPEOPT_RUNS_PER_TRIAL"] = str(N_REPEATS)
    env["LAB_SHAPEOPT_RUN_PLAN"] = ",".join(
        f"{test_name}:{test_run_index}:{test_run_total}"
        for test_name, test_run_index, test_run_total in RUN_PLAN
    )
    env["LAB_SHAPEOPT_TEST"] = SELECTED_TEST_NAMES[0]
    # Forward weights so any child process can reconstruct them if needed.
    env["LAB_SHAPEOPT_TEST_WEIGHTS"] = json.dumps(
        {name: round(frac * 100) for name, frac in SELECTED_TEST_WEIGHTS.items()}
    )
    if GATED_TEST_NAMES:
        env["LAB_SHAPEOPT_GATED_TESTS"] = ",".join(GATED_TEST_NAMES)
    return env
