"""Scoring helpers for the reach-zone (effective workspace) benchmark."""

from __future__ import annotations

SCORE_KEY = "score"
TEST_NAME = "reach_zone"
TEST_LABEL = "Reach Zone"
TEST_DESCRIPTION = "Volume of the 3D zone the gripper+leg combo can actually reach"

# cm^3. Rough placeholder -- no run has been observed yet to calibrate
# against. A ~60mm-radius, 120mm-tall cylinder is ~1360cm^3 analytically,
# but the sweep's coarse 6-direction/3-level mesh underestimates a curved
# boundary substantially (~45% of true volume against a synthetic sphere in
# testing), so the realistic ceiling here is well below that. Recompute once
# real scores come in: MAX_SCORE should sit at the highest realistic volume,
# not an invented ceiling.
MAX_SCORE = 700.0
