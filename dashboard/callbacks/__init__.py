"""Callback registration for the lab's own dashboard tabs."""

from .generation import register_generation_callbacks
from .scenes import register_scene_callbacks

__all__ = [
    "register_generation_callbacks",
    "register_scene_callbacks",
]
