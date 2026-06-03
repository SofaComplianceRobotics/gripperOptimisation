"""
optimize_sofa.py — SOFA process management, launching, and subprocess handling.

Manages SOFA simulation instance lifecycle, Windows job object setup,
and process attachment for graceful cleanup.
"""

import ctypes
import os
import subprocess
import time
from ctypes import wintypes
from pathlib import Path

from optimization.optimize_config import HEADLESS, RUNSOFA_EXE, SOFA_GUI, ASSETS_ROOT

# Global job handle for Windows process group management
SOFA_JOB_HANDLE = None


class IO_COUNTERS(ctypes.Structure):
    """Windows I/O counters structure."""

    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    """Windows job object basic limits."""

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
    """Windows job object extended limits."""

    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def ensure_windows_sofa_job() -> None:
    """Create one Windows Job Object that kills assigned children when this process exits.

    Raises:
        OSError: If job object creation fails.
    """
    global SOFA_JOB_HANDLE
    if os.name != "nt" or SOFA_JOB_HANDLE is not None:
        return

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

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
    """Attach one child process to the global SOFA job object.

    Only works on Windows; silently returns on other platforms.

    Args:
        proc: Child process to attach.
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
    scene_file: Path,
    test_name: str,
    test_run_index: int,
    test_run_total: int,
    collision_stl: Path,
    trial_state_path: Path,
    run_slot: int,
    gen_index: int,
    trial_index: int,
    run_index: int,
    env: dict,
) -> subprocess.Popen:
    """Launch one SOFA simulation instance for a given collision STL.

    The process runs fully in the background with no console window.

    Args:
        scene_file: Scene file to run in SOFA.
        test_name: Selected test name for the run.
        test_run_index: 1-based run index within the selected test.
        test_run_total: Total runs planned for the selected test.
        collision_stl: Path to the collision STL, passed via OPTUNA_STL_PATH env var.
        trial_state_path: Path to trial_state.json shared by this trial.
        run_slot: 1-based run slot index within trial_state.json.
        gen_index: Generation index.
        trial_index: Trial index inside generation.
        run_index: Repeat index inside trial.
        env: Base environment dict to extend for this run.

    Returns:
        The launched SOFA process.
    """
    trial_env = env.copy()
    trial_env["OPTUNA_STL_PATH"] = str(collision_stl)
    trial_env["OPTUNA_TRIAL_STATE_PATH"] = str(trial_state_path)
    trial_env["OPTUNA_RUN_SLOT"] = str(run_slot)
    trial_env["OPTUNA_GEN"] = str(gen_index)
    trial_env["OPTUNA_TRIAL"] = str(trial_index)
    trial_env["OPTUNA_RUN"] = str(run_index)
    trial_env["OPTUNA_TEST_NAME"] = test_name
    trial_env["LAB_SHAPEOPT_TEST"] = test_name
    trial_env["LAB_SHAPEOPT_TEST_RUN_INDEX"] = str(test_run_index)
    trial_env["LAB_SHAPEOPT_TEST_RUN_TOTAL"] = str(test_run_total)
    trial_env["LAB_SHAPEOPT_RUN_LABEL"] = (
        f"{test_name} {test_run_index}/{test_run_total}"
    )

    if SOFA_GUI in ("batch", "imgui", "glfw"):
        gui_mode = SOFA_GUI
    else:
        gui_mode = "batch" if HEADLESS else "imgui"

    creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    if hasattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS"):
        creation_flags |= subprocess.BELOW_NORMAL_PRIORITY_CLASS

    proc = subprocess.Popen(
        [RUNSOFA_EXE, "-l", "SofaPython3", "-g", gui_mode, str(scene_file)],
        env=trial_env,
        cwd=ASSETS_ROOT,
        creationflags=creation_flags,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    attach_process_to_sofa_job(proc)
    return proc


def active_sofa_process_count(processes: list[tuple]) -> int:
    """Count currently running SOFA child processes.

    Args:
        processes: List of tuples where index 2 stores launched runs. Supports
            both (trial_index, trial, runs) and
            (trial_index, trial, runs, launched_run_plan_entries).

    Returns:
        Number of active SOFA processes.
    """
    active = 0
    for entry in processes:
        if len(entry) < 3:
            continue
        runs = entry[2]
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
    """Pause geometry launch until running SOFA process count is below limit.

    Args:
        processes: Running SOFA process list.
        limit: Maximum allowed concurrent SOFA processes (<=0 means no throttle).
        gen_index: Current generation number.
        trial_index: Current trial index.
    """
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
