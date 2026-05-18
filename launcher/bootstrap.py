"""Bootstrap helper for lab runtime.

Provides `bootstrap_lab()` to set LAB_ROOT, insert repo roots into sys.path,
and set up lab-local site-packages. Intended to replace ad-hoc sys.path edits
in scene scripts and launchers.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Tuple


def bootstrap_lab(script_file: str) -> Tuple[Path, Path, Path, Path]:
    """Locate the lab root from a script path and ensure repo paths are on sys.path.

    Args:
        script_file: Path to the calling script (typically __file__).

    Returns:
        A tuple (script_dir, src_root, app_root, lab_root).
    """
    script_dir = Path(script_file).resolve().parent
    lab_root = next(
        (
            c
            for c in (script_dir, *script_dir.parents)
            if (c / "config" / "lab_config.jsonc").is_file()
            and (c / "runtime").is_dir()
        ),
        script_dir,
    )
    src_root = lab_root
    app_root = lab_root
    lab_site = lab_root / "runtime" / "modules" / "site-packages"

    for candidate in (str(lab_root), str(lab_site)):
        if candidate and candidate not in sys.path:
            sys.path.insert(0, candidate)

    return script_dir, src_root, app_root, lab_root
