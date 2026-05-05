"""
motor_playback — Load a recorded motor trajectory and wire up JointConstraints.

Used by all direct-mode tests (grasp_hold, random_cube_pick, etc.) so a
controller can replay motor positions frame-by-frame via PlaybackHandles.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import NamedTuple


class PlaybackHandles(NamedTuple):
    """Everything a playback controller needs from this module."""

    motor_positions: list[list[float]]
    joint_constraints: list[object]
    num_motors: int
    recording_dt: float  # time step used when recording (may differ from sim DT)


def setup(emio, record_file: str | Path) -> PlaybackHandles:
    """Load a motor recording and attach JointConstraints to all motors.

    The recording file must be a JSON object with a "motor_positions" key whose
    value is a list of frames, each frame being a list of motor angles.

    Args:
        emio: The assembled Emio object from base_scene.
        record_file: Path to the motor_recording.json file for this test.

    Returns:
        PlaybackHandles with (motor_positions, joint_constraints, num_motors).

    Raises:
        FileNotFoundError: If record_file does not exist.
        ValueError: If the recording contains no frames.
    """
    record_file = Path(record_file)
    if not record_file.exists():
        raise FileNotFoundError(
            f"[motor_playback] Recording not found: {record_file}\n"
            "Run the scene in recording mode first to capture motor positions."
        )

    with open(record_file, "r", encoding="utf-8") as f:
        recording_data = json.load(f)

    motor_positions: list[list[float]] = recording_data["motor_positions"]
    if not motor_positions:
        raise ValueError(f"[motor_playback] Recording is empty: {record_file}")

    recording_dt = float(recording_data.get("dt", 0.01))
    num_motors = len(emio.motors)
    print(
        f"[motor_playback] Loaded {len(motor_positions)} frames "
        f"(recording_dt={recording_dt}s) "
        f"for {num_motors} motors from {record_file.name}"
    )

    joint_constraints: list[object] = []
    for i, motor in enumerate(emio.motors):
        constraint = motor.addObject(
            "JointConstraint",
            name=f"MotorActuator{i}",
            minDisplacement=-math.pi,
            maxDisplacement=math.pi,
            index=0,
            value=0,
            valueType="displacement",
        )
        joint_constraints.append(constraint)

    return PlaybackHandles(motor_positions, joint_constraints, num_motors, recording_dt)
