"""Shared types and constants for the weight-search helpers.

This module centralises the simple, stable data shapes and constants used by
the other helper modules. Keeping these tiny primitives here helps avoid
import cycles while making the public surface of the weight-search helpers
easy to import from a single place.
"""

from dataclasses import dataclass
from pathlib import Path

# File used to persist ladder state for all run slots.
STATE_FILE_NAME = "random_cube_pick_weight_search.json"

# Defaults for the weight search ladder (kg).
DEFAULT_WEIGHT_MIN = 0.02
DEFAULT_WEIGHT_MAX = 0.2
DEFAULT_WEIGHT_STEP = 0.02

# The cycle of cube sizes this helper uses. Each slot maps onto one entry in
# this tuple (indexing starts at 1). Repeating sizes is intentional so the
# scene can request the same size multiple times in a row.
_CUBE_SIZE_CYCLE = (
    [8.0, 8.0, 8.0],
    [10.0, 10.0, 10.0],
    [20.0, 20.0, 20.0],
)


@dataclass(frozen=True)
class CubeSearchSpec:
    """Chosen size/weight for one run slot.

    Attributes:
        run_slot (int): The slot number used to pick which cube size to use.
        cube_scale (list[float]): The 3D scale for the cube.
        cube_mass (float): The mass/weight selected for the cube (kg).
        weight_index (int): Index into the ladder's ``weight_levels`` list.
        weight_levels (list[float]): Available weight levels for the ladder.
        lower_index (int): Current lower-bound index for the binary search.
        upper_index (int): Current upper-bound index for the binary search.
        status (str): Small status string describing how the candidate was
            chosen (e.g. "binary_search", "seeded", "converged").
    """

    run_slot: int
    cube_scale: list
    cube_mass: float
    weight_index: int
    weight_levels: list
    lower_index: int
    upper_index: int
    status: str


def weight_points_for_index(weight_index: int) -> int:
    """Return the 1-based ladder score for a selected weight index.

    The scoring used by the UI treats index 0 as 1 point, index 1 as 2, and
    so on. Negative indexes map to zero.

    Args:
        weight_index (int): Integer index in the ladder.

    Returns:
        int: 1-based point value for the index (0 for negative inputs).
    """
    return max(0, int(weight_index) + 1)


def boundary_score_for_index(weight_index: int) -> int:
    """Return the score earned by confirming a successful ladder boundary.

    If the index is negative (no boundary) this returns zero.
    """
    return weight_points_for_index(weight_index) if weight_index >= 0 else 0
