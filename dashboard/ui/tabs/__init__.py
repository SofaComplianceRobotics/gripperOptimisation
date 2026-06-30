"""Tab builders — individual dashboard tabs."""

from .config import build_config_tab
from .generate import build_generate_tab
from .scenes import build_scenes_tab
from .optimize import build_optimise_tab, PIE_PALETTE, _equal_split
from .performance import build_performance_tab
from .bounds import build_param_bounds_tab
from .progress import build_progress_tab
from .playground import build_playground_tab
from .styles import LOG_STYLE

__all__ = [
    "build_config_tab",
    "build_generate_tab",
    "build_scenes_tab",
    "build_optimise_tab",
    "build_performance_tab",
    "build_param_bounds_tab",
    "build_progress_tab",
    "build_playground_tab",
    "LOG_STYLE",
    "PIE_PALETTE",
    "_equal_split",
]
