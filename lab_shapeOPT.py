"""
Lab ShapeOPT SOFA Scene - Simulate grasping and lifting performance.

SOFA simulation script that runs gripper models against a cube-lifting task,
measures performance, and writes results for the Optuna optimization loop.
Launched as a subprocess by app/src/optimization/optimize.py and configured
through environment variables.
"""

import os
import sys
import math
import json
import random
from pathlib import Path

sys.path.append(os.path.dirname(os.path.realpath(__file__)) + "/../../")

import os.path

LAB_ROOT = Path(__file__).resolve().parent
ASSETS_ROOT = LAB_ROOT.parent.parent
GRIPPER_MESH_PATH = os.environ.get(
    "OPTUNA_STL_PATH",
    str(ASSETS_ROOT / "data" / "meshes" / "centerparts" / "new_gripper_collision.stl"),
)
SCORE_PATH = os.environ.get("OPTUNA_SCORE_PATH", None)
STATUS_PATH = os.environ.get("OPTUNA_STATUS_PATH", None)
OPTUNA_GEN = int(os.environ.get("OPTUNA_GEN", "0"))
OPTUNA_TRIAL = int(os.environ.get("OPTUNA_TRIAL", "0"))
OPTUNA_RUN = int(os.environ.get("OPTUNA_RUN", "0"))
EARLY_STOP_SIM_TIME = float(os.environ.get("EARLY_STOP_SIM_TIME", "1.0"))
FLOOR_Y_THRESHOLD = float(os.environ.get("FLOOR_Y_THRESHOLD", "-235.0"))
FLOOR_Y_BUFFER = float(os.environ.get("FLOOR_Y_BUFFER", "5.0"))

# Y threshold above which the cube is considered "picked up"
PICKUP_Y_THRESHOLD = float(os.environ.get("PICKUP_Y_THRESHOLD", "-215.0"))

# Penalty applied to the final height if the cube was dropped
DROP_PENALTY = float(os.environ.get("DROP_PENALTY", "50.0"))

# Overload phase config (after recorded motor trajectory)
OVERLOAD_MAX_TIME = float(os.environ.get("OVERLOAD_MAX_TIME", "12.0"))
CUBE_MASS_START = float(os.environ.get("CUBE_MASS_START", "0.02"))
CUBE_MASS_MAX = float(os.environ.get("CUBE_MASS_MAX", "1.0"))
CUBE_MASS_RAMP_TIME = float(os.environ.get("CUBE_MASS_RAMP_TIME", "8.0"))
EARLY_CONTACT_STOP_TIME = float(os.environ.get("EARLY_CONTACT_STOP_TIME", "0.6"))
EARLY_CONTACT_PENALTY = float(os.environ.get("EARLY_CONTACT_PENALTY", "-1.0"))
NO_PICKUP_PENALTY = float(os.environ.get("NO_PICKUP_PENALTY", "0.0"))
UNDERCUBE_PENALTY = float(os.environ.get("UNDERCUBE_PENALTY", "-0.2"))
UNDERCUBE_MARGIN = float(os.environ.get("UNDERCUBE_MARGIN", "0.0"))
ENABLE_UNDERCUBE_CHECK = os.environ.get("ENABLE_UNDERCUBE_CHECK", "0") == "1"
SHAPEOPT_FRICTION_COEF = float(os.environ.get("SHAPEOPT_FRICTION_COEF", "0.6"))

# Set to True to save a matplotlib graph of cube Y position over time
SHOW_CUBE_Y_GRAPH = os.environ.get("SHOW_CUBE_Y_GRAPH", "0") == "1"
SHAPEOPT_TEST_MODE = os.environ.get("SHAPEOPT_TEST_MODE", "").strip().lower()
SHAPEOPT_FINISH_BONUS = float(os.environ.get("SHAPEOPT_FINISH_BONUS", "2.0"))
SHAPEOPT_CUBE_WEIGHT_MIN = float(os.environ.get("SHAPEOPT_CUBE_WEIGHT_MIN", "0.02"))
SHAPEOPT_CUBE_WEIGHT_MAX = float(os.environ.get("SHAPEOPT_CUBE_WEIGHT_MAX", "0.2"))
SHAPEOPT_FLOOR_CENTER_Y = float(os.environ.get("SHAPEOPT_FLOOR_CENTER_Y", "-230.0"))
SHAPEOPT_CUBE_SPAWN_CLEARANCE = float(
    os.environ.get("SHAPEOPT_CUBE_SPAWN_CLEARANCE", "10")
)
SHAPEOPT_DROP_BELOW_SPAWN_TOL = float(
    os.environ.get("SHAPEOPT_DROP_BELOW_SPAWN_TOL", "0.5")
)
SHAPEOPT_PICKUP_ABOVE_SPAWN_TOL = float(
    os.environ.get("SHAPEOPT_PICKUP_ABOVE_SPAWN_TOL", "1.0")
)
SHAPEOPT_CUBE_SPAWN_TIME = float(os.environ.get("SHAPEOPT_CUBE_SPAWN_TIME", "0.4"))
SHAPEOPT_CUBE_PRESPAWN_OFFSET = float(
    os.environ.get("SHAPEOPT_CUBE_PRESPAWN_OFFSET", "200.0")
)


