"""Scene path bootstrapping for SOFA-run scene scripts."""

import sys
from pathlib import Path


def ensure_scene_paths(scene_file: str | Path) -> tuple[Path, Path, Path, Path]:
    """Resolve path roots and insert them into sys.path.

    Walks up from the calling scene script to find the directory that contains
    the ``labtests/`` folder, then adds lab_root, app_root, and src_root to
    sys.path so all project imports work regardless of how SOFA launched the script.

    Args:
        scene_file: The ``__file__`` attribute of the calling scene script.

    Returns:
        Tuple of (script_dir, src_root, app_root, lab_root).
    """
    script_dir = Path(scene_file).resolve().parent
    src_root = next(
        (c for c in (script_dir, *script_dir.parents) if (c / "labtests").is_dir()),
        script_dir.parents[1],
    )
    app_root = src_root.parent
    lab_root = app_root.parent
    for candidate in (str(lab_root), str(app_root), str(src_root)):
        if candidate not in sys.path:
            sys.path.insert(0, candidate)
    return script_dir, src_root, app_root, lab_root
