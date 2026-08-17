"""motor_recorder — Capture motor positions frame-by-frame and autosave to JSON.

Shared by the interactive recording scene (a human drives the target via
ProgramWindow) and the automated per-trial recorder (which replays the
captured target path through a different geometry's own inverse solver):
both just need to append one frame of state per animation step and
periodically flush to disk.

When `target_mo`/`rest_lengths` are given, the recorder also captures the
effector target's Cartesian pose and the gripper opening every frame
("target_poses" / "gripper_openings"). That's what makes the recording
replayable: the per-trial recorder drives a *different* trial's geometry
along this exact captured path (frame-for-frame, same DT_INVERSE) instead of
reinterpreting the source .crprog itself, so it doesn't need to reverse
engineer ProgramWindow's own (closed-source, GUI-only) playback logic.
"""

from __future__ import annotations

import json
from pathlib import Path


class MotorRecorder:
    """Accumulates motor positions (and optionally target pose / gripper
    opening) and autosaves them to `output_file`."""

    def __init__(
        self,
        emio,
        output_file: str | Path,
        dt: float,
        save_interval: float = 1.0,
        target_mo=None,
        rest_lengths=None,
    ):
        """Args:
            emio: The assembled Emio object (source of `.motors`).
            output_file: Path to write the recording JSON to.
            dt: Simulation timestep, recorded alongside the positions.
            save_interval: Seconds of sim time between autosave flushes.
            target_mo: Optional effector-target MechanicalState (Rigid3) to
                also capture as "target_poses" every frame.
            rest_lengths: Optional gripper DistanceMapping.restLengths data
                to also capture as "gripper_openings" every frame.
        """
        self.emio = emio
        self.output_file = Path(output_file)
        self.save_interval = save_interval
        self.target_mo = target_mo
        self.rest_lengths = rest_lengths
        self.state = {"motor_positions": [], "timestamps": [], "start_time": None, "dt": dt}
        if target_mo is not None:
            self.state["target_poses"] = []
        if rest_lengths is not None:
            self.state["gripper_openings"] = []
        self.capture_start_time: float | None = None
        self._last_save_time = 0.0

    def capture_frame(self, current_time: float) -> None:
        """Record one frame of state at `current_time`."""
        if self.state["start_time"] is None:
            self.state["start_time"] = current_time
        if self.capture_start_time is None:
            self.capture_start_time = current_time

        positions = [
            float(motor.getMechanicalState().position.value[0][0]) for motor in self.emio.motors
        ]
        self.state["motor_positions"].append(positions)
        self.state["timestamps"].append(current_time - self.capture_start_time)

        if self.target_mo is not None:
            self.state["target_poses"].append([float(v) for v in self.target_mo.position.value[0]])
        if self.rest_lengths is not None:
            self.state["gripper_openings"].append(float(self.rest_lengths.value[0]))

        if current_time - self._last_save_time >= self.save_interval:
            self._last_save_time = current_time
            self.save()

    def save(self) -> None:
        """Flush the accumulated recording to `output_file`."""
        try:
            self.output_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.output_file, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2)
        except Exception as exc:
            print(f"[MotorRecorder] save error: {exc}")

    @property
    def frame_count(self) -> int:
        return len(self.state["motor_positions"])
