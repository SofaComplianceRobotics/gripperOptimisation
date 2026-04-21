"""
Lab ShapeOPT Recording Scene - Record motor trajectories for replay.

Inverse target-control scene based on project_pickandplace.
Records motor trajectories to runtime/motor_recording.json while simulation runs.

Usage:
    1. Run this scene.
    2. Press Play to start recording.
    3. Stop the simulation when done.
    4. The trajectory is written to runtime/motor_recording.json.

To record a new trajectory, rerun the scene; the previous file is overwritten.
"""

import os
import sys
import json
from pathlib import Path

sys.path.append(os.path.dirname(os.path.realpath(__file__)) + "/../../")

import os.path

import Sofa.Core

LAB_ROOT = Path(__file__).resolve().parent
APP_SRC = LAB_ROOT / "app" / "src"
if str(APP_SRC) not in sys.path:
    sys.path.insert(0, str(APP_SRC))


def _pick_recording_target() -> str:
    """Resolve which test target should receive this recording."""
    env_target = os.environ.get("LAB_SHAPEOPT_RECORDING_TARGET", "").strip()
    if os.environ.get("LAB_SHAPEOPT_RECORDING_PICKER", "1").strip().lower() not in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return "grasp_hold"

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
        print(f"[Recording] target picker unavailable: {exc}")

    if env_target:
        return env_target

    return "grasp_hold"


RECORD_TARGET = _pick_recording_target()
RECORD_FILE = os.path.join(
    os.path.dirname(__file__),
    "runtime",
    "recordings",
    RECORD_TARGET,
    "motor_recording.json",
)
ASSEMBLY_SKIP_TIME = 0.0


class RecordingController(Sofa.Core.Controller):
    def __init__(self, root, emio):
        """Initialize recording state and periodic autosave settings."""
        Sofa.Core.Controller.__init__(self)
        self.name = "RecordingController"
        self.root = root
        self.emio = emio
        self.recording_state = {
            "motor_positions": [],
            "timestamps": [],
            "start_time": None,
            "dt": float(root.dt.value),
        }
        self.capture_start_time = None
        self.last_save_time = 0.0
        self.save_interval = 1.0

        print("=" * 60)
        print("RECORDING MODE ACTIVE")
        print(f"Target test: {RECORD_TARGET}")
        print(f"Output: {RECORD_FILE}")
        print(
            f"Recording starts when you press Play (skip first {ASSEMBLY_SKIP_TIME:.2f}s)"
        )
        print("=" * 60)

    def _save_to_file(self):
        """Persist the in-memory trajectory to runtime/motor_recording.json."""
        try:
            directory = os.path.dirname(RECORD_FILE)
            if directory and not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)
            with open(RECORD_FILE, "w", encoding="utf-8") as f:
                json.dump(self.recording_state, f, indent=2)
        except Exception as exc:
            print(f"[Recording] save error: {exc}")

    def onAnimateBeginEvent(self, event):
        """Capture one frame of motor positions at each animation step."""
        current_time = float(self.root.time.value)

        if self.recording_state["start_time"] is None:
            self.recording_state["start_time"] = current_time

        if current_time < (self.recording_state["start_time"] + ASSEMBLY_SKIP_TIME):
            return

        if self.capture_start_time is None:
            self.capture_start_time = current_time

        positions = []
        for motor in self.emio.motors:
            motor_position = float(motor.getMechanicalState().position.value[0][0])
            positions.append(motor_position)

        self.recording_state["motor_positions"].append(positions)
        self.recording_state["timestamps"].append(
            current_time - self.capture_start_time
        )

        if current_time - self.last_save_time >= self.save_interval:
            self.last_save_time = current_time
            self._save_to_file()
            print(
                f"[Recording] {len(self.recording_state['motor_positions'])} frames | t={current_time:.2f}s"
            )


def createScene(rootnode):
    """Create the recording scene and attach trajectory capture controller."""
    from utils.header import addHeader, addSolvers
    from parts.gripper import Gripper
    from parts.controllers.assemblycontroller import AssemblyController
    import Sofa.ImGui as MyGui
    from parts.emio import Emio, getParserArgs

    args = getParserArgs()

    settings, modelling, simulation = addHeader(rootnode, inverse=True)
    addSolvers(simulation)

    rootnode.dt = 0.05
    rootnode.gravity = [0.0, -9810.0, 0.0]
    rootnode.VisualStyle.displayFlags.value = ["hideBehavior", "hideWireframe"]

    emio = Emio(
        name="Emio",
        legsName=["blueleg"],
        legsModel=["beam"],
        legsPositionOnMotor=[
            "counterclockwisedown",
            "clockwisedown",
            "counterclockwisedown",
            "clockwisedown",
        ],
        centerPartName="new_gripper",
        centerPartType="deformable",
        centerPartModel="beam",
        centerPartClass=Gripper,
        platformLevel=2,
        extended=True,
    )
    if not emio.isValid():
        return

    simulation.addChild(emio)
    emio.attachCenterPartToLegs()
    assembly = AssemblyController(emio)
    assembly.duration = 0.1
    emio.addObject(assembly)

    tray = modelling.addChild("Tray")
    tray.addObject(
        "MeshSTLLoader",
        filename=os.path.dirname(__file__) + "/../../data/meshes/tray.stl",
        translation=[0, 10, 0],
    )
    tray.addObject(
        "OglModel", src=tray.MeshSTLLoader.linkpath, color=[0.3, 0.3, 0.3, 0.2]
    )

    emio.effector.addObject(
        "MechanicalObject", template="Rigid3", position=[0, 0, 0, 0, 0, 0, 1] * 4
    )
    emio.effector.addObject("RigidMapping", rigidIndexPerPoint=[0, 1, 2, 3])

    effectorTarget = modelling.addChild("Target")
    effectorTarget.addObject("EulerImplicitSolver", firstOrder=True)
    effectorTarget.addObject(
        "CGLinearSolver", iterations=50, tolerance=1e-10, threshold=1e-10
    )
    effectorTarget.addObject(
        "MechanicalObject",
        template="Rigid3",
        position=[0, -150, 0, 0, 0, 0, 1],
        showObject=True,
        showObjectScale=20,
    )

    emio.addInverseComponentAndGUI(
        effectorTarget.getMechanicalState().position.linkpath, barycentric=True
    )
    TCP = modelling.addChild("TCP")
    TCP.addObject(
        "MechanicalObject",
        template="Rigid3",
        position=emio.effector.EffectorCoord.barycenter.linkpath,
    )
    MyGui.setIPController(rootnode.Modelling.Target, TCP, rootnode.ConstraintSolver)

    MyGui.MoveWindow.addAccessory(
        "Gripper's opening (mm)",
        emio.centerpart.Effector.Distance.DistanceMapping.restLengths,
        5,
        70,
    )
    MyGui.ProgramWindow.addGripper(
        emio.centerpart.Effector.Distance.DistanceMapping.restLengths, 5, 70
    )
    MyGui.IOWindow.addSubscribableData(
        "/Gripper", emio.centerpart.Effector.Distance.DistanceMapping.restLengths
    )

    rootnode.addObject(RecordingController(rootnode, emio))

    if args.connection:
        emio.addConnectionComponents()

    return rootnode
