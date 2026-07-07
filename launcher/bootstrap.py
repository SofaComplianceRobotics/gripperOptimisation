"""Bootstrap helper for lab runtime.

Provides `bootstrap_lab()` to set LAB_ROOT, insert repo roots into sys.path,
and set up lab-local site-packages. Intended to replace ad-hoc sys.path edits
in scene scripts and launchers.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Tuple


def exe_name(base: str) -> str:
    """Platform executable name: 'base.exe' on Windows, 'base' elsewhere."""
    return f"{base}.exe" if os.name == "nt" else base


def find_bundled_python(python_dir) -> str:
    """Locate the bundled Python interpreter inside an emio-labs python dir.

    Handles the Windows layout (<dir>/python.exe) and the Linux prefix layout
    (<dir>/bin/python3). Returns "" if none is found.
    """
    python_dir = Path(python_dir)
    relatives = (
        ["python.exe"]
        if os.name == "nt"
        else ["bin/python3", "bin/python", "python3", "python"]
    )
    for rel in relatives:
        exe = python_dir / rel
        if exe.is_file():
            return str(exe)
    return ""


def resolve_sofa_root() -> Path:
    """Locate the emio-labs SOFA build wherever it was installed.

    Resolution order, most reliable first:
      1. The build that owns the running interpreter. When launched by the
         emio-labs button, sys.executable lives under <sofa>/bin/python/, so the
         SOFA build whose ABI the plugins match is found directly (OS-agnostic).
      2. An explicit EMIOLABS_SOFA_ROOT override.
      3. The default per-user install location (Windows %LOCALAPPDATA%, or a few
         common Linux locations).

    A generic, possibly stale machine-wide SOFA_ROOT is intentionally ignored
    so it cannot desync the runtime from this build's runSofa.
    """
    candidates = []

    for parent in Path(sys.executable).resolve().parents:
        if parent.name.lower() == "sofa":
            candidates.append(parent)
            break

    override = os.environ.get("EMIOLABS_SOFA_ROOT")
    if override:
        candidates.append(Path(override))

    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(
            Path(local_appdata) / "Programs" / "emio-labs" / "resources" / "sofa"
        )

    home = Path.home()
    candidates += [
        home / ".local" / "share" / "emio-labs" / "resources" / "sofa",
        Path("/opt") / "emio-labs" / "resources" / "sofa",
    ]

    runsofa = exe_name("runSofa")
    for candidate in candidates:
        if (candidate / "bin" / runsofa).is_file():
            return candidate

    raise FileNotFoundError(
        f"Could not locate the emio-labs SOFA build (expected bin/{runsofa}). "
        "Install emio-labs, or set EMIOLABS_SOFA_ROOT to its resources/sofa folder."
    )


def resolve_sofa_runtime(prefer_env: bool = True) -> dict:
    """Resolve every path needed to run SOFA.

    Returns a dict with string values:
      sofa_root, runsofa_exe, python_dir, python_exe, site_packages.

    With ``prefer_env`` (the default), environment variables (SOFA_ROOT,
    RUNSOFA_EXE, SOFA_PYTHON_PATH, SOFA_PYTHON_EXE, SOFA_SITE_PACKAGES) win
    when already set — subprocesses launched by the web launcher and the test
    suite both rely on that. The web launcher itself passes False so a stale
    machine-wide SOFA_ROOT/RUNSOFA_EXE (e.g. a hand-downloaded SOFA) can never
    desync the runtime from the emio-labs build; only the explicit
    EMIOLABS_SOFA_ROOT override is honoured there.
    """

    def _env(key: str) -> str | None:
        return os.environ.get(key) if prefer_env else None

    sofa_root = _env("SOFA_ROOT") or str(resolve_sofa_root())
    root = Path(sofa_root)

    runsofa_exe = _env("RUNSOFA_EXE") or str(root / "bin" / exe_name("runSofa"))
    python_dir = _env("SOFA_PYTHON_PATH") or str(root / "bin" / "python")
    python_exe = (
        _env("SOFA_PYTHON_EXE") or find_bundled_python(python_dir) or sys.executable
    )
    site_packages = _env("SOFA_SITE_PACKAGES") or str(
        root / "plugins" / "SofaPython3" / "lib" / "python3" / "site-packages"
    )

    return {
        "sofa_root": sofa_root,
        "runsofa_exe": runsofa_exe,
        "python_dir": python_dir,
        "python_exe": python_exe,
        "site_packages": site_packages,
    }


def bootstrap_lab(script_file: str) -> Tuple[Path, Path, Path, Path]:
    """Locate the lab root from a script path and ensure repo paths are on sys.path.

    Args:
        script_file: Path to the calling script (typically __file__).

    Returns:
        A tuple (script_dir, src_root, app_root, lab_root).
    """
    script_dir = Path(script_file).resolve().parent
    lab_root = next(
        (
            c
            for c in (script_dir, *script_dir.parents)
            if (c / "config" / "lab_config.jsonc").is_file()
            and (c / "runtime").is_dir()
        ),
        script_dir,
    )
    src_root = lab_root
    app_root = lab_root
    lab_site = lab_root / "runtime" / "modules" / "site-packages"

    for candidate in (str(lab_root), str(lab_site)):
        if candidate and candidate not in sys.path:
            sys.path.insert(0, candidate)

    return script_dir, src_root, app_root, lab_root
