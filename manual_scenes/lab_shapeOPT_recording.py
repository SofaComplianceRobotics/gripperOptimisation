"""
Lab ShapeOPT Recording Scene - Record motor trajectories for replay.

Inverse target-control scene based on project_pickandplace.
Records motor trajectories to runtime/motor_recording.json while simulation runs.
Also records the effector target's pose and the gripper opening every frame
("target_poses" / "gripper_openings") — sofaopt_project.py's per-trial
recorder replays that captured path (not the raw .crprog) through each
trial's own gripper/leg, since there's no way to headlessly re-run
ProgramWindow's own playback logic.

Usage:
    1. Run this scene.
    2. Press Play to start recording.
    3. Stop the simulation when done.
    4. The trajectory is written to runtime/motor_recording.json.

To record a new trajectory, rerun the scene; the previous file is overwritten.
"""

import json
from pathlib import Path

from launcher.bootstrap import bootstrap_lab

SCRIPT_DIR, SRC_ROOT, APP_ROOT, LAB_ROOT = bootstrap_lab(__file__)

import Sofa.Core

from labtests.core.modules.motor_recorder import MotorRecorder
from manual_scenes._manual_scene import build_manual_scene


def _pick_recording_target() -> str:
    """Resolve which test target should receive this recording.

    Priority:
      1. runtime/session_config.json written by the web UI before launching this scene
      2. Interactive PyQt6 picker (if available)
      3. Hard fallback: grasp_hold
    """
    session_cfg = LAB_ROOT / "runtime" / "session_config.json"
    if session_cfg.exists():
        try:
            data = json.loads(session_cfg.read_text(encoding="utf-8"))
            target = data.get("recording_test", "").strip()
            if target:
                print(f"[Recording] Using session config target: {target}")
                return target
        except Exception as exc:
            print(f"[Recording] Could not read session config: {exc}")

    try:
        from labtests.ui import prompt_for_tests

        selected = prompt_for_tests(
            title="Recording Target",
            prompt="Choose which test to record this trajectory for:",
            multi_select=False,
        )
        if selected:
            return selected[0]
    except Exception as exc:
        print(f"[Recording] Picker unavailable: {exc}")

    return "grasp_hold"


RECORD_TARGET = _pick_recording_target()
# Use LAB_ROOT to write to the same location tests read from
RECORD_FILE = str(
    LAB_ROOT / "runtime" / "recordings" / RECORD_TARGET / "motor_recording.json"
)
ASSEMBLY_SKIP_TIME = 0.0


class RecordingController(Sofa.Core.Controller):
    """Controller that captures motor trajectories and autosaves recordings.

    The controller collects motor positions and timestamps during simulation
    and writes them to `runtime/recordings/<test>/motor_recording.json`.
    """

    def __init__(self, root, emio, target_mo, rest_lengths):
        """Initialize recording state and periodic autosave settings."""
        Sofa.Core.Controller.__init__(self)
        self.name = "RecordingController"
        self.root = root
        self.recorder = MotorRecorder(
            emio,
            RECORD_FILE,
            dt=float(root.dt.value),
            target_mo=target_mo,
            rest_lengths=rest_lengths,
        )
        self._start_time = None

        print("=" * 60)
        print("RECORDING MODE ACTIVE")
        print(f"Target test: {RECORD_TARGET}")
        print(f"Output: {RECORD_FILE}")
        print(
            f"Recording starts when you press Play (skip first {ASSEMBLY_SKIP_TIME:.2f}s)"
        )
        print("=" * 60)

    def onAnimateBeginEvent(self, event):
        """Capture one frame of motor positions at each animation step."""
        current_time = float(self.root.time.value)

        if self._start_time is None:
            self._start_time = current_time

        if current_time < (self._start_time + ASSEMBLY_SKIP_TIME):
            return

        self.recorder.capture_frame(current_time)
        if self.recorder.frame_count % 100 == 0:
            print(f"[Recording] {self.recorder.frame_count} frames | t={current_time:.2f}s")


def createScene(rootnode):
    """Create the recording scene and attach trajectory capture controller."""
    nodes, args = build_manual_scene(rootnode, LAB_ROOT)
    if nodes is None:
        return

    target_mo = rootnode.Modelling.Target.getMechanicalState()
    rest_lengths = nodes.emio.centerpart.Effector.Distance.DistanceMapping.restLengths
    rootnode.addObject(
        RecordingController(rootnode, nodes.emio, target_mo, rest_lengths)
    )

    if args.connection:
        nodes.emio.addConnectionComponents()

    return rootnode
