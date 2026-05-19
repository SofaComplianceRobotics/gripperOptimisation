"""Process management: running subprocesses for generation and optimization."""

import json
import os
import subprocess
import sys
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────
LAB_ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE = LAB_ROOT / "config" / "lab_config.jsonc"
OPTIMIZE_SCRIPT = LAB_ROOT / "optimization" / "orchestrator.py"
GENERATE_SCRIPT = LAB_ROOT / "generation" / "generate_gripper.py"
GENERATE_FINE_SCRIPT = LAB_ROOT / "generation" / "generate_gripper_fine.py"
INVERSE_SCENE = LAB_ROOT / "scenes" / "lab_shapeOPT_inverse.py"
RECORDING_SCENE = LAB_ROOT / "scenes" / "lab_shapeOPT_recording.py"
SESSION_CONFIG_FILE = LAB_ROOT / "runtime" / "session_config.json"
_LOG_DIR = LAB_ROOT / "runtime" / "logs"

# Running subprocesses keyed by role ("optimize", "generate")
_PROCS: dict[str, subprocess.Popen | None] = {
    "optimize": None,
    "generate": None,
}


def _proc_running(name: str) -> bool:
    """Return True if a subprocess for the given role is currently running.

    Args:
        name: Role name of the subprocess (e.g. 'optimize', 'generate').

    Returns:
        True if the subprocess exists and has not exited.
    """
    proc = _PROCS.get(name)
    return proc is not None and proc.poll() is None


def _start_proc(name: str, script: Path, env: dict | None = None) -> str:
    """Start a background subprocess for a given role and script.

    Args:
        name: Role name to associate with the subprocess.
        script: Path to the Python script to execute.
        env: Optional environment overrides for the subprocess.

    Returns:
        Human-readable status string (started/already running/error).
    """
    if _proc_running(name):
        return f"Already running (PID {_PROCS[name].pid})."
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = _LOG_DIR / f"{name}.log"
        log_file = open(log_path, "w", encoding="utf-8")
        run_env = env if env is not None else os.environ.copy()
        # Force UTF-8 stdout in the subprocess so unicode characters don't crash on Windows
        run_env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.Popen(
            [sys.executable, str(script)],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=str(script.parent),
            env=run_env,
        )
        _PROCS[name] = proc
        return f"Started (PID {proc.pid})."
    except Exception as exc:
        return f"Error starting process: {exc}"


def _stop_proc(name: str) -> str:
    """Terminate a running subprocess by role name.

    Args:
        name: Role name of the subprocess to stop.

    Returns:
        Status string indicating result.
    """
    proc = _PROCS.get(name)
    if proc is None or proc.poll() is not None:
        return "Not running."
    try:
        proc.kill()
        _PROCS[name] = None
        return "Stopped."
    except Exception as exc:
        return f"Error stopping process: {exc}"


def _read_proc_log(name: str, tail: int = 150) -> str:
    """Read the last lines from a subprocess log file.

    Args:
        name: Role name whose log to read.
        tail: Number of trailing lines to return.

    Returns:
        The tail of the log as a single string, or empty string on error.
    """
    log_path = _LOG_DIR / f"{name}.log"
    if not log_path.exists():
        return ""
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        return "\n".join(lines[-tail:])
    except Exception:
        return ""


def _launch_sofa_scene(scene_file: Path, extra_env: dict | None = None) -> str:
    """Launch a SOFA scene using the emiolabs runSofa executable.

    Args:
        scene_file: Path to the SOFA scene script to launch.
        extra_env: Optional environment variables to merge.

    Returns:
        A status string describing the launch outcome.
    """
    # Interactive scenes require the emiolabs SOFA (ImGui + emiolabs plugins).
    # The custom batch SOFA used for optimisation does not have these.
    runsofa = os.environ.get(
        "EMIOLABS_RUNSOFA_EXE",
        r"C:\Users\Cesar\AppData\Local\Programs\emio-labs\resources\sofa\bin\runSofa.exe",
    )
    if not os.path.isfile(runsofa):
        return f"runSofa.exe not found at: {runsofa}"

    # Derive the emiolabs SOFA root from the executable path (bin/runSofa.exe → sofa/)
    emiolabs_sofa_root = str(Path(runsofa).parents[1])
    assets_root = str(LAB_ROOT.parent.parent)

    env = os.environ.copy()

    # Override SOFA_ROOT / SOFAPYTHON3_ROOT so the emiolabs runSofa.exe loads its own
    # Python packages instead of the custom build's — prevents 'No module named Sofa.Helper'
    env["SOFA_ROOT"] = emiolabs_sofa_root
    env["SOFAPYTHON3_ROOT"] = emiolabs_sofa_root

    # Drop vars that reference the custom Python 3.12 / batch-SOFA build
    for _k in ("SOFA_SITE_PACKAGES", "SOFA_PYTHON_PATH", "RUNSOFA_EXE"):
        env.pop(_k, None)

    # Ensure LAB_ROOT is on PYTHONPATH so scene files can import launcher and other modules
    pythonpath = env.get("PYTHONPATH", "")
    lab_root_str = str(LAB_ROOT)
    if lab_root_str not in pythonpath:
        env["PYTHONPATH"] = f"{lab_root_str};{pythonpath}".rstrip(";")

    if extra_env:
        env.update(extra_env)

    try:
        proc = subprocess.Popen(
            [runsofa, "-l", "SofaPython3", "-g", "imgui", str(scene_file)],
            env=env,
            cwd=str(LAB_ROOT),
        )
        return f"Launched SOFA (PID {proc.pid})."
    except Exception as exc:
        return f"Failed to launch: {exc}"


def _write_session_config(recording_test: str) -> None:
    """Write the chosen recording test into the session config file.

    Args:
        recording_test: Name of the test to save for the recording scene.
    """
    SESSION_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSION_CONFIG_FILE.write_text(
        json.dumps({"recording_test": recording_test}, indent=2),
        encoding="utf-8",
    )


def _load_config_text() -> str:
    """Return the contents of the lab configuration file as text.

    Returns:
        The configuration file contents, or an empty JSON object string on error.
    """
    try:
        return CONFIG_FILE.read_text(encoding="utf-8")
    except Exception:
        return "{}"
