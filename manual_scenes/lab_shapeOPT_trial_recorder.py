"""
Lab ShapeOPT Trial Recorder - Headless per-trial motor trajectory recording.

Launched by sofaopt_project.py's prepare_trial hook (never by hand): replays
a captured effector-target path (position/orientation + gripper opening,
one frame per physics step) through the inverse solver for THIS trial's own
gripper/leg geometry (OPT_LEG_NAME, already read by base_scene.py), and
records the resulting motor angles. That recording is what motor_playback.py
replays in the direct-mode test for this trial, instead of a single
recording shared across every geometry.

Why replay a captured path instead of the source .crprog: SOFA's own
ProgramWindow (the thing that actually plays a .crprog when you press Play in
the interactive Recording scene) has no headless entry point — only
addGripper()/importProgram() are exposed, nothing to trigger playback. So
instead of reimplementing its interpolation/timing by hand, the Recording
scene captures the exact frame-by-frame path ProgramWindow produced
(target_poses/gripper_openings, alongside the motor recording it already
made) and this scene just replays that path verbatim, frame for frame, at
the same DT_INVERSE both scenes share. No interpolation to get wrong.

Required env vars:
    OPT_MOTOR_RECORDING_OUT   Path to write the resulting motor_recording.json.
Optional:
    OPT_REFERENCE_RECORDING   Path to the source recording to replay (must
                              contain "target_poses"/"gripper_openings" —
                              re-record via the interactive Recording scene
                              if it doesn't). Defaults to
                              runtime/recordings/grasp_hold/motor_recording.json.

Runs to completion and hard-kills its own process (matches the
os.kill(pid, 9) convention sofaopt's ScoreWriter uses to end optimizer runs —
batch-mode runSofa has no other exit path).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Launched via sofaopt_project.py's from-scratch scene env (like grasp_hold,
# random_cube_pick), not the dashboard's PYTHONPATH-carrying launcher — so
# LAB_ROOT must be located and put on sys.path manually before `launcher` can
# be imported, the same way grasp_hold/scene.py does.
sys.path.insert(
    0, str(next(c for c in Path(__file__).parents if (c / "labtests").is_dir()))
)
from launcher.bootstrap import bootstrap_lab

SCRIPT_DIR, SRC_ROOT, APP_ROOT, LAB_ROOT = bootstrap_lab(__file__)

DEFAULT_REFERENCE_RECORDING = (
    LAB_ROOT / "runtime" / "recordings" / "grasp_hold" / "motor_recording.json"
)


def _load_reference_path(recording_file: Path) -> tuple[list, list]:
    """Load the captured target_poses/gripper_openings from a recording file.

    Raises:
        FileNotFoundError: If recording_file does not exist.
        ValueError: If it lacks the captured target path (old-format
            recording — needs re-recording via the interactive Recording
            scene to add target_poses/gripper_openings).
    """
    if not recording_file.exists():
        raise FileNotFoundError(f"[TrialRecorder] Reference recording not found: {recording_file}")

    data = json.loads(recording_file.read_text(encoding="utf-8"))
    target_poses = data.get("target_poses")
    gripper_openings = data.get("gripper_openings")
    if not target_poses or not gripper_openings:
        raise ValueError(
            f"[TrialRecorder] {recording_file} has no target_poses/gripper_openings — "
            "re-record it via the interactive Recording scene (Play through the "
            "whole program) so it captures the effector path, not just motor angles."
        )
    return target_poses, gripper_openings


class TargetPathReplayController:
    """Replays a captured target-pose/gripper-opening path frame-for-frame.

    Not a Sofa.Core.Controller subclass itself (Sofa.Core only exists inside an
    active session) — createScene() binds onAnimateBeginEvent below onto a real
    controller instance the same way playback_controller.py does.
    """

    def __init__(self, *, target_mo, rest_lengths, target_poses, gripper_openings, recorder):
        self.target_mo = target_mo
        self.rest_lengths = rest_lengths
        self.target_poses = target_poses
        self.gripper_openings = gripper_openings
        self.recorder = recorder
        self._frame_index = 0
        self._done = False

    def step(self, current_time: float) -> None:
        """Advance the replay by one frame; called from onAnimateBeginEvent.

        Starts at frame 0 immediately, unconditionally — matching
        RecordingController, which never waits for assembly to settle either.
        Waiting here (as an earlier version did) meant replay's frame 0 hit an
        already-fully-assembled robot while the original recording's frame 0
        was captured on a still-forming one (assembly softens in over a short
        ramp) — a different starting mechanical state that the solver then
        carries forward, so the mismatch never dies out.
        """
        if self._done:
            return

        if self._frame_index >= len(self.target_poses):
            self._finish()
            return

        self.target_mo.position.value = [self.target_poses[self._frame_index]]
        if self._frame_index < len(self.gripper_openings):
            opening = self.gripper_openings[self._frame_index]
            self.rest_lengths.value = [opening] * len(self.rest_lengths.value)

        self.recorder.capture_frame(current_time)
        self._frame_index += 1

    def _finish(self) -> None:
        self._done = True
        self.recorder.save()
        print(
            f"[TrialRecorder] Replay complete: {self.recorder.frame_count} frames recorded "
            f"to {self.recorder.output_file}"
        )
        os.kill(os.getpid(), 9)


def createScene(rootnode):
    """Build the headless trial-recorder scene: inverse mode, path replay, recording."""
    import Sofa.Core  # type: ignore

    from labtests.core.base_scene import build_base_scene
    from labtests.core.modules.effector_target import setup as setup_effector
    from labtests.core.modules.motor_recorder import MotorRecorder
    from parts.controllers.assemblycontroller import AssemblyController  # type: ignore

    output_path = os.environ.get("OPT_MOTOR_RECORDING_OUT")
    if not output_path:
        raise RuntimeError(
            "[TrialRecorder] OPT_MOTOR_RECORDING_OUT is required — this scene is only "
            "meant to be launched by sofaopt_project.py's prepare_trial hook."
        )
    reference_path = Path(
        os.environ.get("OPT_REFERENCE_RECORDING") or str(DEFAULT_REFERENCE_RECORDING)
    )
    target_poses, gripper_openings = _load_reference_path(reference_path)

    # multithreading=True matches _manual_scene.py (what RecordingController
    # captures from) — the constraint solver's floating-point summation order
    # differs between threaded and single-threaded runs, which is enough to
    # tip this redundant mechanism's IK onto a different (still valid, but
    # different) solution branch that then persists for the rest of the replay.
    nodes = build_base_scene(rootnode, inverse=True, multithreading=True)
    if nodes is None:
        return

    # duration=0.1 matches _manual_scene.py's manual/interactive scenes (the
    # ones RecordingController captures from) — the default 1.0s used
    # elsewhere would settle the robot before replay's frame 0 instead of
    # during it, a different starting mechanical state for the solver.
    assembly = AssemblyController(nodes.emio)
    assembly.duration = 0.1
    nodes.emio.addObject(assembly)

    effector_handles = setup_effector(
        nodes,
        nodes.emio,
        initial_target_pos=target_poses[0],
        gripper_opening_max=max(gripper_openings),
    )

    rest_lengths = nodes.emio.centerpart.Effector.Distance.DistanceMapping.restLengths
    recorder = MotorRecorder(nodes.emio, output_path, dt=float(rootnode.dt.value))
    replay_controller = TargetPathReplayController(
        target_mo=effector_handles.target_mo,
        rest_lengths=rest_lengths,
        target_poses=target_poses,
        gripper_openings=gripper_openings,
        recorder=recorder,
    )

    class _RecorderStep(Sofa.Core.Controller):
        def onAnimateBeginEvent(self, event):
            replay_controller.step(float(rootnode.time.value))

    nodes.simulation.addObject(_RecorderStep(name="TrialRecorderStep"))

    return rootnode
