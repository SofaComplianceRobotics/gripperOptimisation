"""
analyze_config.py — Configuration and constants for results analysis.

Centralizes all analysis-related configuration including paths, UI constants,
and scoring parameters.
"""

import os
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[1]
TRIALS_DIR = LAB_ROOT / "runtime" / "trials"

TOP_X = 10  # Number of top trials to display in leaderboard
CENTERED_AVG_HALF_WINDOW = 10  # Window size for rolling average plot
LIVE_REFRESH_SECONDS = 2.0  # Refresh interval for live monitoring

HARD_FAIL_SCORE = float(os.environ.get("HARD_FAIL_SCORE", "-3.0"))
SCORE_AGGREGATION = os.environ.get("SCORE_AGGREGATION", "mean").strip().lower()
