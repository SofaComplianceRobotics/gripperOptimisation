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
from sofaopt import (
    ParamSpec,
    SofaOptProject,
    TestSpec,
    TrialPrep,
    param_specs_from_dataclass,
)

from geometry.leg_params import LegParams
from geometry.params import ModelParams
from labtests.registry import get_test_catalog
from launcher.bootstrap import resolve_sofa_runtime
from names import (
    CENTERPARTS_DIRNAME,
    GRIPPER_COLLISION_FINGER_STLS,
    GRIPPER_NAME,
    LEGS_DIRNAME,
)

ASSETS_ROOT = LAB_ROOT.parent.parent
CENTERPARTS_DIR = ASSETS_ROOT / "data" / "meshes" / CENTERPARTS_DIRNAME
LEGS_DIR = ASSETS_ROOT / "data" / "meshes" / LEGS_DIRNAME
GENERATE_SCRIPT = LAB_ROOT / "generation" / "generate_gripper.py"
GENERATE_LEG_SCRIPT = LAB_ROOT / "generation" / "generate_leg.py"
TRIAL_RECORDER_SCENE = LAB_ROOT / "manual_scenes" / "lab_shapeOPT_trial_recorder.py"

GEOMETRY_EXPORT_TIMEOUT = 60.0  # seconds before generate_gripper.py is considered stuck
RECORDING_TIMEOUT = 60.0  # seconds before the trial recording pass is considered stuck

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
    else:
        # SOFA's native init resolves the user/data directories (e.g.
        # sofa::helper::Utils::getUserHomeDirectory) via these Windows env
        # vars before any Python code runs. Without them the process segfaults
        # during startup — this env is otherwise built from scratch (see
        # PYTHONPATH below), so they must be carried over explicitly rather
        # than assumed present.
        for _key in (
            "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA",
            "TEMP", "TMP", "SystemRoot", "SystemDrive", "ComSpec",
        ):
            _val = os.environ.get(_key)
            if _val:
                env[_key] = _val

    # Do not inherit the parent PYTHONPATH (the EmioLabs launcher's own Python
    # env). SofaPython3 must import from its build's site-packages.
    env["PYTHONPATH"] = os.pathsep.join(
        [
            _SOFA["site_packages"],
            os.path.join(sofa_root, "plugins", "STLIB", "lib", "python3", "site-packages"),
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


def _constrain_params(params: dict) -> dict:
    """Apply every params-clamping rule for one trial.

    The leg needs no clamp: its cross-section is fixed at the stock 10x5
    that the gripper pocket was designed for (see geometry/leg_params.py).
    """
    return _constrain_plateaus(params)


def _run_generation_script(
    script: Path, config_path: Path, extra_args: list[str]
) -> None:
    """Run a generation script under the emio-labs bundled Python.

    Never the dashboard's own interpreter — its gmsh/cadquery can differ or
    fail to load. Raises on timeout/failure so sofaopt hard-fails the trial.
    """
    try:
        result = subprocess.run(
            [
                _SOFA["python_exe"],
                str(script),
                "--config",
                str(config_path),
                *extra_args,
            ],
            cwd=str(LAB_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GEOMETRY_EXPORT_TIMEOUT,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"{script.name} timed out after {GEOMETRY_EXPORT_TIMEOUT:.1f}s.\n"
            f"stdout (tail):\n{(e.stdout or '')[-1500:]}\n"
            f"stderr (tail):\n{(e.stderr or '')[-1500:]}"
        ) from e

    if result.returncode != 0:
        raise RuntimeError(
            f"{script.name} failed (returncode={result.returncode}).\n"
            f"stdout (tail):\n{(result.stdout or '')[-2000:]}\n"
            f"stderr (tail):\n{(result.stderr or '')[-2000:]}"
        )


def _prepare_gripper_mesh(
    config_path: Path, trial_dir: Path
) -> tuple[Path, Path, Path]:
    """Turn sampled parameters into a gripper mesh for one trial.

    Stages the outputs:
    - the two per-finger collision STLs stay in CENTERPARTS_DIR under
      trial-unique names so parallel SOFA instances never clash, passed to
      the scene via OPT_MESH_FINGER1/OPT_MESH_FINGER2. Each finger is its own
      collision body so SOFA can detect contact between them (a single merged
      gripper mesh can never register a finger-vs-finger self-contact);
    - a copy of the visual STL goes into the trial dir for the preview render.

    Returns:
        (finger1_collision_stl, finger2_collision_stl, visual_stl_copy) paths.
    """
    _run_generation_script(GENERATE_SCRIPT, config_path, [])

    trial_id = f"{trial_dir.parent.name}_{trial_dir.name}"

    finger_collision_stls = []
    for i, finger_name in enumerate(GRIPPER_COLLISION_FINGER_STLS, start=1):
        finger_src = CENTERPARTS_DIR / finger_name
        if not finger_src.exists():
            raise RuntimeError(f"Finger {i} collision STL not found after generation.")
        finger_stl = CENTERPARTS_DIR / f"gripper_{trial_id}_collision_finger{i}.stl"
        finger_src.replace(finger_stl)
        finger_collision_stls.append(finger_stl)

    visual_src = CENTERPARTS_DIR / f"{GRIPPER_NAME}.stl"
    if not visual_src.exists():
        raise RuntimeError("Visual STL not found after generation.")
    visual_stl_copy = trial_dir / "visual.stl"
    shutil.copy2(visual_src, visual_stl_copy)

    return finger_collision_stls[0], finger_collision_stls[1], visual_stl_copy


def _prepare_leg_mesh(config_path: Path, trial_dir: Path) -> tuple[str, Path, Path]:
    """Turn sampled leg parameters into positions/mesh for one trial.

    The leg files are written directly under LEGS_DIR (where parts.leg.Leg
    looks them up by name) under a trial-unique stem so parallel SOFA
    instances never clash.

    Returns:
        (leg_name, txt_path, stl_path).
    """
    trial_id = f"{trial_dir.parent.name}_{trial_dir.name}"
    leg_name = f"leg_{trial_id}"
    _run_generation_script(GENERATE_LEG_SCRIPT, config_path, ["--name", leg_name])

    txt_path = LEGS_DIR / f"{leg_name}.txt"
    stl_path = LEGS_DIR / f"{leg_name}.stl"
    if not txt_path.exists() or not stl_path.exists():
        raise RuntimeError("Leg positions/STL not found after generation.")

    return leg_name, txt_path, stl_path


def run_trajectory_recorder(output_path: Path, leg_name: str | None = None) -> int:
    """Launch the headless trial-recorder scene, writing to `output_path`.

    Replays the captured reference effector-target path (see
    manual_scenes/lab_shapeOPT_trial_recorder.py) through the inverse solver and
    records the resulting motor angles. Only `leg_name` needs to be passed in
    explicitly: inverse-mode scenes have no collision pipeline, so the
    gripper's own mesh comes from whatever generate_gripper.py already wrote
    to CENTERPARTS_DIR/{GRIPPER_NAME}.stl by the time this launches — the same
    shared-file mechanism every direct-mode test's FEM gripper already relies
    on. `leg_name=None` leaves OPT_LEG_NAME unset, so base_scene.py falls back
    to the stock leg exactly as it does for any other scene.

    Public (no leading underscore): reused by the dashboard's Watch launcher
    (dashboard/callbacks/scenes.py) so a manually-watched test also drives the
    inverse solver with the same leg it's about to test, instead of replaying
    the fixed reference recording.

    Returns:
        Number of recorded motor frames.

    Raises:
        RuntimeError: on timeout or failure to produce a recording.
    """
    env = _scene_env()
    if leg_name:
        env["OPT_LEG_NAME"] = leg_name
    env["OPT_MOTOR_RECORDING_OUT"] = str(output_path)

    cmd = [
        str(_SOFA["runsofa_exe"]),
        "-l", "SofaPython3",
        "-g", "batch",
        str(TRIAL_RECORDER_SCENE),
    ]
    try:
        result = subprocess.run(
            cmd,
            cwd=str(LAB_ROOT),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=RECORDING_TIMEOUT,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"Trial trajectory recording timed out after {RECORDING_TIMEOUT:.1f}s.\n"
            f"stdout (tail):\n{(e.stdout or '')[-1500:]}\n"
            f"stderr (tail):\n{(e.stderr or '')[-1500:]}"
        ) from e

    if not output_path.exists():
        raise RuntimeError(
            f"Trial trajectory recording did not produce a recording "
            f"(returncode={result.returncode}).\n"
            f"stdout (tail):\n{(result.stdout or '')[-2000:]}\n"
            f"stderr (tail):\n{(result.stderr or '')[-2000:]}"
        )

    try:
        return len(json.loads(output_path.read_text(encoding="utf-8"))["motor_positions"])
    except Exception:
        return -1


def _record_trial_trajectory(trial_dir: Path, leg_name: str) -> Path:
    """Record this trial's motor trajectory into trial_dir/motor_recording.json.

    Hard-fails the trial (via run_trajectory_recorder raising) if it doesn't
    finish within RECORDING_TIMEOUT — same treatment as a failed mesh
    generation.
    """
    recording_path = trial_dir / "motor_recording.json"
    frame_count = run_trajectory_recorder(recording_path, leg_name)
    print(
        f"[prepare] {trial_dir.parent.name}/{trial_dir.name}: "
        f"recorded {frame_count} motor frames -> {recording_path}"
    )
    return recording_path


def _render_combined_preview(gripper_stl: Path, leg_stl: Path, out_png: Path) -> None:
    """Render the gripper and the leg side by side into one PNG for one trial.

    sofaopt's own preview pipeline only supports a single image per trial
    (TrialPrep.preview_image), so both parts are composited here rather than
    passed through separately. Best-effort: a render failure just means no
    preview for this trial, not a failed trial (matches how sofaopt's own
    STL-to-PNG rendering treats preview failures).
    """
    import pyvista as pv

    plotter = None
    try:
        plotter = pv.Plotter(off_screen=True, shape=(1, 2), window_size=(1600, 600))
        for col, (title, stl_path) in enumerate(
            (("Gripper", gripper_stl), ("Leg", leg_stl))
        ):
            plotter.subplot(0, col)
            mesh = pv.read(str(stl_path))
            plotter.add_mesh(
                mesh, color="#4a90d9", pbr=True, metallic=0.1, roughness=0.4
            )
            plotter.add_light(pv.Light(position=(200, 200, 400), intensity=0.8))
            plotter.add_text(title, font_size=14)
            plotter.background_color = "white"
            # Head-on instead of pyvista's default isometric angle: view
            # straight down the x axis with y (height) held vertical.
            plotter.enable_parallel_projection()
            center = mesh.center
            plotter.camera_position = [
                (center[0] + 1.0, center[1], center[2]),
                center,
                (0, 1, 0),
            ]
            plotter.reset_camera()
        plotter.screenshot(str(out_png))
    except Exception as e:
        print(f"[warn] Combined preview render failed: {e}")
    finally:
        if plotter is not None:
            plotter.close()


def _prepare_trial(params: dict, trial_dir: Path) -> TrialPrep:
    """Turn one trial's sampled parameters into a gripper mesh and a leg
    mesh, both feeding the same existing test scenes (grasp-hold, random
    cube pick, gripper tilt) — the legs plug into the gripper's leg
    attachments there, so leg shape affects those scores without any
    leg-specific test being added.
    """
    config_path = trial_dir / "params.json"  # already written by sofaopt's prepare_trial

    finger1_stl, finger2_stl, visual_stl_copy = _prepare_gripper_mesh(
        config_path, trial_dir
    )
    leg_name, leg_txt, leg_stl = _prepare_leg_mesh(config_path, trial_dir)
    recording_path = _record_trial_trajectory(trial_dir, leg_name)

    combined_preview = trial_dir / "preview_combined.png"
    _render_combined_preview(visual_stl_copy, leg_stl, combined_preview)
    preview_image = combined_preview if combined_preview.exists() else visual_stl_copy

    return TrialPrep(
        env={
            "OPT_MESH_FINGER1": str(finger1_stl),
            "OPT_MESH_FINGER2": str(finger2_stl),
            "OPT_LEG_NAME": leg_name,
            "OPT_MOTOR_RECORDING": str(recording_path),
        },
        cleanup=[
            finger1_stl,
            finger2_stl,
            visual_stl_copy,
            leg_txt,
            leg_stl,
            combined_preview,
            recording_path,
        ],
        preview_image=preview_image,
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


def _selected_param_names() -> set[str] | None:
    selection_path = LAB_ROOT / "config" / "lab_config.optimization.json"
    if not selection_path.exists():
        return None
    try:
        data = json.loads(selection_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(data, list):
        return {str(name) for name in data}
    if isinstance(data, dict):
        raw = data.get("optimized_params", [])
        if isinstance(raw, list):
            return {str(name) for name in raw}
    return None


def _param_specs(instance, selected: set[str] | None) -> list[ParamSpec]:
    """Build the ParamSpec list for one params dataclass, freezing the rest.

    sofaopt's param_specs_from_dataclass reads each field's [min, max] from its
    "opt" metadata. On top of that, every param not listed in
    config/lab_config.optimization.json is held at its current value
    (low == high), which sofaopt treats as frozen: it still reaches the scene
    but is never searched. selected=None searches everything with opt metadata.
    Bool params are always left searchable.
    """
    specs = param_specs_from_dataclass(instance)
    if selected is None:
        return specs
    return [
        s
        if s.type == "bool" or s.name in selected
        else ParamSpec(s.name, s.type, s.default, s.default, s.default)
        for s in specs
    ]


_SELECTED_PARAM_NAMES = _selected_param_names()


PROJECT = SofaOptProject(
    name="lab_shapeOPT",
    work_dir=LAB_ROOT,
    params=_param_specs(ModelParams(), _SELECTED_PARAM_NAMES)
    + _param_specs(LegParams(), _SELECTED_PARAM_NAMES),
    tests=_tests_from_registry(),
    runsofa_exe=Path(_SOFA["runsofa_exe"]),
    sofa_env=_scene_env(),
    gui_mode="batch",
    float_step=0.1,
    prepare_trial=_prepare_trial,
    constrain_params=_constrain_params,
    n_parallel=5,
    n_generations=400,
    cmaes_sigma0=0.3,  # concentrate around the seeded gripper (normalized space)
    cmaes_startup_trials=10,
    hard_fail_score=float(os.environ.get("HARD_FAIL_SCORE", "-3.0")),
    max_active_sofa_procs=12,
    sofa_realtime_timeout=200.0,
    # prepare_trial now runs three sequential subprocesses (gripper gen, leg
    # gen, trial trajectory recording), each individually bounded by its own
    # timeout, so the outer sofaopt-level budget must cover all three.
    prepare_timeout=2 * GEOMETRY_EXPORT_TIMEOUT + RECORDING_TIMEOUT,
    run_script=LAB_ROOT / "optimize.py",
    run_python_exe=Path(_SOFA["python_exe"]) if _SOFA["python_exe"] else None,
    config_file=LAB_ROOT / "config" / "lab_config.jsonc",
    title="Lab ShapeOPT",
    failed_preview_image=_failed_preview_image(),
)
