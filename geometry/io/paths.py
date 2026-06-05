"""Path resolution and file utilities.

Handles configuration of export directories and path resolution
for gripper model output files.
"""

from pathlib import Path

from geometry.params import ModelParams

CORE_ROOT = Path(__file__).resolve().parent.parent
LAB_ROOT = CORE_ROOT.parent
APP_ROOT = LAB_ROOT


def make_versioned_export_path(p: ModelParams, extension: str) -> Path:
    """
    Build a fixed export path inside the configured export directory.

    Args:
        p: Model parameters.
        extension: File extension, with or without leading dot.

    Returns:
        Full output path using the base filename new_gripper.
    """
    out_dir = LAB_ROOT / p.export_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    ext = extension.lstrip(".")
    return out_dir / f"{p.export_stem}.{ext}"