def _resolve_record_file() -> str:
    """Resolve recording file path for a selected recording target."""
    target = os.environ.get("LAB_SHAPEOPT_RECORDING_TARGET", "").strip()
    if not target:
        target = os.environ.get("OPTUNA_TEST_NAME", "").strip()

    if target:
        target_path = (
            LAB_ROOT / "runtime" / "recordings" / target / "motor_recording.json"
        )
        legacy = LAB_ROOT / "runtime" / "motor_recording.json"
        if target == "grasp_hold" and not target_path.exists() and legacy.exists():
            return str(legacy)
        return str(target_path)

    legacy = LAB_ROOT / "runtime" / "motor_recording.json"
    if legacy.exists():
        return str(legacy)
    return str(
        LAB_ROOT / "runtime" / "recordings" / "grasp_hold" / "motor_recording.json"
    )


def _resolve_random_cube_case() -> tuple[list[float], float] | None:
    """Return (cube_scale, cube_mass) for random-cube mode."""
    if SHAPEOPT_TEST_MODE != "random_cube_pick":
        return None

    size_cycle = ([5, 5, 5], [8, 8, 8], [20, 20, 20])
    test_run_index = int(os.environ.get("LAB_SHAPEOPT_TEST_RUN_INDEX", str(OPTUNA_RUN)))
    cycle_index = max(0, (test_run_index - 1) % 3)
    cube_scale = list(size_cycle[cycle_index])

    lo = min(SHAPEOPT_CUBE_WEIGHT_MIN, SHAPEOPT_CUBE_WEIGHT_MAX)
    hi = max(SHAPEOPT_CUBE_WEIGHT_MIN, SHAPEOPT_CUBE_WEIGHT_MAX)
    rng = random.Random(OPTUNA_GEN)
    cube_mass = rng.uniform(lo, hi)
    return cube_scale, cube_mass


def _write_status(payload: dict) -> None:
    """
    Write one run-status JSON payload for the external monitor.

    Inputs:
        payload (dict): Status payload fields.

    Returns:
        None
    """
    if not STATUS_PATH:
        return

    try:
        status_file = STATUS_PATH
        tmp_file = status_file + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp_file, status_file)
    except Exception:
        # Status telemetry is best-effort; never fail the simulation because of it.
        pass


