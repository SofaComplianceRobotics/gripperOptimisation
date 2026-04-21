"""
Launch the standalone SOFA scene against the custom SOFA build.

This keeps the lab's current 3.10-based working environment intact while
pointing the scene runner to the separate custom 3.12 build.
"""

import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SRC_ROOT = SCRIPT_DIR.parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from labtests.registry import get_test_spec
from labtests.ui import prompt_for_tests


APP_ROOT = SRC_ROOT.parent
LAB_ROOT = APP_ROOT.parent
ASSETS_ROOT = LAB_ROOT.parent.parent
RUNSOFA_EXE = r"C:\dev\sofa\build\bin\Release\runSofa.exe"
SOFA_ROOT = r"C:\dev\sofa\build"
SOFA_PYTHON_PATH = r"C:\Users\Cesar\AppData\Local\Programs\Python\Python312"
SOFA_SITE_PACKAGES = r"C:\dev\sofa\build\lib\python3\site-packages"


def main() -> None:
    """
    Launch the scene with the custom SOFA GUI stack.

    Inputs:
        None

    Returns:
        None
    """
    env = os.environ.copy()

    # Prevent inherited EmioLabs Python settings from polluting SofaPython3 init.
    for key in (
        "PYTHONHOME",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "PYTHONUSERBASE",
        "PYTHONEXECUTABLE",
    ):
        env.pop(key, None)

    env["SOFA_ROOT"] = SOFA_ROOT
    env["SOFAPYTHON3_ROOT"] = SOFA_ROOT
    env["SOFA_PYTHON_PATH"] = SOFA_PYTHON_PATH
    env["SOFA_SITE_PACKAGES"] = SOFA_SITE_PACKAGES
    env["PATH"] = (
        os.path.join(SOFA_ROOT, "bin", "Release")
        + ";"
        + os.path.join(SOFA_ROOT, "bin")
        + ";"
        + SOFA_PYTHON_PATH
        + ";"
        + env.get("PATH", "")
    )
    env["PYTHONPATH"] = (
        SOFA_SITE_PACKAGES
        + ";"
        + os.path.join(SOFA_ROOT, "plugins", "STLIB")
        + ";"
        + str(ASSETS_ROOT)
    )

    selected_tests = prompt_for_tests("Select ShapeOPT scene test", multi_select=False)
    test_name = selected_tests[0]
    test_spec = get_test_spec(test_name)
    env["LAB_SHAPEOPT_TEST"] = test_name
    env["LAB_SHAPEOPT_TESTS"] = test_name

    default_stl = LAB_ROOT / "runtime" / "exports" / "new_gripper_collision.stl"
    if default_stl.exists():
        env.setdefault("OPTUNA_STL_PATH", str(default_stl))

    subprocess.check_call(
        [
            RUNSOFA_EXE,
            "-l",
            "SofaImGui",
            "-l",
            "SofaPython3",
            "-g",
            "imgui",
            str(test_spec.scene_file),
        ],
        cwd=str(ASSETS_ROOT),
        env=env,
    )


if __name__ == "__main__":
    main()
