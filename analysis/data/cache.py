"""Data loading and caching: trials, summaries, and trial state."""

import json
import time
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────
LAB_ROOT = Path(__file__).resolve().parents[2]
TRIALS_DIR = LAB_ROOT / "runtime" / "trials"

# Caches & module-level state
_MAX_SCORE_CACHE: dict[str, float] = {}
_DATA_CACHE: dict = {"records": [], "summaries": [], "last_load": 0.0}


def _read_json(path: Path) -> dict | None:
    """Safely read and parse a JSON file, returning None on error."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_trial_state(trial_record: dict) -> dict | None:
    """Load the saved `trial_state.json` for a given trial record.

    Args:
        trial_record: Trial metadata record containing gen/trial names.

    Returns:
        Parsed trial state dict, or None if missing/unreadable.
    """
    trial_path = (
        TRIALS_DIR
        / trial_record.get("gen_name", "")
        / trial_record.get("trial_name", "")
        / "trial_state.json"
    )
    if not trial_path.exists():
        return None
    return _read_json(trial_path)


def _load_data():
    """Load and cache trial records and generation summaries.

    Returns:
        Tuple of (records, summaries). Uses a short-lived cache to avoid
        excessive disk reads.
    """
    from analyze_config import LIVE_REFRESH_SECONDS
    from analyze_io import load_all_trials, load_gen_summaries

    try:
        now = time.time()
        if _DATA_CACHE.get("records") and (
            now - float(_DATA_CACHE.get("last_load", 0))
        ) < max(0.5, float(LIVE_REFRESH_SECONDS)):
            return _DATA_CACHE["records"], _DATA_CACHE["summaries"]

        records = load_all_trials()
        summaries = load_gen_summaries()
        _DATA_CACHE["records"] = records
        _DATA_CACHE["summaries"] = summaries
        _DATA_CACHE["last_load"] = now
        return records, summaries
    except Exception as exc:
        print(f"[warn] Error loading data: {exc}")
        return (
            _DATA_CACHE.get("records", []) or [],
            _DATA_CACHE.get("summaries", []) or [],
        )


def _current_generation_records(records: list[dict]) -> list[dict]:
    """Return records belonging to the most recent generation.

    Args:
        records: Full list of trial records.

    Returns:
        Filtered and sorted list for the current generation.
    """
    if not records:
        return []
    current_gen = max(
        (record.get("gen_index", -1) for record in records),
        default=-1,
    )
    if current_gen < 0:
        return []
    result = [r for r in records if r.get("gen_index", -1) == current_gen]
    return sorted(result, key=lambda r: r.get("trial_index", 0))
