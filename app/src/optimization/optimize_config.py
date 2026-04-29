"""
optimize_config.py — Configuration, constants, and environment setup for gripper optimization.

Centralizes all hardcoded defaults, paths, and tuning parameters to minimize
configuration scatter across the codebase.
"""

import dataclasses
import json
import os
import sys
from pathlib import Path

# Setup sys.path BEFORE importing from core
SCRIPT_DIR = Path(__file__).resolve().parent
SRC_ROOT = SCRIPT_DIR.parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from core.params import ModelParams
from labtests.registry import get_default_test_names, get_test_spec, parse_test_names

# ─────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────
APP_ROOT = SRC_ROOT.parent
LAB_ROOT = APP_ROOT.parent

BASE_PARAMS = ModelParams()
ASSETS_ROOT = str(LAB_ROOT.parent.parent)
GENERATE_SCRIPT = str(APP_ROOT / "src" / "generation" / "generate_gripper.py")

SELECTED_TEST_NAMES = parse_test_names(os.environ.get("LAB_SHAPEOPT_TESTS"))
if not SELECTED_TEST_NAMES:
    SELECTED_TEST_NAMES = get_default_test_names()

SELECTED_TEST_SPECS = tuple(get_test_spec(name) for name in SELECTED_TEST_NAMES)
RUN_PLAN: tuple[tuple[str, int, int], ...] = tuple(
    (spec.name, run_index, spec.run_count)
    for spec in SELECTED_TEST_SPECS
    for run_index in range(1, spec.run_count + 1)
)


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
CENTERPARTS_DIR = LAB_ROOT.parent.parent / "data" / "meshes" / "centerparts"

# ─────────────────────────────────────────────
# SOFA Runtime Configuration
# ─────────────────────────────────────────────
SOFA_ROOT = os.environ.get(
    "SOFA_ROOT", r"C:\Users\Cesar\AppData\Local\Programs\emio-labs\resources\sofa"
)
SOFA_PYTHON_PATH = os.environ.get(
    "SOFA_PYTHON_PATH", r"C:\Users\Cesar\AppData\Local\Programs\Python\Python310"
)
RUNSOFA_EXE = os.environ.get("RUNSOFA_EXE", "")
if not RUNSOFA_EXE:
    runsofa_candidates = [
        os.path.join(SOFA_ROOT, "bin", "runSofa.exe"),
        os.path.join(SOFA_ROOT, "bin", "Release", "runSofa.exe"),
        os.path.join(SOFA_ROOT, "bin", "RelWithDebInfo", "runSofa.exe"),
        os.path.join(SOFA_ROOT, "build", "bin", "Release", "runSofa.exe"),
    ]
    RUNSOFA_EXE = next(
        (p for p in runsofa_candidates if os.path.isfile(p)), runsofa_candidates[0]
    )


# ─────────────────────────────────────────────
# CMA-ES Optimizer Settings
# ─────────────────────────────────────────────
N_PARALLEL = 10  # number of parallel SOFA instances (and thus trials) per generation
if N_PARALLEL < 4:
    raise ValueError("N_PARALLEL must be at least 4 for CMA-ES to remain valid.")
N_REPEATS = len(RUN_PLAN)
N_GENERATIONS = 400  # how many CMA-ES generations to run
# total trials = N_GENERATIONS * N_PARALLEL

HEADLESS = True
SOFA_GUI = os.environ.get("SOFA_GUI", "").strip().lower()

STL_DELETE_DELAY = 30  # seconds after SOFA launch before deleting collision STL
PRINT_CLEANUP_LOGS = False  # avoid interleaving with live progress bar output
GEN_PROGRESS_POLL_INTERVAL = 0.25  # seconds between frame-progress writes
GEOMETRY_EXPORT_TIMEOUT = float(
    os.environ.get("GEOMETRY_EXPORT_TIMEOUT", "20")
)  # seconds before generate_gripper.py is considered stuck
MAX_ACTIVE_SOFA_PROCS = int(
    os.environ.get("MAX_ACTIVE_SOFA_PROCS", "12")
)  # throttle to avoid starving geometry export
CMAES_STARTUP_TRIALS = int(
    os.environ.get("CMAES_STARTUP_TRIALS", "50")
)  # random warm-up before CMA-ES adaptation
CMAES_SIGMA0 = float(
    os.environ.get("CMAES_SIGMA0", "0.5")
)  # initial global step size (exploration pressure)
HARD_FAIL_SCORE = float(
    os.environ.get("HARD_FAIL_SCORE", "-3.0")
)  # generation-failure score
# ─────────────────────────────────────────────
# Tunable Parameter Specifications
#
# Direct ModelParams fields carry their optimization range as field metadata
# in core/params.py.  The helper below reads that metadata automatically.
# To add or change a directly-mapped optimisable parameter, only edit
# ModelParams in core/params.py:
#   • set  metadata={"opt": {"type": "float", "min": X, "max": Y}}  to enable
#   • set  metadata={"opt": {"type": "float", "min": 0, "max": 0}}   to freeze
#
# Synthetic parameters (polar Bézier handles) have no corresponding
# ModelParams field and are listed explicitly below.
#
# Fixed / frozen convention: min = 0 AND max = 0 means the optimizer never
# suggests a new value; the field default is used verbatim every trial.
# ─────────────────────────────────────────────


