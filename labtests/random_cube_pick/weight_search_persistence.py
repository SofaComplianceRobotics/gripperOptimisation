"""Persistence and file-lock helpers for weight search state.

This module provides the minimal, well-documented helpers used to locate the
state file, read and write it atomically, and coordinate simple filesystem
locking so concurrent processes do not corrupt the shared JSON state.
"""

import json
import os
import time
from pathlib import Path

from .weight_search_common import STATE_FILE_NAME


def _state_path(lab_root: Path) -> Path:
    """Return the canonical path to the persisted state file for the lab.

    Args:
        lab_root (Path): Root path for the lab workspace.

    Returns:
        Path: Path to the JSON state file inside the runtime directory.
    """
    return Path(lab_root) / "runtime" / STATE_FILE_NAME


def _resolve_state_path(lab_root: Path, state_path: Path | None = None) -> Path:
    """Return an explicit path when given, otherwise the canonical state path.

    This helper is small but makes the calling code clearer by resolving the
    optional ``state_path`` parameter in a single place.
    """
    if state_path is not None:
        return Path(state_path)
    return _state_path(lab_root)


def _lock_path(path: Path) -> Path:
    """Return the filesystem lock path associated with a state file path."""
    return path.with_suffix(path.suffix + ".lock")


def _acquire_lock(lock_path: Path, timeout_s: float = 5.0) -> bool:
    """Try to create a filesystem lock file within ``timeout_s``.

    The implementation is deliberately small: it uses ``os.open`` with the
    O_EXCL flag to atomically create the lock file. This avoids races on
    platforms where rename/replace semantics are weak.

    Args:
        lock_path (Path): Path to attempt to create as a lock file.
        timeout_s (float): Number of seconds to retry creating the lock.

    Returns:
        bool: True when the lock was acquired, False otherwise.
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return True
        except FileExistsError:
            time.sleep(0.01)
        except Exception:
            return False
    return False


def _release_lock(lock_path: Path) -> None:
    """Remove the filesystem lock file if it exists.

    This function intentionally ignores errors to keep callers simple: lock
    release should not raise during normal operation.
    """
    try:
        if lock_path.exists():
            lock_path.unlink()
    except Exception:
        pass


def _read_state(path: Path) -> dict:
    """Read JSON state from ``path`` and return a dict on success.

    On any error this returns an empty dict so callers can handle the missing
    or corrupted state in a robust way.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _write_state(path: Path, payload: dict) -> None:
    """Atomically write ``payload`` as JSON to ``path``.

    The function writes to a temporary sibling file and replaces the target
    path to avoid partial writes being observed by readers.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)
