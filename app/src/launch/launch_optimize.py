"""
Launch Optimize - Ensure lab dependencies are installed, then run optimize.py.

Reinstalls dependencies automatically when requirements.txt changes.
"""

import hashlib
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SRC_ROOT = SCRIPT_DIR.parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from labtests.ui import prompt_for_tests


# ─────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────
APP_ROOT = SRC_ROOT.parent
LAB_ROOT = APP_ROOT.parent
SITE_PACKAGES = LAB_ROOT / "runtime" / "modules" / "site-packages"
REQUIREMENTS = APP_ROOT / "requirements.txt"
REQ_HASH_FILE = LAB_ROOT / "runtime" / "modules" / ".requirements.sha256"


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────


def _requirements_hash(path: Path) -> str:
    """
    Compute SHA-256 hash of requirements.txt.

    Inputs:
        path (Path): Requirements file path.

    Returns:
        str: SHA-256 hex digest.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────


def main() -> None:
    """
    Install/refresh dependencies in modules/site-packages and launch optimize.py.

    Inputs:
        None

    Returns:
        None
    """
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SITE_PACKAGES) + os.pathsep + env.get("PYTHONPATH", "")

    selected_tests = prompt_for_tests(
        "Select ShapeOPT optimization tests", multi_select=True
    )
    env["LAB_SHAPEOPT_TESTS"] = ",".join(selected_tests)
    env["LAB_SHAPEOPT_TEST"] = selected_tests[0]

    if not REQUIREMENTS.exists():
        raise FileNotFoundError(f"Missing requirements file: {REQUIREMENTS}")

    required_hash = _requirements_hash(REQUIREMENTS)
    installed_hash = (
        REQ_HASH_FILE.read_text(encoding="utf-8").strip()
        if REQ_HASH_FILE.exists()
        else ""
    )

    if installed_hash != required_hash:
        SITE_PACKAGES.mkdir(parents=True, exist_ok=True)
        subprocess.check_call(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--target",
                str(SITE_PACKAGES),
                "-r",
                str(REQUIREMENTS),
            ]
        )
        REQ_HASH_FILE.parent.mkdir(parents=True, exist_ok=True)
        REQ_HASH_FILE.write_text(required_hash, encoding="utf-8")
        print("Dependencies installed/updated.")
    else:
        print("Dependencies already up to date.")

    subprocess.check_call(
        [sys.executable, str(APP_ROOT / "src" / "optimization" / "optimize.py")],
        env=env,
    )


if __name__ == "__main__":
    main()
