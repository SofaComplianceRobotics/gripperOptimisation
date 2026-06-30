"""Callback registration modules for the ShapeOPT dashboard."""

from .config import register_config_callbacks
from .generation import register_generation_callbacks
from .scenes import register_scene_callbacks
from .optimize import register_optimise_callbacks
from .monitoring import register_monitoring_callbacks
from .playground import register_playground_callbacks

__all__ = [
    "register_config_callbacks",
    "register_generation_callbacks",
    "register_scene_callbacks",
    "register_optimise_callbacks",
    "register_monitoring_callbacks",
    "register_playground_callbacks",
]