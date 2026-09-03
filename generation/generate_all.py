"""
Lab Generation - dashboard "Generate" button entrypoint.

Runs the gripper and leg generation scripts back to back from the same
lab_config.jsonc, so hitting one button produces both parts. Kept as a
separate combined script (rather than folding leg generation into
generate_gripper.py) so the optimizer's prepare_trial hook — which needs the
two parts as trial-unique, independently-named files — can keep calling
generate_gripper.py / generate_leg.py directly without this script's
overhead or its shared, non-trial-unique output names.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

GENERATION_DIR = Path(__file__).resolve().parent


def main() -> None:
    for script in ("generate_gripper.py", "generate_leg.py"):
        print(f"--- {script} ---", flush=True)
        subprocess.run([sys.executable, str(GENERATION_DIR / script)], check=True)


if __name__ == "__main__":
    main()
