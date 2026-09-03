"""Process management for the lab's own dashboard tabs.

Owns the Generate-tab subprocesses and the interactive scene launchers.
The optimizer's Run/Stop lives in sofaopt's dashboard (driven by the
project's run_script / run_python_exe)."""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────
LAB_ROOT = Path(__file__).resolve().parents[2]
GENERATE_SCRIPT = LAB_ROOT / "generation" / "generate_all.py"
GENERATE_WORKER_SCRIPT = LAB_ROOT / "generation" / "worker.py"
GENERATE_FINE_SCRIPT = LAB_ROOT / "generation" / "generate_gripper_fine.py"
CONFIG_FILE = LAB_ROOT / "config" / "lab_config.jsonc"
INVERSE_SCENE = LAB_ROOT / "scenes" / "lab_shapeOPT_inverse.py"
RECORDING_SCENE = LAB_ROOT / "scenes" / "lab_shapeOPT_recording.py"
SESSION_CONFIG_FILE = LAB_ROOT / "runtime" / "session_config.json"
# Dashboard-owned logs (Generate tab, scene launchers). A sibling of runtime/,
# never a child: archiving moves runtime/ wholesale, and the persistent generate
# worker keeps its stderr file open for its whole life — on Windows that move
# fails if the open file sits under the directory being moved.
_LOG_DIR = LAB_ROOT / "logs"


def _sofa_python_exe() -> str:
    """Path to the emio-labs bundled Python for generation/optimization subprocesses.

    Never sys.executable: a machine may have its own Python on PATH that starts
    the dashboard, and its gmsh/cadquery can differ or fail to load. Falls back
    to the current interpreter only if the bundled one is absent.

    Returns:
        Absolute path to the bundled python.exe, or sys.executable as fallback.
    """
    from launcher.bootstrap import find_bundled_python

    exe = os.environ.get("SOFA_PYTHON_EXE") or find_bundled_python(
        os.environ.get("SOFA_PYTHON_PATH", "")
    )
    return exe if exe and os.path.isfile(exe) else sys.executable

# Running subprocesses keyed by role. A "generate" entry may also hold a
# _ThreadHandle when that run is being served by the persistent worker.
_PROCS: dict[str, "subprocess.Popen | _ThreadHandle | None"] = {
    "generate": None,
}


class _ThreadHandle:
    """Minimal Popen-like view of a background thread, so _proc_running and
    _stop_proc treat a warm-worker request like any other 'generate' run."""

    def __init__(self, thread: threading.Thread) -> None:
        self._thread = thread
        self.pid = "worker"

    def poll(self):
        return None if self._thread.is_alive() else 0

    def kill(self) -> None:
        # A gmsh/OCC call cannot be interrupted mid-flight; Stop recycles the
        # worker process instead (see _stop_proc).
        pass


def _proc_running(name: str) -> bool:
    """Return True if a subprocess for the given role is currently running.

    Args:
        name: Role name of the subprocess (e.g. 'optimize', 'generate').

    Returns:
        True if the subprocess exists and has not exited.
    """
    proc = _PROCS.get(name)
    return proc is not None and proc.poll() is None


# ── Persistent generation worker ───────────────────────────────
# The standard Generate button reuses one long-lived worker process so
# repeated clicks skip Python start-up + `import cadquery` (~1.3s). Every
# other path (fine/print export, a custom env) still gets a fresh
# subprocess, and any worker failure falls back to one too.
_WORKER: subprocess.Popen | None = None
_WORKER_RUNS = 0
_WORKER_MAX_RUNS = 40  # recycle before OCC's slow memory creep matters
_WORKER_LOCK = threading.Lock()
_WORKER_SPAWN_TIMEOUT = 30.0
_WORKER_RUN_TIMEOUT = 90.0


def _worker_alive() -> bool:
    return _WORKER is not None and _WORKER.poll() is None


def _kill_worker() -> None:
    global _WORKER
    if _WORKER is not None:
        try:
            _WORKER.kill()
        except Exception:
            pass
        _WORKER = None


