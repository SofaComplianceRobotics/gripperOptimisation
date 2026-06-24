"""
launch_web.py — Start the ShapeOPT web interface.

Sets up the emio-labs SOFA environment then opens the browser-based control
panel. This is the single entry point called from the emiolabs page button.
"""

import os
import sys
from pathlib import Path

# Clear emiolabs Python runtime variables that would otherwise leak into SOFA subprocesses
for _key in ("PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE", "PYTHONEXECUTABLE"):
    os.environ.pop(_key, None)

# One SOFA build for everything: the optimiser (headless batch) and the
# interactive scenes both run on the emio-labs SOFA so their physics match —
# a gripper that grips in the optimiser grips the same way in visual mode.
#
# runSofa.exe, the plugin tree rooted at SOFA_ROOT, the SofaPython3
# site-packages and the bundled Python (which provides python310.dll) must all
# come from this same build or plugins fail to load with "The specified module
# could not be found" (ABI mismatch). SOFA_ROOT is FORCED (not setdefault) so a
# pre-existing machine SOFA_ROOT can't desync it from this build's runSofa.exe.
_EMIOLABS_SOFA_ROOT = (
    r"C:\Users\Cesar\AppData\Local\Programs\emio-labs\resources\sofa"
)
os.environ["SOFA_ROOT"] = _EMIOLABS_SOFA_ROOT
os.environ["RUNSOFA_EXE"] = rf"{_EMIOLABS_SOFA_ROOT}\bin\runSofa.exe"
os.environ["SOFA_SITE_PACKAGES"] = (
    rf"{_EMIOLABS_SOFA_ROOT}\plugins\SofaPython3\lib\python3\site-packages"
)
os.environ["SOFA_PYTHON_PATH"] = rf"{_EMIOLABS_SOFA_ROOT}\bin\python"
os.environ.setdefault(
    "EMIOLABS_RUNSOFA_EXE", rf"{_EMIOLABS_SOFA_ROOT}\bin\runSofa.exe"
)

os.environ.setdefault("SOFA_GUI", "batch")
os.environ.setdefault("HARD_FAIL_SCORE", "-3.0")

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from launcher.bootstrap import bootstrap_lab

SCRIPT_DIR, SRC_ROOT, APP_ROOT, LAB_ROOT = bootstrap_lab(__file__)

from dashboard.app import launch_dashboard

if __name__ == "__main__":
    launch_dashboard(port=8050, open_browser=True)
