"""Scoring helpers for the tilt benchmark."""

from __future__ import annotations

SCORE_KEY = "score"
TEST_NAME = "tilt"
TEST_LABEL = "Tilt"
TEST_DESCRIPTION = "Tilt alignment benchmark"
MAX_SCORE = 40.0


def compute_tilt_score(max_y_spreads):
    """Compute the tilt test score from per-waypoint Y-spread penalties.

    Args:
        max_y_spreads (list[float]): Maximum Y-spread at each waypoint.

    Returns:
        float: Score in (-inf, 40.0]; higher is better.

    Raises:
        ValueError: If max_y_spreads does not contain exactly two values.
    """
    if not max_y_spreads or len(max_y_spreads) != 2:
        raise ValueError("Expected two max_y_spread values (one per waypoint)")
    return 40.0 - max_y_spreads[0] - max_y_spreads[1]
