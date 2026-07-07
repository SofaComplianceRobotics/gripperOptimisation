"""
Shared scoring helpers for all ShapeOPT tests.

Score/status writing itself is sofaopt's job now — scenes call
``trial.attach(rootnode)`` and use ``trial.write_status`` /
``trial.write_score`` / ``trial.prune``. What stays here is the
lab-specific score ceiling derived from a motor recording.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from labtests.core import scene_defaults


def _env_float(name: str, default: float) -> float:
    """Read a float env override, falling back to the given default."""
    raw = os.environ.get(name)
    try:
        return float(raw) if raw not in (None, "") else default
    except ValueError:
        return default


def max_hold_score(recording_file: str | Path, run_count: int = 1) -> float:
    """Return the maximum achievable hold-time score for a motor-playback test.

    The score a run writes is ``hold_time``: seconds the cube stays above the
    pickup threshold, accumulated only after the ``early_stop_sim_time`` gate.
    A flawless run picks the cube up before that gate and holds it to the
    horizon, so the ceiling is the whole timeline minus the pre-pickup window:

        recorded_duration + overload_time - early_stop_sim_time

    summed over ``run_count`` sims (the per-size runs are summed into one test
    score). Deriving this from the recording length and scene_defaults keeps it
    in lockstep with the scene timing, so a 100% hold always normalizes to 1.0.

    Args:
        recording_file: Path to the test's motor_recording.json.
        run_count: Number of sims summed into the test score.

    Returns:
        Maximum achievable summed hold-time score, or 1.0 if the recording
        cannot be read (no normalization effect).
    """
    try:
        data = json.loads(Path(recording_file).read_text(encoding="utf-8"))
        frames = data.get("motor_positions") or []
        recording_dt = float(data.get("dt") or 0.0)
    except Exception:
        return 1.0
    if recording_dt <= 0.0 or not frames:
        return 1.0

    time_scale = max(
        1e-6, _env_float("PLAYBACK_TIME_SCALE", scene_defaults.PLAYBACK_TIME_SCALE)
    )
    recorded_duration = len(frames) * recording_dt / time_scale
    overload = _env_float("OVERLOAD_MAX_TIME", scene_defaults.OVERLOAD_MAX_TIME)
    early_stop = _env_float("EARLY_STOP_SIM_TIME", scene_defaults.EARLY_STOP_SIM_TIME)

    per_sim = max(0.0, recorded_duration + overload - early_stop)
    return per_sim * max(1, int(run_count))
