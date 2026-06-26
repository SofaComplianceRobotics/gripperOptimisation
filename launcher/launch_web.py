"""
launch_web.py — Start the ShapeOPT web interface.

Sets up the emio-labs SOFA environment then opens the browser-based control
panel. This is the single entry point called from the emiolabs page button.
"""

import os
import sys
from pathlib import Path

# Put the lab root on sys.path up front so launcher.bootstrap is importable
# before we resolve the SOFA environment.
LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from launcher.bootstrap import bootstrap_lab, exe_name, find_bundled_python

# Clear emiolabs Python runtime variables that would otherwise leak into SOFA subprocesses
for _key in ("PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE", "PYTHONEXECUTABLE"):
    os.environ.pop(_key, None)

# One SOFA build for everything: the optimiser (headless batch) and the
# interactive scenes both run on the emio-labs SOFA so their physics match —
# a gripper that grips in the optimiser grips the same way in visual mode.
#
# runSofa, the plugin tree rooted at SOFA_ROOT, the SofaPython3 site-packages
# and the bundled Python must all come from this same build or plugins fail to
# load (ABI mismatch).


def _resolve_sofa_root() -> Path:
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


_EMIOLABS_SOFA_ROOT = _resolve_sofa_root()
_RUNSOFA = str(_EMIOLABS_SOFA_ROOT / "bin" / exe_name("runSofa"))
_PYTHON_DIR = _EMIOLABS_SOFA_ROOT / "bin" / "python"

os.environ["SOFA_ROOT"] = str(_EMIOLABS_SOFA_ROOT)
os.environ["RUNSOFA_EXE"] = _RUNSOFA
os.environ["SOFA_SITE_PACKAGES"] = str(
    _EMIOLABS_SOFA_ROOT / "plugins" / "SofaPython3" / "lib" / "python3" / "site-packages"
)
os.environ["SOFA_PYTHON_PATH"] = str(_PYTHON_DIR)
_python_exe = find_bundled_python(_PYTHON_DIR)
if _python_exe:
    os.environ["SOFA_PYTHON_EXE"] = _python_exe
os.environ.setdefault("EMIOLABS_RUNSOFA_EXE", _RUNSOFA)

os.environ.setdefault("SOFA_GUI", "batch")
os.environ.setdefault("HARD_FAIL_SCORE", "-3.0")

SCRIPT_DIR, SRC_ROOT, APP_ROOT, LAB_ROOT = bootstrap_lab(__file__)

from dashboard.app import launch_dashboard

if __name__ == "__main__":
    launch_dashboard(port=8050, open_browser=True)