def _spawn_worker() -> bool:
    """Start the worker and wait for its readiness line. Returns success."""
    global _WORKER, _WORKER_RUNS
    _kill_worker()
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        run_env = os.environ.copy()
        run_env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.Popen(
            [_sofa_python_exe(), str(GENERATE_WORKER_SCRIPT)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=open(_LOG_DIR / "generate_worker.err", "w", encoding="utf-8"),
            cwd=str(GENERATE_WORKER_SCRIPT.parent),
            env=run_env,
            text=True,
            bufsize=1,
        )
    except Exception:
        _WORKER = None
        return False

    ready = _read_line_with_timeout(proc.stdout, _WORKER_SPAWN_TIMEOUT)
    if not ready or not _json_ok(ready):
        try:
            proc.kill()
        except Exception:
            pass
        _WORKER = None
        return False

    _WORKER = proc
    _WORKER_RUNS = 0
    return True


def _read_line_with_timeout(stream, timeout: float) -> str:
    """Blocking readline guarded by a timeout thread. Returns '' on timeout."""
    box: list[str] = []
    reader = threading.Thread(target=lambda: box.append(stream.readline()), daemon=True)
    reader.start()
    reader.join(timeout)
    return box[0] if box else ""


def _json_ok(line: str) -> bool:
    try:
        return bool(json.loads(line).get("ok"))
    except Exception:
        return False


def _run_generate_on_worker(log_path: Path) -> dict:
    """Send one generate request to the worker and wait for its reply.

    Assumes the caller holds a live worker reference. Returns the parsed
    reply dict, or {"ok": False, ...} if the worker stalled or died.
    """
    request = json.dumps(
        {"cmd": "generate", "config": str(CONFIG_FILE), "log": str(log_path)}
    )
    try:
        _WORKER.stdin.write(request + "\n")
        _WORKER.stdin.flush()
    except Exception as exc:
        return {"ok": False, "error": f"worker write failed: {exc}"}

    reply = _read_line_with_timeout(_WORKER.stdout, _WORKER_RUN_TIMEOUT)
    if not reply:
        return {"ok": False, "error": "worker timed out"}
    try:
        return json.loads(reply)
    except Exception:
        return {"ok": False, "error": "worker sent malformed reply"}


def _start_generate() -> str:
    """Run the standard gripper+leg generation, preferring the warm worker.

    Falls back to a cold generate_all.py subprocess if the worker cannot be
    spawned or fails a run.
    """
    global _WORKER_RUNS

    log_path = _LOG_DIR / "generate.log"
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    with _WORKER_LOCK:
        if not _worker_alive() or _WORKER_RUNS >= _WORKER_MAX_RUNS:
            if not _spawn_worker():
                return _start_subprocess("generate", GENERATE_SCRIPT)
        _WORKER_RUNS += 1

    log_path.write_text("Generating (warm worker)...\n", encoding="utf-8")

    def _drive() -> None:
        result = _run_generate_on_worker(log_path)
        if not result.get("ok"):
            with _WORKER_LOCK:
                _kill_worker()
            with open(log_path, "a", encoding="utf-8") as log:
                log.write(
                    f"\n[warm worker failed: {result.get('error')}] "
                    "falling back to a fresh process...\n"
                )
            try:
                cold = subprocess.Popen(
                    [_sofa_python_exe(), str(GENERATE_SCRIPT)],
                    stdout=open(log_path, "a", encoding="utf-8"),
                    stderr=subprocess.STDOUT,
                    cwd=str(GENERATE_SCRIPT.parent),
                    env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                )
                cold.wait()
            except Exception as exc:
                with open(log_path, "a", encoding="utf-8") as log:
                    log.write(f"\nFallback generation failed: {exc}\n")

    thread = threading.Thread(target=_drive, daemon=True)
    thread.start()
    _PROCS["generate"] = _ThreadHandle(thread)
    return "Started (warm worker)."


def _start_subprocess(name: str, script: Path, env: dict | None = None) -> str:
    """Start a background subprocess for a given role and script.

    Args:
        name: Role name to associate with the subprocess.
        script: Path to the Python script to execute.
        env: Optional environment overrides for the subprocess.

    Returns:
        Human-readable status string (started/already running/error).
    """
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = _LOG_DIR / f"{name}.log"
        log_file = open(log_path, "w", encoding="utf-8")
        run_env = env if env is not None else os.environ.copy()
        # Force UTF-8 stdout in the subprocess so unicode characters don't crash on Windows
        run_env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.Popen(
            [_sofa_python_exe(), str(script)],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            cwd=str(script.parent),
            env=run_env,
        )
        _PROCS[name] = proc
        return f"Started (PID {proc.pid})."
    except Exception as exc:
        return f"Error starting process: {exc}"


def _start_proc(name: str, script: Path, env: dict | None = None) -> str:
    """Start a background job for a given role and script.

    The standard Generate run (generate_all.py, no custom env) goes through
    the persistent worker; everything else gets a fresh subprocess.

    Returns:
        Human-readable status string (started/already running/error).
    """
    if _proc_running(name):
        return f"Already running (PID {_PROCS[name].pid})."
    if name == "generate" and script == GENERATE_SCRIPT and env is None:
        return _start_generate()
    return _start_subprocess(name, script, env)


def _stop_proc(name: str) -> str:
    """Terminate a running job by role name.

    Args:
        name: Role name of the subprocess to stop.

    Returns:
        Status string indicating result.
    """
    proc = _PROCS.get(name)
    if proc is None or proc.poll() is not None:
        return "Not running."
    try:
        if isinstance(proc, _ThreadHandle):
            with _WORKER_LOCK:
                _kill_worker()
        else:
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
    # Interactive scenes run on the emio-labs SOFA with the ImGui GUI — the same
    # build the optimiser uses headless, so what you see here matches a trial.
    runsofa = os.environ["EMIOLABS_RUNSOFA_EXE"]
    if not os.path.isfile(runsofa):
        return f"runSofa executable not found at: {runsofa}"

    # Derive the emiolabs SOFA root from the executable path (bin/runSofa.exe → sofa/)
    emiolabs_sofa_root = str(Path(runsofa).parents[1])

    env = os.environ.copy()

    # Point SOFA_ROOT / SOFAPYTHON3_ROOT at the emiolabs build so runSofa.exe
    # self-resolves its own bundled Python packages.
    env["SOFA_ROOT"] = emiolabs_sofa_root
    env["SOFAPYTHON3_ROOT"] = emiolabs_sofa_root
    env["SHAPEOPT_FORCE_PAUSED"] = "1"

    # Let the GUI runSofa self-resolve its Python; clear the explicit paths the
    # optimiser sets for its headless launches.
    for _k in ("SOFA_SITE_PACKAGES", "SOFA_PYTHON_PATH", "RUNSOFA_EXE"):
        env.pop(_k, None)

    # Ensure LAB_ROOT and the sofaopt package are on PYTHONPATH: scene files
    # import launcher/labtests from the lab, and sofaopt.scene for scoring —
    # runSofa's embedded Python doesn't see the bundled Python's site-packages.
    import sofaopt

    pythonpath = env.get("PYTHONPATH", "")
    for extra in (str(LAB_ROOT), str(Path(sofaopt.__file__).resolve().parents[1])):
        if extra not in pythonpath:
            pythonpath = f"{extra}{os.pathsep}{pythonpath}".rstrip(os.pathsep)
    env["PYTHONPATH"] = pythonpath

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
