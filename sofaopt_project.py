"""The lab's sofaopt project definition.

This is the single adapter between lab_shapeOPT and the sofaopt framework:
it declares what to tune (gripper parameters), what to run (the labtests
catalog), how to reach the emio-labs SOFA build, and how to turn sampled
parameters into a gripper mesh before each trial (the prepare hook).

Everything downstream — CMA-ES sampling, parallel runSofa scheduling, score
aggregation, gating, the live dashboard — is provided by sofaopt.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parent
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

import sofaopt
from sofaopt import SofaOptProject, TestSpec, TrialPrep, param_specs_from_dataclass

from geometry.params import ModelParams
from labtests.registry import get_test_catalog
from launcher.bootstrap import resolve_sofa_runtime
from names import CENTERPARTS_DIRNAME, GRIPPER_COLLISION_STL, GRIPPER_NAME

ASSETS_ROOT = LAB_ROOT.parent.parent
CENTERPARTS_DIR = ASSETS_ROOT / "data" / "meshes" / CENTERPARTS_DIRNAME
GENERATE_SCRIPT = LAB_ROOT / "generation" / "generate_gripper.py"

GEOMETRY_EXPORT_TIMEOUT = 20.0  # seconds before generate_gripper.py is considered stuck

_SOFA = resolve_sofa_runtime()

# The sofaopt package location, so scene subprocesses (running inside
# runSofa's SofaPython3, not the bundled Python) can import sofaopt.scene.
_SOFAOPT_PATH = Path(sofaopt.__file__).resolve().parents[1]


def _scene_env() -> dict[str, str]:
    """Environment for SOFA scene subprocesses.

    Built explicitly rather than inherited: the dashboard may run under a
    foreign Python whose PATH/PYTHONPATH would crash SofaPython3 on startup
    (ABI mismatch), so every entry points at the one emio-labs build.
    """
    sofa_root = _SOFA["sofa_root"]

    env: dict[str, str] = {
        "SOFA_ROOT": sofa_root,
        "SOFAPYTHON3_ROOT": sofa_root,
    }

    path_chunks = [
        os.path.join(sofa_root, "bin", "Release"),
        os.path.join(sofa_root, "bin", "RelWithDebInfo"),
        os.path.join(sofa_root, "bin"),
        os.path.join(sofa_root, "lib"),
        _SOFA["python_dir"],
        os.environ.get("PATH", ""),
    ]
    env["PATH"] = os.pathsep.join(p for p in path_chunks if p)

    # On Linux the dynamic loader uses LD_LIBRARY_PATH, not PATH, to find the
    # SOFA shared objects and their dependencies.
    if os.name != "nt":
        ld_chunks = [
            os.path.join(sofa_root, "lib"),
            os.path.join(sofa_root, "bin"),
            os.environ.get("LD_LIBRARY_PATH", ""),
        ]
        env["LD_LIBRARY_PATH"] = os.pathsep.join(p for p in ld_chunks if p)

    # Do not inherit the parent PYTHONPATH (the EmioLabs launcher's own Python
    # env). SofaPython3 must import from its build's site-packages.
    env["PYTHONPATH"] = os.pathsep.join(
        [
            _SOFA["site_packages"],
            os.path.join(sofa_root, "plugins", "STLIB"),
            str(ASSETS_ROOT),
            str(_SOFAOPT_PATH),
        ]
    )
    return env


def _constrain_plateaus(params: dict) -> dict:
    """Keep the three cylinder plateaus inside the 45° budget.

    Plateau C may use only whatever angle A and B leave available; the value
    the optimizer recorded is untouched, only the value used for generation.
    """
    if "cylinder_plateau_C_deg" in params:
        max_c = max(
            0.0,
            45.0
            - max(
                params.get("cylinder_plateau_A_deg", 0.0),
                params.get("cylinder_plateau_B_deg", 0.0),
            ),
        )
        params["cylinder_plateau_C_deg"] = round(
            min(params["cylinder_plateau_C_deg"], max_c), 3
        )
    return params


def _prepare_gripper_trial(params: dict, trial_dir: Path) -> TrialPrep:
    """Turn sampled parameters into a gripper mesh for one trial.

    Writes the full config, runs generate_gripper.py under the emio-labs
    bundled Python (never the dashboard's own interpreter — its gmsh/cadquery
    can differ or fail to load), and stages the outputs:

    - the collision STL stays in CENTERPARTS_DIR under a trial-unique name so
      parallel SOFA instances never clash, passed to the scene via OPT_MESH;
    - a copy of the visual STL goes into the trial dir for the preview render.

    Raises on generator timeout/failure — sofaopt hard-fails the trial.
    """
    config_path = trial_dir / "lab_config.jsonc"
    config_path.write_text(json.dumps(params, indent=2), encoding="utf-8")

    try:
        result = subprocess.run(
            [_SOFA["python_exe"], str(GENERATE_SCRIPT), "--config", str(config_path)],
            cwd=str(LAB_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GEOMETRY_EXPORT_TIMEOUT,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"generate_gripper.py timed out after {GEOMETRY_EXPORT_TIMEOUT:.1f}s.\n"
            f"stdout (tail):\n{(e.stdout or '')[-1500:]}\n"
            f"stderr (tail):\n{(e.stderr or '')[-1500:]}"
        ) from e

    if result.returncode != 0:
        raise RuntimeError(
            f"generate_gripper.py failed (returncode={result.returncode}).\n"
            f"stdout (tail):\n{(result.stdout or '')[-2000:]}\n"
            f"stderr (tail):\n{(result.stderr or '')[-2000:]}"
        )

    trial_id = f"{trial_dir.parent.name}_{trial_dir.name}"

    collision_src = CENTERPARTS_DIR / GRIPPER_COLLISION_STL
    if not collision_src.exists():
        raise RuntimeError("Collision STL not found after generation.")
    collision_stl = CENTERPARTS_DIR / f"gripper_{trial_id}_collision.stl"
    collision_src.replace(collision_stl)

    visual_src = CENTERPARTS_DIR / f"{GRIPPER_NAME}.stl"
    if not visual_src.exists():
        raise RuntimeError("Visual STL not found after generation.")
    visual_stl_copy = trial_dir / "visual.stl"
    shutil.copy2(visual_src, visual_stl_copy)

    return TrialPrep(
        env={"OPT_MESH": str(collision_stl)},
        cleanup=[collision_stl, visual_stl_copy],
        preview_image=visual_stl_copy,
    )


def _tests_from_registry() -> list[TestSpec]:
    """Map the labtests catalog onto sofaopt test specs."""
    return [
        TestSpec(
            name=spec.name,
            scene_file=spec.scene_file,
            label=spec.label,
            description=spec.description,
            run_count=spec.run_count,
            max_score=spec.max_score,
            score_aggregation=spec.score_aggregation,
            default_selected=spec.default_selected,
        )
        for spec in get_test_catalog().values()
    ]


def _failed_preview_image() -> Path | None:
    for candidate in (
        LAB_ROOT / "failed_generations.png",
        LAB_ROOT / "failed_generation.png",
    ):
        if candidate.exists():
            return candidate
    return None


PROJECT = SofaOptProject(
    name="lab_shapeOPT",
    work_dir=LAB_ROOT,
    params=param_specs_from_dataclass(ModelParams()),
    tests=_tests_from_registry(),
    runsofa_exe=Path(_SOFA["runsofa_exe"]),
    sofa_env=_scene_env(),
    gui_mode="batch",
    float_step=0.1,
    prepare_trial=_prepare_gripper_trial,
    constrain_params=_constrain_plateaus,
    n_parallel=5,
    n_generations=400,
    cmaes_sigma0=0.3,  # concentrate around the seeded gripper (normalized space)
    cmaes_startup_trials=10,
    hard_fail_score=float(os.environ.get("HARD_FAIL_SCORE", "-3.0")),
    max_active_sofa_procs=12,
    sofa_realtime_timeout=200.0,
    prepare_timeout=GEOMETRY_EXPORT_TIMEOUT,
    stl_delete_delay=30.0,
    run_script=LAB_ROOT / "optimize.py",
    run_python_exe=Path(_SOFA["python_exe"]) if _SOFA["python_exe"] else None,
    config_file=LAB_ROOT / "config" / "lab_config.jsonc",
    title="Lab ShapeOPT",
    failed_preview_image=_failed_preview_image(),
)