def _param_specs_from_metadata(base: ModelParams) -> list[dict]:
    """Build param spec entries for all ModelParams fields annotated with opt metadata."""
    specs = []
    for f in dataclasses.fields(base):
        opt = f.metadata.get("opt")
        if opt is None:
            continue
        specs.append(
            {
                "name": f.name,
                "type": opt["type"],
                "min": opt["min"],
                "max": opt["max"],
                "default": getattr(base, f.name),
            }
        )
    return specs


PARAM_SPECS: list[dict] = [
    # fmt: off
    # ── Fields annotated in ModelParams (auto-generated from metadata) ──────────
    *_param_specs_from_metadata(BASE_PARAMS),
    # ── Spline first handle (anchor fixed at 0, 0) ──────────────────────────────
    {"name": "p0_hout_dist",              "type": "float", "min": 0.0,   "max": 80.0,  "default": 0.0},
    {"name": "p0_hout_angle_deg",         "type": "float", "min": -90.0, "max": 90.0,  "default": 0.0},
    # ── Spline endpoint ──────────────────────────────────────────────────────────
    {"name": "p1_dist",                   "type": "float", "min": 80.0,  "max": 110.0,  "default": 90.0},
    {"name": "p1_angle_deg",              "type": "float", "min": -90.0, "max": 45.0,  "default": -40.0},
    # ── Spline last handle ───────────────────────────────────────────────────────
    {"name": "p1_hin_dist",               "type": "float", "min": 0.0,   "max": 80.0,  "default": 0.0},
    {"name": "p1_hin_angle_deg",          "type": "float", "min": -10.0, "max": 260.0, "default": 0.0},
    # fmt: on
]

# ─────────────────────────────────────────────
# Simulation Scoring & Early Stop Parameters
# ─────────────────────────────────────────────
EARLY_STOP_SIM_TIME = (
    1.0  # seconds of sim time before checking if cube is still on floor
)
FLOOR_Y_THRESHOLD = -235.0  # cube Y below this = on the floor / never picked up
FLOOR_Y_BUFFER = 5.0  # how far above threshold counts as "still on floor"
PICKUP_Y_THRESHOLD = -215.0  # cube Y above this = considered picked up
DROP_PENALTY = (
    50.0  # score to assign if cube is dropped after being picked up at least once
)

OVERLOAD_MAX_TIME = 5.0  # seconds of post-recording overload simulation
CUBE_MASS_START = 0.005  # kg, should match scene cube initial mass
CUBE_MASS_MAX = 1.0  # kg reached by the end of the overload ramp
CUBE_MASS_RAMP_TIME = 8.0  # seconds to ramp from start mass to max mass

ENABLE_UNDERCUBE_CHECK = (
    False  # if False, skip the under-cube invalid-geometry malus rule
)
SHAPEOPT_FRICTION_COEF = float(
    os.environ.get("SHAPEOPT_FRICTION_COEF", "0.6")
)  # passed to scene contact manager (mu)
EARLY_CONTACT_PENALTY = float(os.environ.get("EARLY_CONTACT_PENALTY", "-1.0"))
NO_PICKUP_PENALTY = float(os.environ.get("NO_PICKUP_PENALTY", "0.0"))
UNDERCUBE_PENALTY = float(os.environ.get("UNDERCUBE_PENALTY", "-0.2"))
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

    sofa_site_packages = os.environ.get(
        "SOFA_SITE_PACKAGES", os.path.join(SOFA_ROOT, "lib", "python3", "site-packages")
    )

    # Critical: do not inherit parent PYTHONPATH (often a Python 3.10 env from
    # EmioLabs launcher). SofaPython3 in custom builds can run a different Python
    # version and must use its own site-packages to avoid startup crashes.
    env["PYTHONPATH"] = ";".join(
        [
            sofa_site_packages,
            os.path.join(SOFA_ROOT, "plugins", "STLIB"),
            ASSETS_ROOT,
        ]
    )

    # Early stop parameters — read by lab_shapeOPT.py via os.environ.get()
    env["EARLY_STOP_SIM_TIME"] = str(EARLY_STOP_SIM_TIME)
    env["FLOOR_Y_THRESHOLD"] = str(FLOOR_Y_THRESHOLD)
    env["FLOOR_Y_BUFFER"] = str(FLOOR_Y_BUFFER)
    env["PICKUP_Y_THRESHOLD"] = str(PICKUP_Y_THRESHOLD)
    env["DROP_PENALTY"] = str(DROP_PENALTY)
    env["OVERLOAD_MAX_TIME"] = str(OVERLOAD_MAX_TIME)
    env["CUBE_MASS_START"] = str(CUBE_MASS_START)
    env["CUBE_MASS_MAX"] = str(CUBE_MASS_MAX)
    env["CUBE_MASS_RAMP_TIME"] = str(CUBE_MASS_RAMP_TIME)
    env["ENABLE_UNDERCUBE_CHECK"] = "1" if ENABLE_UNDERCUBE_CHECK else "0"
    env["EARLY_CONTACT_PENALTY"] = str(EARLY_CONTACT_PENALTY)
    env["NO_PICKUP_PENALTY"] = str(NO_PICKUP_PENALTY)
    env["UNDERCUBE_PENALTY"] = str(UNDERCUBE_PENALTY)
    env["SHAPEOPT_FRICTION_COEF"] = str(SHAPEOPT_FRICTION_COEF)
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
    return env
