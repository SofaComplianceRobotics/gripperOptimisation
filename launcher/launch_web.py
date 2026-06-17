"""
launch_web.py — Start the ShapeOPT web interface.

Sets up the custom SOFA environment then opens the browser-based control panel.
This is the single entry point called from the emiolabs page button.
"""

import os
import sys
from pathlib import Path

# Clear emiolabs Python runtime variables that would otherwise leak into SOFA subprocesses
for _key in ("PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE", "PYTHONEXECUTABLE"):
    os.environ.pop(_key, None)

# emiolabs SOFA — used for interactive scenes (ImGui + emiolabs plugins)
_EMIOLABS_SOFA_BIN = (
    r"C:\Users\Cesar\AppData\Local\Programs\emio-labs\resources\sofa\bin"
)
os.environ.setdefault(
    "EMIOLABS_RUNSOFA_EXE",
    os.path.join(_EMIOLABS_SOFA_BIN, "runSofa.exe"),
)

# Custom SOFA build — used for headless optimisation (batch mode, Python 3.12).
#
# These three are FORCED (not setdefault): runSofa.exe, the plugin tree rooted
# at SOFA_ROOT, and the SofaPython3 site-packages must all come from the SAME
# build or plugins fail to load with "The specified procedure could not be
# found" (ABI mismatch) and every scene exits before it can run. A user/machine
# environment that already defines SOFA_ROOT (e.g. pointing at a downloaded
# binary release) would otherwise desync it from this build's runSofa.exe.
_CUSTOM_SOFA_ROOT = r"C:\dev\sofa\build"
os.environ["SOFA_ROOT"] = _CUSTOM_SOFA_ROOT
os.environ["RUNSOFA_EXE"] = rf"{_CUSTOM_SOFA_ROOT}\bin\Release\runSofa.exe"
os.environ["SOFA_SITE_PACKAGES"] = rf"{_CUSTOM_SOFA_ROOT}\lib\python3\site-packages"

os.environ.setdefault("SOFA_GUI", "batch")
os.environ.setdefault("HARD_FAIL_SCORE", "-3.0")
os.environ.setdefault(
    "SOFA_PYTHON_PATH",
    r"C:\Users\Cesar\AppData\Local\Programs\Python\Python312",
)

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from launcher.bootstrap import bootstrap_lab

SCRIPT_DIR, SRC_ROOT, APP_ROOT, LAB_ROOT = bootstrap_lab(__file__)

from dashboard.app import launch_dashboard

if __name__ == "__main__":
    launch_dashboard(port=8050, open_browser=True)
