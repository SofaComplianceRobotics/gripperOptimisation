"""Scoring helpers for the current grasp-hold benchmark."""

from __future__ import annotations

from pathlib import Path

from labtests.core.scoring import max_hold_score

SCORE_KEY = "score"
TEST_NAME = "grasp_hold"
TEST_LABEL = "Grasp Hold"
TEST_DESCRIPTION = "Current cube-lift benchmark"

# Max hold-time the single run can reach: scene length + overload, minus the
# pre-pickup gate. Derived from the recording so it tracks the scene timing.
_RECORDING = (
    Path(__file__).resolve().parents[2]
    / "runtime"
    / "recordings"
    / "grasp_hold"
    / "motor_recording.json"
)
MAX_SCORE = max_hold_score(_RECORDING, run_count=1)
