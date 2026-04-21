"""
optimize.py — Optuna + CMA-ES gripper shape optimizer.

Strategy per generation:
  1. For each trial (serially): generate geometry, copy visual STL, render preview, launch SOFA immediately
  2. Each SOFA instance runs in parallel — launched right after its geometry is ready so it
     reads new_gripper.stl before the next trial's generation overwrites it
  3. Delete collision STL after a delay (it's already loaded by SOFA)
  4. Wait for all SOFA instances to finish, read scores
  5. Write a summary.json with avg/best/worst score for the generation
  6. Write a progress.json with overall progress for the UI progress bar
  7. Report scores → Optuna updates CMA-ES distribution
"""

import os
import sys
import json
import time
import subprocess
import threading
import shutil
import ctypes
import statistics
from ctypes import wintypes
from pathlib import Path

import optuna
import pyvista as pv

# ─────────────────────────────────────────────
# Paths
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

SCRIPT_DIR = Path(__file__).resolve().parent
SRC_ROOT = SCRIPT_DIR.parent
APP_ROOT = SRC_ROOT.parent
LAB_ROOT = APP_ROOT.parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from core.params import ModelParams

BASE_PARAMS = ModelParams()
ASSETS_ROOT = str(LAB_ROOT.parent.parent)
SCENE_FILE = str(LAB_ROOT / "lab_shapeOPT.py")
GENERATE_SCRIPT = str(APP_ROOT / "src" / "generation" / "generate_gripper.py")

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
TRAINING_STARTED_AT = 0.0
SOFA_JOB_HANDLE = None

# Where generate_gripper.py deposits its STL outputs
CENTERPARTS_DIR = LAB_ROOT.parent.parent / "data" / "meshes" / "centerparts"

# ─────────────────────────────────────────────
# Fixed params (not being optimized)
# ─────────────────────────────────────────────
MESH_FIXED = {
    "mesh_size_max": 9,
    "mesh_size_min": 6,
    "mesh_collision_size": 90.0,
    "mesh_angle_smooth": 20.0,
    "mesh_size_from_curvature": 12,
}

RING_FIXED = {
    "cylinder_radius": 26.5,
    "cylinder_height": 4.0,
    "cylinder_hole_thickness": 3.0,
}

# ─────────────────────────────────────────────
# Optimizer settings
# ─────────────────────────────────────────────
N_PARALLEL = 10  # number of parallel SOFA instances (and thus trials) per generation
if N_PARALLEL < 4:
    raise ValueError("N_PARALLEL must be at least 4 for CMA-ES to remain valid.")
N_REPEATS = 1  # number of SOFA runs per trial
N_GENERATIONS = 400  # how many CMA-ES generations to run
# total trials = N_GENERATIONS * N_PARALLEL
# (TODO: add secondary stop condition based on score convergence)
HEADLESS = True
SOFA_GUI = os.environ.get("SOFA_GUI", "").strip().lower()

STL_DELETE_DELAY = 30  # seconds after SOFA launch before deleting collision STL
# (TODO: find a more robust way to know when it's safe to delete)
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
PINCER_ROUND_ENDS = os.environ.get(
    "PINCER_ROUND_ENDS", "1" if BASE_PARAMS.pincer_round_ends else "0"
).strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

# ─────────────────────────────────────────────
# Early stop / scoring thresholds (passed to lab_shapeOPT.py via env vars)
# ─────────────────────────────────────────────
EARLY_STOP_SIM_TIME = (
    1.0  # seconds of sim time before checking if cube is still on floor
)
FLOOR_Y_THRESHOLD = -235.0  # cube Y below this = on the floor / never picked up
FLOOR_Y_BUFFER = 5.0  # how far above threshold counts as "still on floor"
PICKUP_Y_THRESHOLD = -215.0  # cube Y above this = considered picked up
DROP_PENALTY = 50.0  # score to assign if cube is dropped after being picked up at least once # fmt: skip
# after the early stop window

# Overload phase (after recorded trajectory): cube mass ramps up, and score is
# hold-time only after EARLY_STOP_SIM_TIME.
OVERLOAD_MAX_TIME = 5.0  # seconds of post-recording overload simulation
CUBE_MASS_START = 0.005  # kg, should match scene cube initial mass
CUBE_MASS_MAX = 1.0  # kg reached by the end of the overload ramp
CUBE_MASS_RAMP_TIME = 8.0  # seconds to ramp from start mass to max mass
ENABLE_UNDERCUBE_CHECK = (
    False  # if False, skip the under-cube invalid-geometry malus rule entirely
)
SHAPEOPT_FRICTION_COEF = float(
    os.environ.get("SHAPEOPT_FRICTION_COEF", "0.6")
)  # passed to scene contact manager (mu)
EARLY_CONTACT_PENALTY = float(os.environ.get("EARLY_CONTACT_PENALTY", "-1.0"))
NO_PICKUP_PENALTY = float(os.environ.get("NO_PICKUP_PENALTY", "0.0"))
UNDERCUBE_PENALTY = float(os.environ.get("UNDERCUBE_PENALTY", "-0.2"))
CONSISTENCY_PENALTY_COEF = float(
    os.environ.get("CONSISTENCY_PENALTY_COEF", "0.1")
)  # lower values reduce risk-aversion
SCORE_AGGREGATION = os.environ.get("SCORE_AGGREGATION", "mean").strip().lower()


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────


def reset_trials_dir():
    """
    Wipe the entire trials directory and recreate it fresh, including the previews folder.

    Inputs:
        None

    Returns:
        None
    """
    if TRIALS_DIR.exists():
        shutil.rmtree(TRIALS_DIR)
        print(f"[reset] Cleared {TRIALS_DIR}")
    TRIALS_DIR.mkdir(parents=True)
    PREVIEWS_DIR.mkdir()


