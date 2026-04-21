"""
Launch Optimize - run the optimization loop against the custom SOFA build.

This keeps the lab's current 3.10-based working environment intact while
pointing SOFA subprocesses to the separate custom 3.12 build.
"""

import os

from launch_optimize import main as launch_default_optimize


def main() -> None:
    """
    Set custom SOFA environment variables and launch optimize.py.

    Inputs:
        None

    Returns:
        None
    """
    # Prevent inherited EmioLabs Python settings from leaking into SofaPython3.
    for key in (
        "PYTHONHOME",
        "PYTHONSTARTUP",
        "PYTHONUSERBASE",
        "PYTHONEXECUTABLE",
    ):
        os.environ.pop(key, None)

    os.environ["SOFA_ROOT"] = r"C:\dev\sofa\build"
    os.environ["RUNSOFA_EXE"] = r"C:\dev\sofa\build\bin\Release\runSofa.exe"
    os.environ["SOFA_GUI"] = "batch"
    os.environ["SOFA_PYTHON_PATH"] = (
        r"C:\Users\Cesar\AppData\Local\Programs\Python\Python312"
    )
    os.environ["SOFA_SITE_PACKAGES"] = r"C:\dev\sofa\build\lib\python3\site-packages"
    launch_default_optimize()


if __name__ == "__main__":
    main()
