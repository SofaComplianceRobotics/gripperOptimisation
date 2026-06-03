"""
optimize_utils.py — Miscellaneous utility functions for trial and directory management.

Provides directory setup, file utilities, and misc logging functions.
"""

import shutil
import threading
import time
from pathlib import Path

from optimization.optimize_config import TRIALS_DIR, PREVIEWS_DIR, PRINT_CLEANUP_LOGS


def reset_trials_dir() -> None:
    """Wipe the entire trials directory and recreate it fresh, including the previews folder."""
    if TRIALS_DIR.exists():
        shutil.rmtree(TRIALS_DIR)
        print(f"[reset] Cleared {TRIALS_DIR}")
    TRIALS_DIR.mkdir(parents=True)
    PREVIEWS_DIR.mkdir()


def delete_after_delay(path: Path, delay: float) -> None:
    """Delete a file after a delay in a background daemon thread.

    Args:
        path: File to delete.
        delay: Seconds to wait before deleting.
    """

    def _delete():
        time.sleep(delay)
        try:
            path.unlink()
            if PRINT_CLEANUP_LOGS:
                print(f"[cleanup] Deleted {path.name}")
        except FileNotFoundError:
            pass

    threading.Thread(target=_delete, daemon=True).start()


def cleanup_collision_stls(collision_stls_by_trial: dict[int, Path]) -> None:
    """Delete all collision STL files in a generation's stash.

    Args:
        collision_stls_by_trial: Mapping of trial index to collision STL path.
    """
    for collision_stl in collision_stls_by_trial.values():
        try:
            if collision_stl.exists():
                collision_stl.unlink()
                if PRINT_CLEANUP_LOGS:
                    print(f"[cleanup] Deleted {collision_stl.name}")
        except Exception:
            pass