def resolve_failed_preview_image() -> Path:
    """
    Resolve the placeholder image used for failed or empty generations.

    Returns:
        Path: Existing placeholder PNG path.
    """
    for candidate in FAILED_PREVIEW_IMAGE_CANDIDATES:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "Missing failed preview placeholder image. Expected "
        "failed_generation.png in the lab root."
    )


def publish_preview(
    source_png: Path, trial_dir: Path, gen_index: int, trial_index: int
):
    """
    Copy one preview PNG into both the trial folder and the flat gallery.

    Inputs:
        source_png (Path): Source preview image.
        trial_dir (Path): Trial directory where preview.png should live.
        gen_index (int): Generation number used for the gallery filename.
        trial_index (int): Trial number used for the gallery filename.

    Returns:
        Path: The trial-local preview path.
    """
    local_path = trial_dir / "preview.png"
    shutil.copy2(source_png, local_path)

    flat_name = f"gen_{gen_index:04d}_trial_{trial_index:02d}.png"
    shutil.copy2(local_path, PREVIEWS_DIR / flat_name)

    return local_path


def build_env() -> dict:
    """
    Build a copy of the current environment with SOFA, Python, and early-stop
    parameters injected as environment variables.

    Inputs:
        None

    Returns:
        dict: Environment variables dict ready to pass to subprocess calls.
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
    return env


def write_jsonc(path: Path, data: dict):
    """
    Write a dict as plain JSON to a .jsonc file.

    Inputs:
        path (Path): Destination file path.
        data (dict): Data to serialize.

    Returns:
        None
    """
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


class GeometryExportTimeoutError(RuntimeError):
    pass


class GeometryExportFailureError(RuntimeError):
    pass


def write_run_status(path: Path, data: dict) -> None:
    """
    Write one run status JSON file for the live monitor window.

    Inputs:
        path (Path): Status file path.
        data (dict): Status payload.

    Returns:
        None
    """
    # Atomic replace prevents partially written/empty files from being observed.
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def params_from_trial(trial) -> dict:
    """
    Sample one set of gripper shape parameters from an Optuna trial.

    Inputs:
        trial (optuna.Trial): Active Optuna trial to sample from.

    Returns:
        dict: Sampled shape parameter values.
    """
    return {
        # Pincer profile
        "pincer_profile_width": trial.suggest_float("pincer_profile_width", 2.0, 8.0),
        "pincer_profile_height": trial.suggest_float(
            "pincer_profile_height", 6.0, 16.0
        ),
        "pincer_path_scale": 0.4,
        "pincer_tilt_y_deg": 90.0,
        "pincer_round_ends": PINCER_ROUND_ENDS,
        # Spline first handle (anchor is fixed at 0,0)
        "p0_hout_dist": trial.suggest_float("p0_hout_dist", 0.0, 80.0),
        "p0_hout_angle_deg": trial.suggest_float("p0_hout_angle_deg", -90, 90),
        # Spline endpoint
        "p1_dist": trial.suggest_float("p1_dist", 70.0, 90.0),
        "p1_angle_deg": trial.suggest_float("p1_angle_deg", -90.0, 45.0),
        # Spline last handle
        "p1_hin_dist": trial.suggest_float("p1_hin_dist", 0.0, 80.0),
        "p1_hin_angle_deg": trial.suggest_float("p1_hin_angle_deg", -10.0, 260.0),
        # Leg tilt
        "leg_attachement_tilt_angle": trial.suggest_float(
            "leg_attachement_tilt_angle", -30.0, 30.0
        ),
    }


def generate_stl_for_trial(trial_dir: Path, config: dict) -> tuple[Path, Path]:
    """
    Write lab_config.jsonc into trial_dir, call generate_gripper.py, rename the
    collision STL to a trial-specific name, and copy the visual STL into trial_dir.

    The visual STL (new_gripper.stl) is left in place in CENTERPARTS_DIR so SOFA
    can find it by its hardcoded name. It is also copied into trial_dir as visual.stl
    for the preview render. The collision STL is renamed to a trial-specific name to
    avoid conflicts across parallel SOFA instances.

    Inputs:
        trial_dir (Path): Directory for this trial's files.
        config (dict): Full config to write as lab_config.jsonc.

    Returns:
        tuple[Path, Path]: Paths to (collision STL in CENTERPARTS_DIR, visual STL copy in trial_dir).
    """
    config_path = trial_dir / "lab_config.jsonc"
    write_jsonc(config_path, config)

    try:
        result = subprocess.run(
            [sys.executable, GENERATE_SCRIPT, "--config", str(config_path)],
            cwd=str(APP_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GEOMETRY_EXPORT_TIMEOUT,
        )
    except subprocess.TimeoutExpired as e:
        stdout_tail = (e.stdout or "")[-1500:]
        stderr_tail = (e.stderr or "")[-1500:]
        raise GeometryExportTimeoutError(
            "generate_gripper.py timed out "
            f"after {GEOMETRY_EXPORT_TIMEOUT:.1f}s.\n"
            f"stdout (tail):\n{stdout_tail}\n"
            f"stderr (tail):\n{stderr_tail}"
        ) from e

    if result.returncode != 0:
        stdout_tail = (result.stdout or "")[-2000:]
        stderr_tail = (result.stderr or "")[-2000:]
        raise GeometryExportFailureError(
            "generate_gripper.py failed "
            f"(returncode={result.returncode}).\n"
            f"stdout (tail):\n{stdout_tail}\n"
            f"stderr (tail):\n{stderr_tail}"
        )

    trial_id = f"{trial_dir.parent.name}_{trial_dir.name}"

    # Rename collision STL to a trial-specific name so parallel SOFA instances don't collide
    collision_src = CENTERPARTS_DIR / "new_gripper_collision.stl"
    if not collision_src.exists():
        raise RuntimeError("Collision STL not found after generation.")
    collision_stl = CENTERPARTS_DIR / f"gripper_{trial_id}_collision.stl"
    collision_src.replace(collision_stl)

    # Copy visual STL into trial_dir for the preview — new_gripper.stl stays in place for SOFA
    visual_src = CENTERPARTS_DIR / "new_gripper.stl"
    if not visual_src.exists():
        raise RuntimeError("Visual STL not found after generation.")
    visual_stl_copy = trial_dir / "visual.stl"
    shutil.copy2(visual_src, visual_stl_copy)

    return collision_stl, visual_stl_copy


def render_stl_preview(
    visual_stl: Path, trial_dir: Path, gen_index: int, trial_index: int
):
    """
    Render an offscreen PNG preview from the visual STL, save it to the trial
    directory and the flat previews folder, then delete the STL.

    Inputs:
        visual_stl (Path): Path to the full-resolution visual STL to render.
        trial_dir (Path): Trial directory where preview.png will be saved.
        gen_index (int): Generation number, used to name the flat preview file.
        trial_index (int): Trial number within the generation, used to name the flat preview file.

    Returns:
        None
    """
    plotter = None
    try:
        mesh = pv.read(str(visual_stl))

        if mesh.n_cells == 0 or mesh.n_points == 0:
            raise ValueError("visual mesh is empty")

        plotter = pv.Plotter(off_screen=True, window_size=(800, 600))
        plotter.add_mesh(mesh, color="#4a90d9", pbr=True, metallic=0.1, roughness=0.4)
        plotter.add_light(pv.Light(position=(200, 200, 400), intensity=0.8))
        plotter.camera_position = [
            (300, -30, 0),  # where the camera sits
            (0, -30, 0),  # what it looks at (center of model)
            (0, 1, 0),  # which direction is "up"
        ]
        plotter.camera.zoom(1.2)
        plotter.background_color = "white"

        local_path = trial_dir / "preview.png"
        plotter.screenshot(str(local_path))

        # Visual STL no longer needed now that the preview is saved
        visual_stl.unlink()

        flat_name = f"gen_{gen_index:04d}_trial_{trial_index:02d}.png"
        shutil.copy2(local_path, PREVIEWS_DIR / flat_name)

        print(f"[preview] Saved {flat_name}")
    except Exception as e:
        print(f"[warn] Preview render failed for {visual_stl.name}: {e}")
        try:
            publish_preview(
                resolve_failed_preview_image(), trial_dir, gen_index, trial_index
            )
            print(
                f"[preview] Saved failed placeholder for gen_{gen_index:04d} "
                f"trial_{trial_index:02d}"
            )
        except Exception as fallback_err:
            print(
                f"[warn] Failed preview fallback could not be published: {fallback_err}"
            )
    finally:
        if plotter is not None:
            plotter.close()
        if visual_stl.exists():
            visual_stl.unlink()


def delete_after_delay(path: Path, delay: float):
    """
    Delete a file after a delay in a background daemon thread.

    Inputs:
        path (Path): File to delete.
        delay (float): Seconds to wait before deleting.

    Returns:
        None
    """

    def _delete():
        time.sleep(delay)
        try:
            path.unlink()
            if PRINT_CLEANUP_LOGS:
                print(f"[cleanup] Deleted {path.name}")
        except FileNotFoundError:
            pass

    threading.Thread(target=_delete, daemon=True).start()


def ensure_windows_sofa_job() -> None:
    """
    Create one Windows Job Object configured to kill all assigned children when
    this optimizer process exits or its console is closed.

    Inputs:
        None

    Returns:
        None
    """
    global SOFA_JOB_HANDLE
    if os.name != "nt" or SOFA_JOB_HANDLE is not None:
        return

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        wintypes.INT,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise OSError(f"CreateJobObjectW failed: {ctypes.get_last_error()}")

    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    JobObjectExtendedLimitInformation = 9
    info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE

    ok = kernel32.SetInformationJobObject(
        job,
        JobObjectExtendedLimitInformation,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if not ok:
        raise OSError(f"SetInformationJobObject failed: {ctypes.get_last_error()}")

    SOFA_JOB_HANDLE = job


def attach_process_to_sofa_job(proc: subprocess.Popen) -> None:
    """
    Attach one child process to the global SOFA job object.

    Inputs:
        proc (subprocess.Popen): Child process to attach.

    Returns:
        None
    """
    if os.name != "nt":
        return

    ensure_windows_sofa_job()
    if SOFA_JOB_HANDLE is None:
        return

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL

    ok = kernel32.AssignProcessToJobObject(
        SOFA_JOB_HANDLE,
        wintypes.HANDLE(proc._handle),
    )
    if not ok:
        err = ctypes.get_last_error()
        print(
            f"[warn] Could not attach SOFA process {proc.pid} to kill-on-close job (winerr={err})."
        )


def launch_sofa(
    collision_stl: Path,
    score_path: Path,
    status_path: Path,
    gen_index: int,
    trial_index: int,
    run_index: int,
    env: dict,
) -> subprocess.Popen:
    """
    Launch one SOFA simulation instance for a given collision STL and score output path.
    The process runs fully in the background with no console window.

    Inputs:
        collision_stl (Path): Path to the collision STL, passed via OPTUNA_STL_PATH env var.
        score_path (Path): Path where SOFA will write the score JSON.
        status_path (Path): Path where SOFA will write per-frame run status.
        gen_index (int): Generation index.
        trial_index (int): Trial index inside generation.
        run_index (int): Repeat index inside trial.
        env (dict): Base environment dict to extend for this run.

    Returns:
        subprocess.Popen: The launched SOFA process.
    """
    trial_env = env.copy()
    trial_env["OPTUNA_STL_PATH"] = str(collision_stl)
    trial_env["OPTUNA_SCORE_PATH"] = str(score_path)
    trial_env["OPTUNA_STATUS_PATH"] = str(status_path)
    trial_env["OPTUNA_GEN"] = str(gen_index)
    trial_env["OPTUNA_TRIAL"] = str(trial_index)
    trial_env["OPTUNA_RUN"] = str(run_index)

    if SOFA_GUI in ("batch", "imgui", "glfw"):
        gui_mode = SOFA_GUI
    else:
        gui_mode = "batch" if HEADLESS else "imgui"
    creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    if hasattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS"):
        creation_flags |= subprocess.BELOW_NORMAL_PRIORITY_CLASS

    proc = subprocess.Popen(
        [RUNSOFA_EXE, "-l", "SofaPython3", "-g", gui_mode, SCENE_FILE],
        env=trial_env,
        cwd=ASSETS_ROOT,
        creationflags=creation_flags,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    attach_process_to_sofa_job(proc)
    return proc


def active_sofa_process_count(processes: list[tuple]) -> int:
    """Count currently running SOFA child processes."""
    active = 0
    for _, _, runs in processes:
        for p, _, _ in runs:
            if p.poll() is None:
                active += 1
    return active


def wait_for_geometry_slot(
    processes: list[tuple],
    limit: int,
    gen_index: int,
    trial_index: int,
) -> None:
    """Pause geometry launch until running SOFA process count is below limit."""
    if limit <= 0:
        return

    warned = False
    while active_sofa_process_count(processes) >= limit:
        if not warned:
            print(
                f"[throttle] Gen {gen_index:04d} Trial {trial_index:02d} waiting for "
                f"active SOFA < {limit}"
            )
            warned = True
        time.sleep(0.2)


def wait_for_sofa_runs(
    gen_index: int,
    processes: list[tuple],
    all_scores: list[float],
    n_repeats: int,
) -> None:
    """
    Wait for all SOFA subprocesses in a generation and print a live progress bar.

    Inputs:
        gen_index (int): Generation number for status display.
        processes (list[tuple]): List of (trial, runs) where runs is a list of
            (Popen, score_path, status_path).
        all_scores (list[float]): Completed-trial scores from previous generations.
        n_repeats (int): Number of repeated runs per trial.

    Returns:
        None
    """
    total_runs = sum(len(runs) for _, _, runs in processes)
    if total_runs == 0:
        return

    completed: set[tuple[int, int]] = set()
    start_time = time.time()
    last_update = 0.0
    bar_width = 28

    while len(completed) < total_runs:
        for trial_i, (_, _, runs) in enumerate(processes):
            for run_i, (p, _, _) in enumerate(runs):
                key = (trial_i, run_i)
                if key in completed:
                    continue
                if p.poll() is not None:
                    completed.add(key)

        now = time.time()
        if now - last_update >= 0.5:
            done = len(completed)
            pct = (100.0 * done) / total_runs
            filled = int(bar_width * done / total_runs)
            bar = "#" * filled + "-" * (bar_width - filled)
            elapsed = now - start_time
            print(
                f"\r[progress] Gen {gen_index:04d} SOFA [{bar}] "
                f"{done}/{total_runs} ({pct:5.1f}%)  elapsed {elapsed:5.1f}s",
                end="",
                flush=True,
            )
            last_update = now

        if len(completed) < total_runs:
            time.sleep(0.2)

    total_elapsed = time.time() - start_time
    print(
        f"\r[progress] Gen {gen_index:04d} SOFA [{'#' * bar_width}] "
        f"{total_runs}/{total_runs} (100.0%)  elapsed {total_elapsed:5.1f}s"
    )


def generation_progress_fraction(status_paths_by_trial: list[list[Path]]) -> float:
    """
    Estimate generation progress from per-run frame progress only.

    Inputs:
        status_paths_by_trial (list[list[Path]]): Expected status files for each
            trial/run slot in the generation.

    Returns:
        float: Generation progress as a fraction in [0, 1].
    """
    total = 0.0

    for runs in status_paths_by_trial:
        trial_total = 0.0
        for status_path in runs:
            try:
                data = json.loads(status_path.read_text(encoding="utf-8"))
                state = str(data.get("state", "")).lower()
                reason = str(data.get("reason", "")).lower()

                if state in {
                    "done",
                    "skipped",
                    "failed",
                    "error",
                    "cancelled",
                    "pruned",
                }:
                    trial_total += 1.0
                    continue

                cur = float(data.get("current_frame", 0))
                total_frames = data.get("total_frames")
                if isinstance(total_frames, int) and total_frames > 0:
                    trial_total += max(0.0, min(1.0, cur / float(total_frames)))
                elif reason:
                    # Any explicit end reason without frame data still counts as complete.
                    trial_total += 1.0
            except Exception:
                pass

        if runs:
            total += trial_total / len(runs)

    if not status_paths_by_trial:
        return 0.0

    return max(0.0, min(1.0, total / len(status_paths_by_trial)))


def generation_progress_writer(
    gen_index: int,
    status_paths_by_trial: list[list[Path]],
    all_scores: list[float],
    stop_event: threading.Event,
) -> None:
    """
    Continuously write frame-only generation progress until stopped.

    Inputs:
        gen_index (int): Current generation number.
        status_paths_by_trial (list[list[Path]]): Expected status files for the
            generation.
        all_scores (list[float]): All collected scores so far.
        stop_event (threading.Event): Signals when to stop writing progress.

    Returns:
        None
    """
    while not stop_event.is_set():
        write_progress(
            gen_index,
            generation_progress_fraction(status_paths_by_trial) * N_PARALLEL,
            all_scores,
        )
        stop_event.wait(GEN_PROGRESS_POLL_INTERVAL)


def read_score(score_path: Path) -> float:
    """
    Read the cube_z_final score written by SOFA's PlaybackController.

    Inputs:
        score_path (Path): Path to the JSON file written by SOFA.

    Returns:
        float: The score value, or -inf if the file is missing or malformed.
    """
    try:
        with open(score_path) as f:
            return float(json.load(f)["cube_z_final"])
    except Exception as e:
        print(f"[warn] Could not read score from {score_path}: {e}")
        return float("-inf")


def write_gen_summary(gen_dir: Path, gen_index: int, scores: list[float]):
    """
    Compute and write a summary.json for the generation with avg, best, and worst scores
    (including consistency-penalized final scores).

    Inputs:
        gen_dir (Path): The generation directory where summary.json will be written.
        gen_index (int): Current generation number.
        scores (list[float]): All trial final_scores for this generation (already consistency-penalized).

    Returns:
        None
    """
    valid_scores = [s for s in scores if s not in (float("-inf"), None)]

    summary = {
        "gen": gen_index,
        "n_trials": len(scores),
        "n_valid": len(valid_scores),
        "avg_score": (
            round(sum(valid_scores) / len(valid_scores), 4) if valid_scores else None
        ),
        "best_score": round(max(valid_scores), 4) if valid_scores else None,
        "worst_score": round(min(valid_scores), 4) if valid_scores else None,
    }
    write_jsonc(gen_dir / "summary.json", summary)
    avg_str = (
        f"{summary['avg_score']:.2f}" if summary["avg_score"] is not None else "n/a"
    )
    best_str = (
        f"{summary['best_score']:.2f}" if summary["best_score"] is not None else "n/a"
    )
    print(
        f"[summary] Gen {gen_index:04d} — "
        f"avg: {avg_str}  best: {best_str}  "
        f"({len(valid_scores)}/{len(scores)} trials) [consistency-adjusted]"
    )


def write_progress(gen_index: int, trials_done_in_gen: float, all_scores: list[float]):
    """
    Write current optimization progress to progress.json for the UI progress bar to poll.

    Inputs:
        gen_index (int): Current generation number (1-based).
        trials_done_in_gen (float): How many trial-equivalents have progressed in the current generation.
        all_scores (list[float]): Every score collected so far across all generations.

    Returns:
        None
    """
    trials_done_in_gen = max(0.0, min(float(N_PARALLEL), float(trials_done_in_gen)))
    total_done = (gen_index - 1) * N_PARALLEL + trials_done_in_gen
    total = N_GENERATIONS * N_PARALLEL
    payload = {
        "gen_current": gen_index,
        "gen_total": N_GENERATIONS,
        "trials_per_gen": N_PARALLEL,
        "runs_per_trial": N_REPEATS,
        "trial_current": total_done,
        "trial_total": total,
        "pct": round(100 * total_done / total, 1),
        "best_score": round(max(all_scores), 4) if all_scores else None,
        "avg_score": (
            round(sum(all_scores) / len(all_scores), 4) if all_scores else None
        ),
        "started_at": TRAINING_STARTED_AT,
        "updated_at": time.time(),
    }

    PROGRESS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def cleanup_generation_status_files(gen_dir: Path) -> None:
    """
    Delete all per-run status files for a generation after it is fully complete.

    Inputs:
        gen_dir (Path): Generation directory.

    Returns:
        None
    """
    for status_path in gen_dir.glob("trial_*/status_run*.json"):
        # On Windows, external readers (monitor/AV/indexer) can transiently lock
        # JSON files right after the generation ends. Never fail training cleanup.
        removed = False
        for attempt in range(8):
            try:
                status_path.unlink()
                removed = True
                break
            except FileNotFoundError:
                removed = True
                break
            except PermissionError:
                # Back off briefly and retry while lock is released.
                time.sleep(0.05 * (attempt + 1))

        if not removed and status_path.exists():
            print(f"[warn] Could not delete locked status file: {status_path}")


# ─────────────────────────────────────────────
# Core generation loop
# ─────────────────────────────────────────────


def run_generation(
    gen_index: int,
    trials: list,
    study: optuna.Study,
    env: dict,
    all_scores: list[float],
):
    gen_dir = TRIALS_DIR / f"gen_{gen_index:04d}"
    gen_dir.mkdir(parents=True, exist_ok=True)

    processes = (
        []
    )  # list of (trial_index, trial, [(Popen, score_path, status_path), ...])
    collision_stls_by_trial: dict[int, Path] = {}
    status_paths_by_trial: list[list[Path]] = []

    # Pre-create all trial/run status files in deterministic order so the
    # monitor can always display every run slot (not-started/running/done).
    for trial_index in range(1, N_PARALLEL + 1):
        trial_dir = gen_dir / f"trial_{trial_index:02d}"
        trial_status_paths: list[Path] = []
        trial_dir.mkdir(exist_ok=True)
        for run_index in range(1, N_REPEATS + 1):
            status_path = trial_dir / f"status_run{run_index-1}.json"
            trial_status_paths.append(status_path)
            write_run_status(
                status_path,
                {
                    "gen": gen_index,
                    "trial": trial_index,
                    "run": run_index,
                    "state": "not-started",
                    "current_frame": 0,
                    "total_frames": None,
                    "sim_time": 0.0,
                    "updated_at": time.time(),
                },
            )
        status_paths_by_trial.append(trial_status_paths)

    progress_stop = threading.Event()
    progress_thread = threading.Thread(
        target=generation_progress_writer,
        args=(gen_index, status_paths_by_trial, all_scores, progress_stop),
        daemon=True,
    )
    progress_thread.start()

    prelaunch_scores: list[float] = []

    for i, trial in enumerate(trials):
        trial_index = i + 1
        trial_dir = gen_dir / f"trial_{trial_index:02d}"
        trial_dir.mkdir(exist_ok=True)

        wait_for_geometry_slot(processes, MAX_ACTIVE_SOFA_PROCS, gen_index, trial_index)

        shape_params = params_from_trial(trial)
        full_config = {**RING_FIXED, **shape_params, **MESH_FIXED}

        try:
            collision_stl, visual_stl_copy = generate_stl_for_trial(
                trial_dir, full_config
            )

            render_stl_preview(visual_stl_copy, trial_dir, gen_index, trial_index)

            runs = []
            for r in range(N_REPEATS):
                score_path = trial_dir / f"score_run{r}.json"
                status_path = trial_dir / f"status_run{r}.json"
                write_run_status(
                    status_path,
                    {
                        "gen": gen_index,
                        "trial": trial_index,
                        "run": r + 1,
                        "state": "launching",
                        "current_frame": 0,
                        "total_frames": None,
                        "sim_time": 0.0,
                        "updated_at": time.time(),
                    },
                )
                p = launch_sofa(
                    collision_stl,
                    score_path,
                    status_path,
                    gen_index,
                    trial_index,
                    r + 1,
                    env,
                )
                print(
                    f"[sofa] Gen {gen_index:04d} Trial {trial_index:02d} Run {r+1}/{N_REPEATS}"
                )
                runs.append((p, score_path, status_path))

            collision_stls_by_trial[trial_index] = collision_stl
            processes.append((trial_index, trial, runs))

        except GeometryExportTimeoutError as e:
            try:
                publish_preview(
                    resolve_failed_preview_image(), trial_dir, gen_index, trial_index
                )
            except Exception as preview_err:
                print(
                    f"[warn] Failed placeholder preview for Gen {gen_index:04d} "
                    f"Trial {trial_index:02d}: {preview_err}"
                )
            for r in range(N_REPEATS):
                status_path = trial_dir / f"status_run{r}.json"
                try:
                    write_run_status(
                        status_path,
                        {
                            "gen": gen_index,
                            "trial": trial_index,
                            "run": r + 1,
                            "state": "failed",
                            "current_frame": 0,
                            "total_frames": None,
                            "sim_time": 0.0,
                            "reason": f"geometry export timed out: {e}",
                            "updated_at": time.time(),
                        },
                    )
                except Exception as status_err:
                    print(
                        f"[warn] Could not write timeout status for "
                        f"Gen {gen_index:04d} Trial {trial_index:02d} "
                        f"Run {r+1}: {status_err}"
                    )
            print(
                f"[error] Gen {gen_index:04d} Trial {trial_index:02d} geometry timed out: {e}"
            )
            study.tell(trial, -2.0)
            write_jsonc(
                trial_dir / "trial_stats.json",
                {
                    "trial": trial_index,
                    "gen": gen_index,
                    "n_runs": 0,
                    "avg_score": -2.0,
                    "best_run": -2.0,
                    "worst_run": -2.0,
                    "consistency_penalty": 0.0,
                    "final_score": -2.0,
                    "run_scores": [],
                    "run_scores_valid": [],
                    "outcome": "geometry export timed out",
                },
            )
            prelaunch_scores.append(-2.0)
            all_scores.append(-2.0)
        except GeometryExportFailureError as e:
            try:
                publish_preview(
                    resolve_failed_preview_image(), trial_dir, gen_index, trial_index
                )
            except Exception as preview_err:
                print(
                    f"[warn] Failed placeholder preview for Gen {gen_index:04d} "
                    f"Trial {trial_index:02d}: {preview_err}"
                )
            for r in range(N_REPEATS):
                status_path = trial_dir / f"status_run{r}.json"
                try:
                    write_run_status(
                        status_path,
                        {
                            "gen": gen_index,
                            "trial": trial_index,
                            "run": r + 1,
                            "state": "failed",
                            "current_frame": 0,
                            "total_frames": None,
                            "sim_time": 0.0,
                            "reason": f"geometry export failed: {e}",
                            "updated_at": time.time(),
                        },
                    )
                except Exception as status_err:
                    print(
                        f"[warn] Could not write failed status for "
                        f"Gen {gen_index:04d} Trial {trial_index:02d} "
                        f"Run {r+1}: {status_err}"
                    )
            print(
                f"[error] Gen {gen_index:04d} Trial {trial_index:02d} geometry failed: {e}"
            )
            study.tell(trial, HARD_FAIL_SCORE)
            write_jsonc(
                trial_dir / "trial_stats.json",
                {
                    "trial": trial_index,
                    "gen": gen_index,
                    "n_runs": 0,
                    "avg_score": HARD_FAIL_SCORE,
                    "best_run": HARD_FAIL_SCORE,
                    "worst_run": HARD_FAIL_SCORE,
                    "consistency_penalty": 0.0,
                    "final_score": HARD_FAIL_SCORE,
                    "run_scores": [],
                    "run_scores_valid": [],
                    "outcome": "geometry export failed",
                },
            )
            prelaunch_scores.append(HARD_FAIL_SCORE)
            all_scores.append(HARD_FAIL_SCORE)
        except Exception as e:
            try:
                publish_preview(
                    resolve_failed_preview_image(), trial_dir, gen_index, trial_index
                )
            except Exception as preview_err:
                print(
                    f"[warn] Failed placeholder preview for Gen {gen_index:04d} "
                    f"Trial {trial_index:02d}: {preview_err}"
                )
            for r in range(N_REPEATS):
                status_path = trial_dir / f"status_run{r}.json"
                try:
                    write_run_status(
                        status_path,
                        {
                            "gen": gen_index,
                            "trial": trial_index,
                            "run": r + 1,
                            "state": "failed",
                            "current_frame": 0,
                            "total_frames": None,
                            "sim_time": 0.0,
                            "reason": f"geometry export failed: {e}",
                            "updated_at": time.time(),
                        },
                    )
                except Exception as status_err:
                    print(
                        f"[warn] Could not write failed status for "
                        f"Gen {gen_index:04d} Trial {trial_index:02d} "
                        f"Run {r+1}: {status_err}"
                    )
            print(
                f"[error] Gen {gen_index:04d} Trial {trial_index:02d} geometry failed: {e}"
            )
            study.tell(trial, HARD_FAIL_SCORE)
            write_jsonc(
                trial_dir / "trial_stats.json",
                {
                    "trial": trial_index,
                    "gen": gen_index,
                    "n_runs": 0,
                    "avg_score": HARD_FAIL_SCORE,
                    "best_run": HARD_FAIL_SCORE,
                    "worst_run": HARD_FAIL_SCORE,
                    "consistency_penalty": 0.0,
                    "final_score": HARD_FAIL_SCORE,
                    "run_scores": [],
                    "run_scores_valid": [],
                    "outcome": "geometry export failed",
                },
            )
            prelaunch_scores.append(HARD_FAIL_SCORE)
            all_scores.append(HARD_FAIL_SCORE)

    # --- Wait for all SOFA instances with live progress, then collect scores ---
    try:
        wait_for_sofa_runs(gen_index, processes, all_scores, N_REPEATS)

        gen_scores = prelaunch_scores.copy()

        def _read_status_data(path: Path) -> dict | None:
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return None

        def _is_pruned_status(status_data: dict | None) -> bool:
            if not isinstance(status_data, dict):
                return False
            state = str(status_data.get("state", "")).lower()
            reason = str(status_data.get("reason", "")).lower()
            return (
                state == "pruned"
                or "pruned" in reason
                or "test horizon complete" in reason
                or "glitched through floor after pickup" in reason
            )

        def _prune_reason(status_data: dict | None) -> str:
            if not isinstance(status_data, dict):
                return "unknown prune reason"
            reason = str(status_data.get("reason", "")).strip()
            state = str(status_data.get("state", "")).strip() or "unknown"
            return reason if reason else f"state={state}"

        def _print_prune_banner(message: str) -> None:
            print("#################")
            print("")
            print("PRUNED RUN")
            print(message)
            print("")
            print("#################")

        for trial_index, trial, runs in processes:
            trial_dir = gen_dir / f"trial_{trial_index:02d}"
            run_scores = []
            prune_trial = False
            prune_reasons: list[str] = []
            collision_stl = collision_stls_by_trial.get(trial_index)
            for run_number, (p, score_path, status_path) in enumerate(runs, start=1):
                score = read_score(score_path)
                status_data = _read_status_data(status_path)

                # Retry one time if this run ended pruned. If the retry is still pruned,
                # prune the whole trial as requested.
                if _is_pruned_status(status_data):
                    first_reason = _prune_reason(status_data)
                    _print_prune_banner(
                        f"Gen {gen_index:04d} Trial {trial_index:02d} Run {run_number} first prune: {first_reason}"
                    )
                    if collision_stl is None or not collision_stl.exists():
                        unavailable_msg = (
                            f"Gen {gen_index:04d} Trial {trial_index:02d} "
                            f"Run {run_number} pruned but STL is unavailable for retry."
                        )
                        _print_prune_banner(unavailable_msg)
                        prune_reasons.append(unavailable_msg)
                        prune_trial = True
                    else:
                        print(
                            f"[retry] Gen {gen_index:04d} Trial {trial_index:02d} "
                            f"Run {run_number} pruned; relaunching once..."
                        )
                        try:
                            if score_path.exists():
                                score_path.unlink()
                        except Exception:
                            pass

                        write_run_status(
                            status_path,
                            {
                                "gen": gen_index,
                                "trial": trial_index,
                                "run": run_number,
                                "state": "launching",
                                "current_frame": 0,
                                "total_frames": None,
                                "sim_time": 0.0,
                                "reason": "retry after pruned run",
                                "updated_at": time.time(),
                            },
                        )

                        retry_proc = launch_sofa(
                            collision_stl,
                            score_path,
                            status_path,
                            gen_index,
                            trial_index,
                            run_number,
                            env,
                        )
                        retry_proc.wait()
                        score = read_score(score_path)
                        status_data = _read_status_data(status_path)

                        if _is_pruned_status(status_data):
                            second_reason = _prune_reason(status_data)
                            retry_msg = (
                                f"Gen {gen_index:04d} Trial {trial_index:02d} Run {run_number} "
                                f"pruned again after retry: {second_reason}"
                            )
                            _print_prune_banner(retry_msg)
                            prune_reasons.append(retry_msg)
                            prune_trial = True

                state = ""
                reason = ""
                if isinstance(status_data, dict):
                    state = str(status_data.get("state", "")).lower()
                    reason = str(status_data.get("reason", "")).lower()

                run_scores.append(score)

                # If SOFA exited without writing a score, mark run as failed with reason.
                if score == float("-inf"):
                    if state in ("", "not-started", "launching", "running"):
                        run_index = (
                            int(status_data.get("run", 0))
                            if isinstance(status_data, dict)
                            else 0
                        )
                        write_run_status(
                            status_path,
                            {
                                "gen": gen_index,
                                "trial": trial_index,
                                "run": run_index,
                                "state": "failed",
                                "current_frame": 0,
                                "total_frames": None,
                                "sim_time": 0.0,
                                "reason": (
                                    f"sofa exited with code {p.returncode} before writing score"
                                ),
                                "updated_at": time.time(),
                            },
                        )

            if prune_trial:
                study.tell(trial, state=optuna.trial.TrialState.PRUNED)
                gen_scores.append(None)
                if prune_reasons:
                    _print_prune_banner(
                        "TRIAL PRUNED because a run stayed pruned after retry. "
                        + " | ".join(prune_reasons)
                    )
                print(
                    f"[score] trial_{trial_index:02d} → PRUNED (impossible end-horizon / post-pickup floor glitch)"
                )
                continue

            if any(score == float("-inf") for score in run_scores):
                final_score = HARD_FAIL_SCORE
                study.tell(trial, final_score)
                print(
                    f"[score] trial_{trial_index:02d} → {final_score:.2f} "
                    f"(generation failure: runs={run_scores})"
                )
                gen_scores.append(final_score)
                all_scores.append(final_score)
                continue

            valid_scores = [s for s in run_scores if s != float("-inf")]

            avg_score = sum(valid_scores) / len(valid_scores)
            median_score = statistics.median(valid_scores)
            if SCORE_AGGREGATION == "median":
                aggregate_score = median_score
            else:
                # Default to mean to reward occasional strong outcomes and
                # improve escape from conservative local basins.
                aggregate_score = avg_score
            # Apply consistency penalty: penalize high variance between runs
            consistency_penalty = CONSISTENCY_PENALTY_COEF * (
                max(valid_scores) - min(valid_scores)
            )
            final_score = aggregate_score - consistency_penalty
            study.tell(trial, final_score)

            # Write trial-level statistics to a JSON file for analysis
            trial_stats = {
                "trial": trial_index,
                "gen": gen_index,
                "n_runs": len(valid_scores),
                "avg_score": round(avg_score, 4),
                "median_score": round(median_score, 4),
                "score_aggregation": SCORE_AGGREGATION,
                "aggregate_score": round(aggregate_score, 4),
                "best_run": round(max(valid_scores), 4),
                "worst_run": round(min(valid_scores), 4),
                "consistency_penalty": round(consistency_penalty, 4),
                "final_score": round(final_score, 4),
                "run_scores": [round(s, 4) for s in run_scores],
                "run_scores_valid": [round(s, 4) for s in valid_scores],
            }
            write_jsonc(trial_dir / "trial_stats.json", trial_stats)

            print(
                f"[score] trial_{trial_index:02d} → {final_score:.2f} "
                f"({SCORE_AGGREGATION}: {aggregate_score:.2f}, "
                f"penalty: {consistency_penalty:.2f}, "
                f"runs: {[round(s,2) for s in run_scores]})"
            )

            gen_scores.append(final_score)
            all_scores.append(final_score)
        write_gen_summary(gen_dir, gen_index, gen_scores)
        cleanup_generation_status_files(gen_dir)
    finally:
        for collision_stl in collision_stls_by_trial.values():
            try:
                if collision_stl.exists():
                    collision_stl.unlink()
                    if PRINT_CLEANUP_LOGS:
                        print(f"[cleanup] Deleted {collision_stl.name}")
            except Exception:
                pass
        progress_stop.set()
        progress_thread.join(timeout=2.0)


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────


def main():
    """
    Entry point: initialize a fresh Optuna CMA-ES study and run all generations.

    Inputs:
        None

    Returns:
        None
    """
    global TRAINING_STARTED_AT

    # Always start fresh — wipe trials dir and delete existing DB
    reset_trials_dir()
    TRAINING_STARTED_AT = time.time()
    db_path = LAB_ROOT / "runtime" / "gripper_opt.db"
    if db_path.exists():
        db_path.unlink()
        print(f"[reset] Deleted {db_path.name}")

    sampler_kwargs = {
        "popsize": N_PARALLEL,
        "sigma0": CMAES_SIGMA0,
        "n_startup_trials": CMAES_STARTUP_TRIALS,
        "consider_pruned_trials": True,
        "x0": {  # start from your known-good design
            "pincer_profile_width": 5.0,
            "pincer_profile_height": 10.0,
            "pincer_path_scale": 0.4,
            "p0_hout_dist": 0.0,
            "p0_hout_angle_deg": 0.0,
            "p1_dist": 80.0,
            "p1_angle_deg": -40.0,
            "p1_hin_dist": 0.0,
            "p1_hin_angle_deg": 0.0,
            "leg_attachement_tilt_angle": -15.0,
        },
    }
    sampler = optuna.samplers.CmaEsSampler(**sampler_kwargs)

    storage = optuna.storages.RDBStorage(f"sqlite:///{db_path}")
    study = optuna.create_study(
        study_name="gripper_shape_v1",
        sampler=sampler,
        direction="maximize",
        storage=storage,
    )

    env = build_env()
    all_scores: list[float] = []  # accumulates every score across all generations

    for gen in range(1, N_GENERATIONS + 1):
        # Write an immediate progress heartbeat at generation start so UI
        # polling has a file to read even before first trial scores arrive.
        write_progress(gen, 0, all_scores)

        print(f"\n{'='*50}")
        print(f"Generation {gen}/{N_GENERATIONS}")
        print(f"{'='*50}")

        trials = [study.ask() for _ in range(N_PARALLEL)]
        run_generation(gen, trials, study, env, all_scores)

        try:
            best = study.best_trial
            print(f"Best trial: {best.value}")
        except ValueError:
            print("No valid trials yet — all trials failed.")
            best = None

        if best is not None:
            print(f"[best so far] Trial {best.number} → {best.value:.2f}")
        else:
            print("[best so far] No valid trials yet.")

    print("\nOptimization complete.")
    try:
        best_trial = study.best_trial
        print(f"Best trial:  {best_trial.number}")
        print(f"Best value:  {best_trial.value:.4f}")
        print(f"Best params: {best_trial.params}")
    except ValueError:
        print("No valid trials found — all simulations failed.")


if __name__ == "__main__":
    main()
