"""Scoring helpers for the random cube benchmark."""

from __future__ import annotations

SCORE_KEY = "score"
TEST_NAME = "random_cube_pick"
TEST_LABEL = "Random Cube"
TEST_DESCRIPTION = "Cube pickup hold-time benchmark across 3 cube sizes"
# Hold-time scored like grasp_hold (max 8.06 per run), summed over 3 cube sizes.
MAX_SCORE = 24.18
