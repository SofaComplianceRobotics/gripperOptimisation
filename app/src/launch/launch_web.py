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
_EMIOLABS_SOFA_BIN = r"C:\Users\Cesar\AppData\Local\Programs\emio-labs\resources\sofa\bin"
os.environ.setdefault(
    "EMIOLABS_RUNSOFA_EXE",
    os.path.join(_EMIOLABS_SOFA_BIN, "runSofa.exe"),
)

# Custom SOFA build — used for headless optimisation (batch mode, Python 3.12)
os.environ.setdefault("SOFA_ROOT", r"C:\dev\sofa\build")
os.environ.setdefault("RUNSOFA_EXE", r"C:\dev\sofa\build\bin\Release\runSofa.exe")
os.environ.setdefault("SOFA_GUI", "batch")
os.environ.setdefault(
    "SOFA_PYTHON_PATH",
    r"C:\Users\Cesar\AppData\Local\Programs\Python\Python312",
)
os.environ.setdefault(
    "SOFA_SITE_PACKAGES",
    r"C:\dev\sofa\build\lib\python3\site-packages",
)

LAB_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = LAB_ROOT / "app" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from analysis.dashboard import launch_dashboard

if __name__ == "__main__":
    launch_dashboard(port=8050, open_browser=True)
