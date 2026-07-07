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

from launcher.bootstrap import bootstrap_lab, resolve_sofa_runtime

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
_sofa = resolve_sofa_runtime()

os.environ["SOFA_ROOT"] = _sofa["sofa_root"]
os.environ["RUNSOFA_EXE"] = _sofa["runsofa_exe"]
os.environ["SOFA_SITE_PACKAGES"] = _sofa["site_packages"]
os.environ["SOFA_PYTHON_PATH"] = _sofa["python_dir"]
if _sofa["python_exe"]:
    os.environ["SOFA_PYTHON_EXE"] = _sofa["python_exe"]
os.environ.setdefault("EMIOLABS_RUNSOFA_EXE", _sofa["runsofa_exe"])

bootstrap_lab(__file__)

from dashboard.app import launch_dashboard

if __name__ == "__main__":
    launch_dashboard(port=8050, open_browser=True)
