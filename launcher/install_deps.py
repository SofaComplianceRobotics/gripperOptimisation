"""
install_deps.py — Install sofaopt and this lab's Python dependencies.

Triggered from the lab's #python-button, which EmioLabs runs with the
emio-labs bundled Python already first on PATH (see launcher/bootstrap.py's
resolve_sofa_runtime for the equivalent used by the other scripts). That
means sys.executable here already *is* the right interpreter — no path
hunting needed, unlike a plain terminal session.

Click once after installing/updating the lab. Safe to click again later
(git pull / pip install are both idempotent).
"""

import shutil
import subprocess
import sys
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[1]
SOFAOPT_DIR = Path.home() / "Documents" / "SofaOptimisation"
SOFAOPT_ZIP_URL = "https://github.com/SofaComplianceRobotics/SofaOptimisation/archive/refs/heads/main.zip"
REQUIREMENTS = LAB_ROOT / "tools" / "requirements-bundle.txt"
# Applied to every pip install below. This runs against the shared emio-labs
# SOFA Python, so numpy/cadquery must stay at the versions emioapi and the
# other labs expect (see tools/constraints.txt).
CONSTRAINTS = LAB_ROOT / "tools" / "constraints.txt"


def run(cmd: list[str]) -> None:
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def install_sofaopt() -> None:
    """Editable install via a local git clone/pull when git is available
    (lets a dev edit sofaopt in place); otherwise install straight from
    GitHub's zip download, which needs nothing but pip."""
    if shutil.which("git"):
        if (SOFAOPT_DIR / ".git").is_dir():
            print(f"sofaopt already cloned at {SOFAOPT_DIR}, updating to origin/main...")
            # The lab consumes stock sofaopt main. Pin the checkout there before
            # pulling so a clone left on a local feature branch (or with an
            # unrelated upstream) still lands on the version the lab expects.
            run(["git", "-C", str(SOFAOPT_DIR), "fetch", "origin", "main"])
            run(["git", "-C", str(SOFAOPT_DIR), "checkout", "main"])
            run(["git", "-C", str(SOFAOPT_DIR), "merge", "--ff-only", "origin/main"])
        else:
            print(f"Cloning sofaopt into {SOFAOPT_DIR}...")
            run(["git", "clone", "https://github.com/SofaComplianceRobotics/SofaOptimisation.git", str(SOFAOPT_DIR)])
        run([sys.executable, "-m", "pip", "install", "-c", str(CONSTRAINTS), "-e", f"{SOFAOPT_DIR}[dashboard,preview]"])
    else:
        print("git not found — installing sofaopt directly from GitHub (not editable).")
        run([sys.executable, "-m", "pip", "install", "-c", str(CONSTRAINTS), f"sofaopt[dashboard,preview] @ {SOFAOPT_ZIP_URL}"])


def install_lab_requirements() -> None:
    run([sys.executable, "-m", "pip", "install", "-c", str(CONSTRAINTS), "-r", str(REQUIREMENTS)])


if __name__ == "__main__":
    print(f"Using Python: {sys.executable}")
    install_sofaopt()
    install_lab_requirements()
    print("\nDone. You can close this window and use the lab's other buttons now.")
