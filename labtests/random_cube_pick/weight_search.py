"""Weight-search helpers for random_cube_pick.

This module provides a stable, small public surface for selecting candidate
weights and recording their results. Internally the implementation is split
across smaller modules for persistence, state manipulation, ladder math and
UI snapshot rendering. Importing from this module yields the original
convenience functions used by the rest of the codebase.
"""

from pathlib import Path

from .weight_search_common import (
    CubeSearchSpec,
    weight_points_for_index,
    boundary_score_for_index,
)
from .weight_search_api import select_cube_spec, record_cube_result
from .weight_search_ladder import build_search_snapshot

__all__ = [
    "CubeSearchSpec",
    "weight_points_for_index",
    "boundary_score_for_index",
    "select_cube_spec",
    "record_cube_result",
    "build_search_snapshot",
]
