"""Weight-search helpers for random_cube_pick.

This module provides a stable, small public surface for selecting candidate
weights and recording their results. Internally the implementation is split
across smaller modules for persistence, state manipulation, ladder math and
UI snapshot rendering.
"""

from .common import (
    CubeSearchSpec,
    weight_points_for_index,
    boundary_score_for_index,
    DEFAULT_WEIGHT_MIN,
    DEFAULT_WEIGHT_MAX,
    DEFAULT_WEIGHT_STEP,
)
from .api import select_cube_spec, record_cube_result
from .ladder import build_search_snapshot

__all__ = [
    "CubeSearchSpec",
    "weight_points_for_index",
    "boundary_score_for_index",
    "DEFAULT_WEIGHT_MIN",
    "DEFAULT_WEIGHT_MAX",
    "DEFAULT_WEIGHT_STEP",
    "select_cube_spec",
    "record_cube_result",
    "build_search_snapshot",
]
