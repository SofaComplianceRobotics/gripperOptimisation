"""
Compatibility wrapper.

Use launch_optimize.py as the canonical entry point.
"""

import sys
from pathlib import Path

LAUNCH_DIR = Path(__file__).resolve().parents[1] / "launch"
if str(LAUNCH_DIR) not in sys.path:
    sys.path.insert(0, str(LAUNCH_DIR))

from launch_optimize import main


if __name__ == "__main__":
    main()
