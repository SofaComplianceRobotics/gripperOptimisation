"""
Public API for gripper part builders.

Exports the primary builder functions and types used to construct gripper
geometry (ring, leg attachments, and pincers).

Exports:
    make_circle, make_leg_attachment, make_pincer_local,
    make_pincer_pair_world, make_pincer_pair_world_collision,
    ModelParams, PincerSplinePoint, PROFILE_EXTRUDE_MARGIN
"""

from .gripper_geometry import make_circle, make_leg_attachment
from .gripper_pincers import (
    make_pincer_local,
    make_pincer_pair_world,
    make_pincer_pair_world_collision,
)

from .params import ModelParams, PincerSplinePoint, PROFILE_EXTRUDE_MARGIN

__all__ = [
    "make_circle",
    "make_leg_attachment",
    "make_pincer_local",
    "make_pincer_pair_world",
    "make_pincer_pair_world_collision",
    "ModelParams",
    "PincerSplinePoint",
    "PROFILE_EXTRUDE_MARGIN",
]