def createScene(rootnode):
    from utils.header import addHeader, addSolvers
    from parts.gripper import Gripper
    from parts.controllers.assemblycontroller import AssemblyController
    from parts.emio import Emio, getParserArgs
    from splib3.animation import AnimationManager
    import Sofa.Core

    # args = getParserArgs()

    DT = 0.01
    RECORD_FILE = _resolve_record_file()
    is_random_cube_mode = SHAPEOPT_TEST_MODE == "random_cube_pick"
    cube_mass_start = CUBE_MASS_START
    cube_mass_max = CUBE_MASS_MAX
    cube_mass_ramp_time = CUBE_MASS_RAMP_TIME

    random_cube_case = _resolve_random_cube_case()
    if random_cube_case is not None:
        cube_scale_mode, random_cube_mass = random_cube_case
        cube_mass_start = random_cube_mass
        cube_mass_max = random_cube_mass
        print(
            f"[cube] random_cube_pick test_run={os.environ.get('LAB_SHAPEOPT_TEST_RUN_INDEX', str(OPTUNA_RUN))} "
            f"global_run={OPTUNA_RUN} gen={OPTUNA_GEN} "
            f"scale={cube_scale_mode} mass={random_cube_mass:.5f}kg"
        )
    else:
        cube_scale_mode = [5.0, 5.0, 5.0]

    settings, modelling, simulation = addHeader(
        rootnode,
        inverse=False,
        withCollision=True,
        friction=SHAPEOPT_FRICTION_COEF,
        multithreading=False,
    )
    print(f"[contact] friction configured with mu={SHAPEOPT_FRICTION_COEF:.6f}")

    addSolvers(simulation)

    # rootnode.addObject(AnimationManager(rootnode))
    rootnode.animate = True

    localMinDist = rootnode.getObject("LocalMinDistance")
    localMinDist.alarmDistance = 5
    localMinDist.contactDistance = 1.5  # careful, if too low it can cause the gripper to glitch through the cube keeping it stuck inside, giving a perfect score to any gripper this hapens to

    confignode = simulation.addChild("Config")
    confignode.addObject(
        "RequiredPlugin", name="Sofa.Component.AnimationLoop", printLog=False
    )
    confignode.addObject(
        "RequiredPlugin",
        name="Sofa.Component.Collision.Detection.Algorithm",
        printLog=False,
    )
    confignode.addObject(
        "RequiredPlugin",
        name="Sofa.Component.Collision.Detection.Intersection",
        printLog=False,
    )
    confignode.addObject(
        "RequiredPlugin", name="Sofa.Component.Collision.Geometry", printLog=False
    )
    confignode.addObject(
        "RequiredPlugin",
        name="Sofa.Component.Collision.Response.Contact",
        printLog=False,
    )
    confignode.addObject(
        "RequiredPlugin",
        name="Sofa.Component.Constraint.Lagrangian.Correction",
        printLog=False,
    )
    confignode.addObject(
        "RequiredPlugin",
        name="Sofa.Component.Constraint.Lagrangian.Solver",
        printLog=False,
    )
    confignode.addObject(
        "RequiredPlugin", name="Sofa.Component.IO.Mesh", printLog=False
    )
    confignode.addObject(
        "RequiredPlugin", name="Sofa.Component.LinearSolver.Iterative", printLog=False
    )
    confignode.addObject(
        "RequiredPlugin", name="Sofa.Component.Mapping.NonLinear", printLog=False
    )
    confignode.addObject("RequiredPlugin", name="Sofa.Component.Mass", printLog=False)
    confignode.addObject(
        "RequiredPlugin", name="Sofa.Component.ODESolver.Backward", printLog=False
    )
    confignode.addObject(
        "RequiredPlugin", name="Sofa.Component.StateContainer", printLog=False
    )
    confignode.addObject(
        "RequiredPlugin",
        name="Sofa.Component.Topology.Container.Constant",
        printLog=False,
    )
    confignode.addObject("RequiredPlugin", name="Sofa.Component.Visual", printLog=False)
    confignode.addObject(
        "RequiredPlugin", name="Sofa.GL.Component.Rendering3D", printLog=False
    )

    rootnode.dt = DT
    rootnode.gravity = [0.0, -9810.0, 0.0]

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
    # assembly = AssemblyController(emio)
    # assembly.duration = 0.1
    # emio.addObject(assembly)

    gripper_collision = emio.centerpart.addChild("CollisionModel")
    gripper_collision.addObject(
        "MeshSTLLoader", name="loader", filename=GRIPPER_MESH_PATH
    )
    gripper_collision.addObject("MeshTopology", src="@loader")
    gripper_collision.addObject("MechanicalObject")
    gripper_collision.addObject("PointCollisionModel", group=1)
    gripper_collision.addObject("LineCollisionModel", group=1)
    gripper_collision.addObject(
        "TriangleCollisionModel", name="gripperCollisionTriangles", group=1
    )
    gripper_collision.addObject("SkinningMapping")

    # emio.effector.addObject(
    #     "MechanicalObject", template="Rigid3", position=[0, 0, 0, 0, 0, 0, 1] * 4
    # )
    # emio.effector.addObject("RigidMapping", rigidIndexPerPoint=[0, 1, 2, 3])

    # effectorTarget = modelling.addChild("Target")
    # effectorTarget.addObject("EulerImplicitSolver", firstOrder=True)
    # effectorTarget.addObject(
    #     "CGLinearSolver", iterations=50, tolerance=1e-10, threshold=1e-10
    # )
    # effectorTarget.addObject(
    #     "MechanicalObject",
    #     template="Rigid3",
    #     position=[0, -150, 0, 0, 0, 0, 1],
    #     showObject=True,
    #     showObjectScale=20,
    # )

    # FORWARD DYNAMICS MODE - Always load and playback recorded motor trajectory
    filepath = RECORD_FILE

    if not os.path.exists(filepath):
        print(f"ERROR: Recording file not found: {filepath}")
        print("Run scene in direct mode first to record motor positions!")
        return

    with open(filepath, "r") as f:
        recording_data = json.load(f)

    motor_positions = recording_data["motor_positions"]
    num_motors = len(emio.motors)

    if not motor_positions:
        print("ERROR: No motor positions in recording!")
        return

    print("=" * 60)
    print("FORWARD DYNAMICS MODE - PLAYBACK")
    print(f"Loaded {len(motor_positions)} frames")
    print(f"Number of motors: {num_motors}")
    print("=" * 60 + "\n")

    joint_constraints = []
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

    class PlaybackController(Sofa.Core.Controller):
        def __init__(self, *args, **kwargs):
            Sofa.Core.Controller.__init__(self, *args, **kwargs)
            self.finished = False
            self.frame = 0
            self.recorded_frames = len(motor_positions)
            self.overload_frames = max(0, int(OVERLOAD_MAX_TIME / DT))
            self.total_frames = self.recorded_frames + self.overload_frames
            self.peak_y = float("-inf")
            self.was_picked_up = False
            self.dropped = False
            self.hold_time = 0.0
            self.last_positions = (
                list(motor_positions[-1]) if motor_positions else [0.0] * num_motors
            )
            self.cube_y_log = []
            self.time_log = []
            self.cube_gripper_contact_listener = None
            self.spawn_cube_y = None
            self.drop_y_threshold = None
            self.pickup_y_threshold = None
            self.cube_has_spawned = False
            self.spawn_contact_check_frames = 0
            print(
                f"[Playback] {self.recorded_frames} recorded + {self.overload_frames} overload frames"
            )
            print(
                f"[Scoring] hold-time after {EARLY_STOP_SIM_TIME:.2f}s, pickup threshold: {PICKUP_Y_THRESHOLD}"
            )
            self._set_cube_mass(cube_mass_start)

            _write_status(
                {
                    "gen": OPTUNA_GEN,
                    "trial": OPTUNA_TRIAL,
                    "run": OPTUNA_RUN,
                    "state": "running",
                    "current_frame": 0,
                    "total_frames": self.total_frames,
                    "sim_time": 0.0,
                    "cube_y": None,
                    "updated_at": rootnode.time.value,
                }
            )

        def _get_cube_y(self):
            cube_mo = rootnode.Simulation.Cube.getMechanicalState()
            return float(cube_mo.position.value[0][1])

        def _set_cube_mass(self, value: float) -> None:
            mass = max(0.0001, float(value))
            try:
                rootnode.Simulation.Cube.cube_mass.totalMass.value = mass
            except Exception:
                pass

        def _get_cube_collision_min_y(self) -> float | None:
            try:
                cube_collision_mo = (
                    rootnode.Simulation.Cube.collision.getMechanicalState()
                )
                points = cube_collision_mo.position.value
            except Exception:
                return None
            if len(points) == 0:
                return None
            ys = [float(p[1]) for p in points if len(p) >= 2]
            if not ys:
                return None
            return min(ys)

        def _get_gripper_collision_min_y(self) -> float | None:
            try:
                gripper_mo = gripper_collision.getMechanicalState()
                points = gripper_mo.position.value
            except Exception:
                return None
            if len(points) == 0:
                return None
            ys = [float(p[1]) for p in points if len(p) >= 2]
            if not ys:
                return None
            return min(ys)

        def _current_phase(self) -> str:
            if self.frame < self.recorded_frames:
                return "recorded"
            return "overload"

        def _update_overload_mass(self) -> None:
            if self.frame < self.recorded_frames:
                self._set_cube_mass(cube_mass_start)
                return

            overload_t = (self.frame - self.recorded_frames) * DT
            if cube_mass_ramp_time <= 0:
                alpha = 1.0
            else:
                alpha = max(0.0, min(1.0, overload_t / cube_mass_ramp_time))
            mass = cube_mass_start + (cube_mass_max - cube_mass_start) * alpha
            self._set_cube_mass(mass)

        def _write_score_and_stop(self, score: float, reason: str):
            if self.finished:
                return
            self.finished = True

            if SCORE_PATH:
                with open(SCORE_PATH, "w") as f:
                    json.dump({"score": score}, f)
            _write_status(
                {
                    "gen": OPTUNA_GEN,
                    "trial": OPTUNA_TRIAL,
                    "run": OPTUNA_RUN,
                    "state": "done",
                    "current_frame": self.frame,
                    "total_frames": self.total_frames,
                    "sim_time": self.frame * DT,
                    "cube_y": self._get_cube_y(),
                    "score": score,
                    "reason": reason,
                    "updated_at": rootnode.time.value,
                }
            )
            print(f"[Playback] Stopped — {reason} | final score: {score:.2f}")
            rootnode.animate = False

            if SHOW_CUBE_Y_GRAPH and self.cube_y_log:
                import matplotlib.pyplot as plt

                fig, ax = plt.subplots(figsize=(12, 6))
                ax.plot(self.time_log, self.cube_y_log, linewidth=0.8)
                ax.axhline(
                    y=PICKUP_Y_THRESHOLD,
                    color="green",
                    linestyle="--",
                    linewidth=0.8,
                    label=f"pickup threshold ({PICKUP_Y_THRESHOLD})",
                )
                ax.axhline(
                    y=FLOOR_Y_THRESHOLD,
                    color="red",
                    linestyle="--",
                    linewidth=0.8,
                    label=f"floor threshold ({FLOOR_Y_THRESHOLD})",
                )
                ax.set_xlim(0, len(motor_positions) * DT)
                ax.set_ylim(-320, -10)
                ax.set_xlabel("Simulation time (s)")
                ax.set_ylabel("Cube Y position")
                ax.set_title(f"Cube Y — {reason} | score: {score:.2f}")
                ax.legend()
                out_path = os.path.join(
                    os.path.dirname(__file__), f"cube_y_{os.getpid()}.png"
                )
                fig.savefig(out_path, dpi=150)
                print(f"[Graph] Saved to {out_path}")
                plt.show()  # Open interactive Tkinter window — allows zoom/pan

            os.kill(os.getpid(), 9)

        def _write_pruned_and_stop(self, reason: str):
            if self.finished:
                return
            self.finished = True

            _write_status(
                {
                    "gen": OPTUNA_GEN,
                    "trial": OPTUNA_TRIAL,
                    "run": OPTUNA_RUN,
                    "state": "pruned",
                    "current_frame": self.frame,
                    "total_frames": self.total_frames,
                    "sim_time": self.frame * DT,
                    "cube_y": self._get_cube_y(),
                    "score": None,
                    "reason": reason,
                    "updated_at": rootnode.time.value,
                }
            )
            print(f"[Playback] Pruned — {reason}")
            rootnode.animate = False
            os.kill(os.getpid(), 9)

        def _compute_score(self, cube_y: float) -> tuple[float, str]:
            """
            Hold-time scoring after early-stop window.

            Returns:
              - score: total held time (seconds)
              - reason: textual summary
            """
            return self.hold_time, f"hold_time={self.hold_time:.2f}s"

        def _get_cube_gripper_contact_count(self) -> int:
            if self.cube_gripper_contact_listener is None:
                try:
                    self.cube_gripper_contact_listener = rootnode.Simulation.getObject(
                        "cubeGripperContactListener"
                    )
                except Exception:
                    self.cube_gripper_contact_listener = None

            if self.cube_gripper_contact_listener is None:
                return 0

            try:
                return int(self.cube_gripper_contact_listener.getNumberOfContacts())
            except Exception:
                return 0

        def _has_cube_gripper_contact(self) -> bool:
            return self._get_cube_gripper_contact_count() > 0

        def _collision_aabb(self, collision_node):
            try:
                points = collision_node.getMechanicalState().position.value
            except Exception:
                return None
            if len(points) == 0:
                return None

            xs = [float(point[0]) for point in points if len(point) >= 3]
            ys = [float(point[1]) for point in points if len(point) >= 3]
            zs = [float(point[2]) for point in points if len(point) >= 3]
            if not xs or not ys or not zs:
                return None

            return min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)

        def _spawn_overlap_detected(self) -> bool:
            contact_count = self._get_cube_gripper_contact_count()
            if contact_count > 0:
                return True

            cube_aabb = self._collision_aabb(rootnode.Simulation.Cube.collision)
            gripper_aabb = self._collision_aabb(gripper_collision)
            if cube_aabb is None or gripper_aabb is None:
                return False

            cube_min_x, cube_max_x, cube_min_y, cube_max_y, cube_min_z, cube_max_z = (
                cube_aabb
            )
            (
                gripper_min_x,
                gripper_max_x,
                gripper_min_y,
                gripper_max_y,
                gripper_min_z,
                gripper_max_z,
            ) = gripper_aabb
            return (
                cube_min_x <= gripper_max_x
                and cube_max_x >= gripper_min_x
                and cube_min_y <= gripper_max_y
                and cube_max_y >= gripper_min_y
                and cube_min_z <= gripper_max_z
                and cube_max_z >= gripper_min_z
            )

        def _ensure_drop_threshold_initialized(self, cube_y: float) -> None:
            if (
                self.spawn_cube_y is not None
                and self.drop_y_threshold is not None
                and self.pickup_y_threshold is not None
            ):
                return
            self.spawn_cube_y = float(cube_y)
            self.drop_y_threshold = self.spawn_cube_y - SHAPEOPT_DROP_BELOW_SPAWN_TOL
            self.pickup_y_threshold = (
                self.spawn_cube_y + SHAPEOPT_PICKUP_ABOVE_SPAWN_TOL
            )
            print(
                f"[Scoring] spawn_y={self.spawn_cube_y:.2f} | "
                f"pickup>={self.pickup_y_threshold:.2f} (+{SHAPEOPT_PICKUP_ABOVE_SPAWN_TOL:.2f}) | "
                f"drop<{self.drop_y_threshold:.2f} (-{SHAPEOPT_DROP_BELOW_SPAWN_TOL:.2f})"
            )

        def _check_spawn_contact_window(self, sim_time: float) -> None:
            if self.spawn_contact_check_frames <= 0 or self.finished:
                return
            contact_count = self._get_cube_gripper_contact_count()
            overlap = self._spawn_overlap_detected()
            print(
                f"[SpawnCheck] t={sim_time:.2f}s contacts={contact_count} overlap={overlap} "
                f"frames_left={self.spawn_contact_check_frames}"
            )
            if overlap:
                self._write_score_and_stop(
                    EARLY_CONTACT_PENALTY,
                    ("cube touched gripper at spawn window " f"t={sim_time:.2f}s"),
                )
                return
            self.spawn_contact_check_frames -= 1

        def onAnimateBeginEvent(self, event):
            if self.finished:
                return

            if self.frame == 0:
                if self.cube_has_spawned:
                    cube = rootnode.Simulation.Cube.getMechanicalState()
                    print("INIT cube vel:", cube.velocity.value)
                else:
                    print("INIT cube vel: n/a (cube not spawned yet)")

            sim_time = self.frame * DT
            self._update_overload_mass()

            cube_y = None
            if not self.cube_has_spawned and sim_time >= SHAPEOPT_CUBE_SPAWN_TIME:
                cube_mo = rootnode.Simulation.Cube.getMechanicalState()
                cube_mo.position.value = [[0.0, cube_spawn_y, 0.0, 0.0, 0.0, 0.0, 1.0]]
                cube_mo.velocity.value = [[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]]
                self.cube_has_spawned = True
                self.spawn_contact_check_frames = 2
                self.was_picked_up = False
                self.dropped = False
                self.hold_time = 0.0
                cube_y = float(cube_spawn_y)
                self._ensure_drop_threshold_initialized(cube_y)
                print(
                    f"[Spawn] cube spawned at t={sim_time:.2f}s "
                    f"(pos=[0,{cube_spawn_y:.2f},0], rot=identity, vel=zero)"
                )
                self._check_spawn_contact_window(sim_time)

            if self.cube_has_spawned and cube_y is None:
                cube_y = self._get_cube_y()
                self._ensure_drop_threshold_initialized(cube_y)
            elif not self.cube_has_spawned:
                cube_mo = rootnode.Simulation.Cube.getMechanicalState()
                prespawn_y = cube_spawn_y + SHAPEOPT_CUBE_PRESPAWN_OFFSET
                cube_mo.position.value = [[0.0, prespawn_y, 0.0, 0.0, 0.0, 0.0, 1.0]]
                cube_mo.velocity.value = [[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]]

            _write_status(
                {
                    "gen": OPTUNA_GEN,
                    "trial": OPTUNA_TRIAL,
                    "run": OPTUNA_RUN,
                    "state": "running",
                    "current_frame": self.frame,
                    "total_frames": self.total_frames,
                    "sim_time": sim_time,
                    "cube_y": cube_y,
                    "phase": self._current_phase(),
                    "updated_at": rootnode.time.value,
                }
            )

            if self.cube_has_spawned:
                # Record cube Y for graph
                if SHOW_CUBE_Y_GRAPH:
                    self.cube_y_log.append(cube_y)
                    self.time_log.append(sim_time)

                # Track peak height
                if cube_y > self.peak_y:
                    self.peak_y = cube_y

                if ENABLE_UNDERCUBE_CHECK:
                    cube_min_y = self._get_cube_collision_min_y()
                    gripper_min_y = self._get_gripper_collision_min_y()
                    if (
                        cube_min_y is not None
                        and gripper_min_y is not None
                        and gripper_min_y < (cube_min_y - UNDERCUBE_MARGIN)
                    ):
                        score = UNDERCUBE_PENALTY
                        reason = f"undercube_penalty={UNDERCUBE_PENALTY:.2f}"
                        self._write_score_and_stop(
                            score,
                            (
                                "invalid under-cube geometry at "
                                f"t={sim_time:.2f}s "
                                f"(gripper_min_y={gripper_min_y:.2f} < "
                                f"cube_min_y={cube_min_y:.2f} - margin={UNDERCUBE_MARGIN:.2f}) "
                                f"— {reason}"
                            ),
                        )
                        return

                # Detect pickup: cube must rise above spawn position
                if cube_y > float(self.pickup_y_threshold):
                    self.was_picked_up = True

                # Detect drop: was picked up, now below spawn height (with tolerance)
                if self.was_picked_up and cube_y < float(self.drop_y_threshold):
                    self.dropped = True

                # Hold-time metric starts after the pickup gate window.
                if sim_time >= EARLY_STOP_SIM_TIME and cube_y > float(
                    self.pickup_y_threshold
                ):
                    self.hold_time += DT

                # Rule 1: cube glitched through floor — hard failure
                if cube_y < FLOOR_Y_THRESHOLD:
                    if self.was_picked_up:
                        self._write_pruned_and_stop(
                            f"cube glitched through floor after pickup at t={sim_time:.2f}s"
                        )
                    else:
                        score, reason = self._compute_score(cube_y)
                        self._write_score_and_stop(
                            score,
                            f"cube glitched through floor at t={sim_time:.2f}s — {reason}",
                        )
                    return

                # Rule 2: after early stop window, cube still on floor
                if sim_time >= EARLY_STOP_SIM_TIME and not self.was_picked_up:
                    score = NO_PICKUP_PENALTY
                    reason = (
                        f"no_pickup_penalty={NO_PICKUP_PENALTY:.2f} "
                        f"(hold_time={self.hold_time:.2f}s)"
                    )
                    self._write_score_and_stop(
                        score,
                        f"pickup gate failed at t={sim_time:.2f}s — {reason}",
                    )
                    return

                # Rule 3: once picked up, stop when it is dropped.
                if self.was_picked_up and cube_y < float(self.drop_y_threshold):
                    score, reason = self._compute_score(cube_y)
                    self._write_score_and_stop(
                        score,
                        (
                            f"dropped at t={sim_time:.2f}s in {self._current_phase()} phase "
                            f"(cube_y={cube_y:.2f} < drop_y={float(self.drop_y_threshold):.2f}) — {reason}"
                        ),
                    )
                    return

            # Normal end — all frames played
            if self.frame >= self.total_frames:
                if is_random_cube_mode:
                    self._write_score_and_stop(
                        self.hold_time + SHAPEOPT_FINISH_BONUS,
                        (
                            "test horizon complete "
                            f"at t={sim_time:.2f}s — hold_time={self.hold_time:.2f}s "
                            f"+ finish_bonus={SHAPEOPT_FINISH_BONUS:.2f}"
                        ),
                    )
                else:
                    self._write_pruned_and_stop(
                        f"test horizon complete at t={sim_time:.2f}s"
                    )
                return

            # Normal step — replay recorded trajectory, then hold last pose.
            if self.frame < self.recorded_frames:
                positions = motor_positions[self.frame]
            else:
                positions = self.last_positions
            for i, constraint in enumerate(joint_constraints):
                if i < len(positions):
                    constraint.value.value = positions[i]

            if self.frame % 200 == 0:
                cube_y_text = f"{cube_y:.2f}" if cube_y is not None else "n/a"
                print(
                    f"[Playback] frame {self.frame}/{self.total_frames - 1}"
                    f"  t={sim_time:.2f}s  cube_Y={cube_y_text}"
                    f"  phase={self._current_phase()}"
                    f"  peak={self.peak_y:.2f}"
                    f"  hold_time={self.hold_time:.2f}s"
                    f"  picked_up={self.was_picked_up}"
                    f"  dropped={self.dropped}",
                    flush=True,
                )

            self.frame += 1

        def onAnimateEndEvent(self, event):
            if self.finished:
                return
            sim_time = max(0.0, (self.frame - 1) * DT)
            self._check_spawn_contact_window(sim_time)

    simulation.addObject(PlaybackController(name="PlaybackController"))

    # ------------------------
    # Adding objects
    # ------------------------

    totalMass = 0.10
    volume = 1.0
    inertiaMatrix = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
    cube_scale = cube_scale_mode
    floor_scale = [2.0, 1.0, 2.0]
    cube_spawn_y = (
        SHAPEOPT_FLOOR_CENTER_Y
        + (cube_scale[1] + floor_scale[1]) * 0.5
        + SHAPEOPT_CUBE_SPAWN_CLEARANCE
    )

    cube = simulation.addChild("Cube")
    cube.addObject(
        "MechanicalObject",
        template="Rigid3",
        position=[[0.0, cube_spawn_y, 0.0, 0.0, 0.0, 0.0, 1.0]],
        showObject=True,
    )

    cube.addObject("UniformMass", name="cube_mass", totalMass=cube_mass_start)

    visucube = cube.addChild("Visual")
    visucube.addObject(
        "MeshOBJLoader", name="loader", filename="mesh/cube.obj", scale3d=cube_scale
    )
    visucube.addObject(
        "OglModel", name="cubeVisual", src=visucube.loader.linkpath, color=[1, 0, 0, 1]
    )
    visucube.addObject("RigidMapping")

    collision = cube.addChild("collision")
    collision.addObject(
        "MeshOBJLoader",
        name="loader",
        filename="mesh/cube.obj",
        triangulate="true",
        scale3d=cube_scale,
    )
    collision.addObject("MeshTopology", src="@loader")
    collision.addObject("MechanicalObject")
    collision.addObject(
        "TriangleCollisionModel",
        name="cubeCollisionTriangles",
        group=2,
        moving=True,
        simulated=True,
    )
    collision.addObject(
        "LineCollisionModel",
        name="cubeCollisionLines",
        group=2,
        moving=True,
        simulated=True,
    )
    collision.addObject(
        "PointCollisionModel",
        name="cubeCollisionPoints",
        group=2,
        moving=True,
        simulated=True,
    )
    collision.addObject("RigidMapping")

    simulation.addObject(
        "ContactListener",
        name="cubeGripperContactListener",
        collisionModel1=gripper_collision.gripperCollisionTriangles.getLinkPath(),
        collisionModel2=collision.cubeCollisionTriangles.getLinkPath(),
    )

    floor = simulation.addChild("floor")
    floor.addObject(
        "MechanicalObject",
        name="mstate",
        template="Rigid3",
        translation2=[0.0, SHAPEOPT_FLOOR_CENTER_Y, 0.0],
        rotation2=[0.0, 0.0, 0.0],
        showObjectScale=5.0,
    )
    floor.addObject(
        "UniformMass", name="mass", vertexMass=[totalMass, volume, inertiaMatrix[:]]
    )
    floor.addObject("FixedConstraint", indices="0")

    floorCollis = floor.addChild("collision")
    floorCollis.addObject(
        "MeshOBJLoader",
        name="loader",
        filename="mesh/floor.obj",
        triangulate="true",
        scale3d=floor_scale,
    )
    floorCollis.addObject("MeshTopology", src="@loader")
    floorCollis.addObject("MechanicalObject")
    floorCollis.addObject(
        "TriangleCollisionModel", moving=False, simulated=False, group=3
    )
    floorCollis.addObject("LineCollisionModel", moving=False, simulated=False, group=3)
    floorCollis.addObject("PointCollisionModel", moving=False, simulated=False, group=3)
    floorCollis.addObject("RigidMapping")

    floorVisu = floor.addChild("VisualModel")
    floorVisu.loader = floorVisu.addObject(
        "MeshOBJLoader", name="loader", filename="mesh/floor.obj"
    )
    floorVisu.addObject(
        "OglModel",
        name="model",
        src="@loader",
        scale3d=floor_scale,
        color=[1.0, 1.0, 0.0],
        updateNormals=False,
    )
    floorVisu.addObject("RigidMapping")
    return rootnode
