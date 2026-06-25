"""Scoring helpers for the random cube benchmark."""

from __future__ import annotations

from pathlib import Path

from labtests.core.scoring import max_hold_score

SCORE_KEY = "score"
TEST_NAME = "random_cube_pick"
TEST_LABEL = "Random Cube"
TEST_DESCRIPTION = "Cube pickup hold-time benchmark across 3 cube sizes"

# Hold-time summed over the three cube sizes. Each size's ceiling is the scene
# length + overload minus the pre-pickup gate; derived from the recording so a
# perfect hold across all three sizes normalizes to 1.0.
_RECORDING = (
    Path(__file__).resolve().parents[2]
    / "runtime"
    / "recordings"
    / "random_cube_pick"
    / "motor_recording.json"
)
MAX_SCORE = max_hold_score(_RECORDING, run_count=3)
