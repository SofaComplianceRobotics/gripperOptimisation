"""Tab builders for the lab's own dashboard tabs."""

from .generate import build_generate_tab
from .scenes import build_scenes_tab

__all__ = [
    "build_generate_tab",
    "build_scenes_tab",
]
