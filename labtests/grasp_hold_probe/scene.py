"""
Scene: grasp_hold_probe — THROWAWAY debug copy of grasp_hold, for isolating the
cube/floor first-impact run-to-run divergence. Not a real test; safe to delete.

Copied from labtests/grasp_hold/scene.py and extended with env-var toggles so
components can be stripped one at a time without touching the real scene or
shared core modules:

  PROBE_SKIP_GRIPPER=1   Build cube+floor+gravity only. Skips Emio/gripper
                          construction, motor playback, and the playback
                          controller entirely (rootnode.animate stays True via
                          a trivial stepper so the sim still runs on its own).
  PROBE_NARROWPHASE=BVH  Swap DirectSAPNarrowPhase for BVHNarrowPhase after
                          the header builds the default collision pipeline.
  PROBE_SOLVER_TIGHT=1   Restore ConstraintSolver to tolerance=1e-10,
                          maxIterations=1500 (the pre-lab-override values),
                          instead of the loosened 1e-3/250 base_scene.py sets.
  PROBE_SKIP_PLAYBACK=1   Build the full scene (Emio/gripper/legs, real
                          collision meshes, cube+floor) but never attach the
                          motor-playback controller — the robot sits static
                          under gravity, never commanded to move or approach
                          the cube. Isolates "robot merely present in the
                          shared collision/constraint solve" from "robot
                          actively driven every frame".
  PROBE_LEGS_ONLY=1       Same as PROBE_SKIP_PLAYBACK (frozen, no motor
                          playback) but built with centerPartName=None, so
                          Emio never constructs the gripper/centerpart at
                          all — only the 4 legs + platform. No gripper
                          collision meshes, no ContactListeners (cube_floor
                          gets an empty finger list). Isolates legs vs
                          gripper specifically.
  PROBE_CUBE_TILT_DEG=N   Tilt the cube's initial orientation by N degrees
                          about a diagonal horizontal axis before it drops,
                          so it lands corner-first instead of flush-flat on
                          the floor. Breaks the many-simultaneous-contact tie
                          a flat cube on a flat floor creates. 0 (default) =
                          untouched, identity orientation, as production has
                          it. Applied wherever the cube's initial position is
                          set explicitly (the minimal/legs-only/frozen paths).
  PROBE_UNCOUPLED_CORRECTION=1  PROBE_SKIP_GRIPPER path only. Removes the
                          shared GenericConstraintCorrection (routes through
                          the full SparseLDLSolver linear system) and adds a
                          separate UncoupledConstraintCorrection directly to
                          the cube and floor nodes instead (diagonal/approx
                          compliance per body, no shared linear solve). Only
                          valid for free/unconnected bodies — do not use on
                          the legs/gripper paths, which have real joints.
  PROBE_OMP1=1            No-op here (thread pinning happens at the process
                          level in the probe launcher, not the scene) — kept
                          as a documented no-op so its absence isn't a surprise.
  PROBE_CUBE_UNREACHABLE=1  PROBE_SKIP_PLAYBACK or PROBE_LEGS_ONLY paths.
                          Builds the cube+floor exactly as normal (same
                          collision meshes, same mass/mapping components,
                          same total DOF count and MatrixLinearSystem.groups
                          population as without this flag), but spawns the
                          cube far out of reach so it can never fall into
                          contact range within the probe's step window.
                          Isolates "no contact ever occurs" from "scene
                          structure changed" — unlike skipping cube_floor
                          setup entirely, which changes the total DOF count
                          and therefore isn't a clean control.
"""

from __future__ import annotations

import math
import os
import sys
from pathlib import Path

sys.path.insert(
    0, str(next(c for c in Path(__file__).parents if (c / "labtests").is_dir()))
)
from launcher.bootstrap import bootstrap_lab

SCRIPT_DIR, SRC_ROOT, APP_ROOT, LAB_ROOT = bootstrap_lab(__file__)

from geometry.timing_config import DT_DIRECT as DT

RECORD_FILE = os.environ.get("OPT_MOTOR_RECORDING") or str(
    LAB_ROOT / "runtime" / "recordings" / "grasp_hold" / "motor_recording.json"
)


def _bool_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _cube_orientation() -> list:
    """Quaternion [qx,qy,qz,qw] for the cube's initial drop orientation.

    Identity (flush-flat landing) unless PROBE_CUBE_TILT_DEG is set — then a
    rotation about the (1,0,1) diagonal, so the cube lands corner-first
    instead of face-first, breaking the many-simultaneous-contact tie a flat
    landing creates.
    """
    deg = float(os.environ.get("PROBE_CUBE_TILT_DEG", "0"))
    if deg == 0.0:
        return [0.0, 0.0, 0.0, 1.0]
    half = math.radians(deg) / 2.0
    s = math.sin(half)
    axis = (1.0 / math.sqrt(2.0), 0.0, 1.0 / math.sqrt(2.0))
    return [axis[0] * s, axis[1] * s, axis[2] * s, math.cos(half)]


def _swap_narrowphase(rootnode) -> None:
    target = os.environ.get("PROBE_NARROWPHASE", "").strip().upper()
    if target != "BVH":
        return
    old = rootnode.getObject("DirectSAPNarrowPhase")
    if old is None:
        print("[probe] PROBE_NARROWPHASE=BVH requested but no DirectSAPNarrowPhase found", file=sys.stderr)
        return
    rootnode.removeObject(old)
    rootnode.addObject("BVHNarrowPhase")
    print("[probe] narrowphase swapped: DirectSAPNarrowPhase -> BVHNarrowPhase", file=sys.stderr)


def _retighten_solver(rootnode) -> None:
    solver = rootnode.getObject("ConstraintSolver")
    if _bool_env("PROBE_SOLVER_TIGHT"):
        if solver is None:
            print("[probe] PROBE_SOLVER_TIGHT requested but no ConstraintSolver found", file=sys.stderr)
            return
        solver.tolerance = 1e-10
        solver.maxIterations = 1500
        print("[probe] ConstraintSolver retightened: tolerance=1e-10 maxIterations=1500", file=sys.stderr)
    elif _bool_env("PROBE_SOLVER_REFTOL"):
        # Match lab_optimisation's reference scene exactly: tolerance=1e-6,
        # maxIterations=1000 (that scene is measured-clean at this setting).
        if solver is None:
            print("[probe] PROBE_SOLVER_REFTOL requested but no ConstraintSolver found", file=sys.stderr)
            return
        solver.tolerance = 1e-6
        solver.maxIterations = 1000
        print("[probe] ConstraintSolver set to reference tolerance: 1e-6 / 1000", file=sys.stderr)


def _enable_lcp_dump(rootnode) -> None:
    """PROBE_DUMP_LCP=1: turn on printLog for the ConstraintSolver so SOFA's own
    GenericConstraintSolver::solveSystem() dumps the actual W matrix, dfree
    ("delta"), and force ("lambda") vectors every step via msg_info() — no
    custom instrumentation needed, this is built into SOFA itself, just muted
    by default.
    """
    if not _bool_env("PROBE_DUMP_LCP"):
        return
    solver = rootnode.getObject("ConstraintSolver")
    if solver is None:
        print("[probe] PROBE_DUMP_LCP requested but no ConstraintSolver found", file=sys.stderr)
        return
    solver.printLog = True
    print("[probe] ConstraintSolver.printLog enabled (W/delta/lambda dumps every step)", file=sys.stderr)


def _enable_broadphase_dump(rootnode) -> None:
    """PROBE_DUMP_BROADPHASE=1: turn on printLog for BruteForceBroadPhase (and
    DirectSAPNarrowPhase) so their existing dmsg_info() calls print each
    CollisionModel's name AND raw pointer as it's registered, in call order —
    the earliest point in the whole pipeline we can observe ordering at.
    """
    if not _bool_env("PROBE_DUMP_BROADPHASE"):
        return
    bp = rootnode.getObject("BruteForceBroadPhase")
    if bp is not None:
        bp.printLog = True
    np_ = rootnode.getObject("DirectSAPNarrowPhase") or rootnode.getObject("BVHNarrowPhase")
    if np_ is not None:
        np_.printLog = True
    print(f"[probe] broadphase/narrowphase printLog enabled (bp={bp is not None}, np={np_ is not None})", file=sys.stderr)


def _set_solver_multithreading(rootnode) -> None:
    """PROBE_SOLVER_MULTITHREAD=1: flip BuiltConstraintSolver's own `multithreading`
    Data flag on (the flag gating doBuildSystem's parallel compliance-matrix
    assembly across l_constraintCorrections) — separate from OpenMP/BLAS
    threading, and separate from the lab's own base_scene multithreading arg.
    """
    if not _bool_env("PROBE_SOLVER_MULTITHREAD"):
        return
    solver = rootnode.getObject("ConstraintSolver")
    if solver is None:
        print("[probe] PROBE_SOLVER_MULTITHREAD requested but no ConstraintSolver found", file=sys.stderr)
        return
    solver.multithreading = True
    print(f"[probe] ConstraintSolver.multithreading set to True (readback: {solver.multithreading.value})", file=sys.stderr)


def _create_minimal_scene(rootnode):
    """PROBE_SKIP_GRIPPER path: cube + floor + gravity only, no Emio/gripper/motor playback."""
    import utils.header as uh

    settings, modelling, simulation = uh.addHeader(
        rootnode,
        inverse=False,
        withCollision=True,
        friction=float(os.environ.get("SHAPEOPT_FRICTION_COEF", "1.2")),
        multithreading=False,
    )
    uh.addSolvers(simulation)

    uncoupled = _bool_env("PROBE_UNCOUPLED_CORRECTION")
    if uncoupled:
        shared_correction = simulation.getObject("GenericConstraintCorrection")
        if shared_correction is not None:
            simulation.removeObject(shared_correction)
            print("[probe] removed shared GenericConstraintCorrection", file=sys.stderr)

    from labtests.core.plugins import add_required_plugins
    add_required_plugins(simulation)
    simulation.addObject(
        "RequiredPlugin", name="Sofa.Component.Constraint.Projective", printLog=False
    )

    rootnode.animate = True
    rootnode.dt = DT
    rootnode.gravity = [0.0, -9810.0, 0.0]

    local_min_dist = rootnode.getObject("LocalMinDistance")
    if local_min_dist is not None and local_min_dist.getClassName() == "LocalMinDistance":
        rootnode.removeObject(local_min_dist)
        rootnode.addObject(
            "MinProximityIntersection", name="LocalMinDistance", alarmDistance=5.0, contactDistance=1.0,
        )

    constraint_solver = rootnode.getObject("ConstraintSolver")
    if constraint_solver is not None:
        constraint_solver.tolerance = 1e-3
        constraint_solver.maxIterations = 250

    from labtests.core.scene_defaults import FLOOR_CENTER_Y, CUBE_SPAWN_CLEARANCE, CUBE_MASS_START

    # Bare cube + floor, no gripper/ContactListener wiring — cube_floor.py's
    # setup() insists on gripper finger nodes for that, which the minimal
    # scene doesn't have.
    cube_scale = [8.0, 8.0, 8.0]
    floor_scale = [2.0, 1.0, 2.0]
    cube_spawn_y = FLOOR_CENTER_Y + (cube_scale[1] + floor_scale[1]) * 0.5 + CUBE_SPAWN_CLEARANCE

    # Same inertia as cube_floor.py's real setup() (rotation_resistance=5.0,
    # side lengths = 2*scale) — a naive identity inertia lets the cube tumble
    # wildly on any asymmetric impulse and swamps the comparison with noise
    # unrelated to the actual bug.
    side = 2.0 * cube_scale[0]
    inertia_diag = (side**2 + side**2) / 12.0 * 5.0
    cube_inertia = [inertia_diag, 0.0, 0.0, 0.0, inertia_diag, 0.0, 0.0, 0.0, inertia_diag]

    cube = simulation.addChild("Cube")
    cube.addObject(
        "MechanicalObject",
        template="Rigid3",
        position=[[0.0, cube_spawn_y, 0.0] + _cube_orientation()],
        showObject=True,
    )
    cube.addObject("UniformMass", name="cube_mass", vertexMass=[CUBE_MASS_START, 1.0, cube_inertia])
    if uncoupled:
        cube.addObject("UncoupledConstraintCorrection")
    collision = cube.addChild("collision")
    collision.addObject("MeshOBJLoader", name="loader", filename="mesh/cube.obj", triangulate="true", scale3d=cube_scale)
    collision.addObject("MeshTopology", src="@loader")
    collision.addObject("MechanicalObject")
    collision.addObject("TriangleCollisionModel", name="cubeCollisionTriangles", group=2, moving=True, simulated=True)
    collision.addObject("LineCollisionModel", name="cubeCollisionLines", group=2, moving=True, simulated=True)
    collision.addObject("PointCollisionModel", name="cubeCollisionPoints", group=2, moving=True, simulated=True)
    collision.addObject("RigidMapping")

    floor = simulation.addChild("floor")
    floor.addObject("MechanicalObject", name="mstate", template="Rigid3", translation2=[0.0, FLOOR_CENTER_Y, 0.0], rotation2=[0.0, 0.0, 0.0])
    floor.addObject("UniformMass", name="mass", vertexMass=[0.10, 1.0, [1.0, 0, 0, 0, 1.0, 0, 0, 0, 1.0]])
    floor.addObject("FixedConstraint", indices="0")
    if uncoupled:
        floor.addObject("UncoupledConstraintCorrection")
    floor_collis = floor.addChild("collision")
    floor_collis.addObject("MeshOBJLoader", name="loader", filename="mesh/floor.obj", triangulate="true", scale3d=floor_scale)
    floor_collis.addObject("MeshTopology", src="@loader")
    floor_collis.addObject("MechanicalObject")
    floor_collis.addObject("TriangleCollisionModel", moving=False, simulated=False, group=3)
    floor_collis.addObject("LineCollisionModel", moving=False, simulated=False, group=3)
    floor_collis.addObject("PointCollisionModel", moving=False, simulated=False, group=3)
    floor_collis.addObject("RigidMapping")

    _swap_narrowphase(rootnode)
    _retighten_solver(rootnode)
    _set_solver_multithreading(rootnode)
    _enable_lcp_dump(rootnode)
    _enable_broadphase_dump(rootnode)
    return rootnode


def _create_legs_only_scene(rootnode):
    """PROBE_LEGS_ONLY path: same as build_base_scene() but centerPartName=None,
    so Emio builds the 4 legs + platform and never constructs a centerpart/gripper
    at all. Mirrors labtests/core/base_scene.py's build_base_scene() exactly,
    minus the centerpart — kept in sync by hand since this is a throwaway probe.
    """
    from utils.header import addHeader, addSolvers  # type: ignore
    from parts.emio import Emio  # type: ignore
    from labtests.core.modules.cube_floor import setup as setup_cube_floor
    from labtests.core.plugins import add_required_plugins
    from labtests.core.scene_config import PlaybackConfig
    from names import LEG_NAME

    cfg = PlaybackConfig.from_env(LAB_ROOT)

    settings, modelling, simulation = addHeader(
        rootnode, inverse=False, withCollision=True, friction=cfg.friction_coef, multithreading=False,
    )
    addSolvers(simulation)
    rootnode.animate = True
    rootnode.dt = DT
    rootnode.gravity = [0.0, -9810.0, 0.0]

    local_min_dist = rootnode.getObject("LocalMinDistance")
    if local_min_dist is not None and local_min_dist.getClassName() == "LocalMinDistance":
        rootnode.removeObject(local_min_dist)
        rootnode.addObject("MinProximityIntersection", name="LocalMinDistance", alarmDistance=5.0, contactDistance=1.0)

    constraint_solver = rootnode.getObject("ConstraintSolver")
    if constraint_solver is not None:
        constraint_solver.tolerance = 1e-3
        constraint_solver.maxIterations = 250

    leg_name = os.environ.get("OPT_LEG_NAME", LEG_NAME)
    emio = Emio(
        name="Emio",
        legsName=[leg_name],
        legsModel=["beam"],
        legsPositionOnMotor=["counterclockwisedown", "clockwisedown", "counterclockwisedown", "clockwisedown"],
        # The runtime default for this Data field is "" (empty string), not the
        # Python None the docstring implies — Emio's own check is
        # `centerPartName.value != "None"` (the literal 4-char string), which is
        # the actual documented way to skip building a centerpart.
        centerPartName="None",
        platformLevel=2,
        extended=True,
    )
    if not emio.isValid():
        print("[probe] Emio (legs-only) failed isValid() — bailing out", file=sys.stderr)
        return None
    simulation.addChild(emio)
    # No attachCenterPartToLegs(): would crash (self.centerpart is None with no gripper).

    add_required_plugins(simulation)

    cube_handles = setup_cube_floor(
        simulation,
        [],  # no gripper fingers to wire ContactListeners against
        cube_scale=[8, 8, 8],
        cube_mass=cfg.cube_mass_start,
        floor_center_y=cfg.floor_center_y,
        cube_spawn_clearance=cfg.cube_spawn_clearance,
    )
    if _bool_env("PROBE_CUBE_UNREACHABLE"):
        # Same cube/floor/collision infrastructure as the baseline, just
        # spawned far enough away that it cannot fall into contact range
        # with the legs within the probe's step window.
        spawn_y = cube_handles.cube_spawn_y + 1.0e6
        print(f"[probe] PROBE_CUBE_UNREACHABLE: cube spawned at y={spawn_y} (unreachable)", file=sys.stderr)
    else:
        spawn_y = cube_handles.cube_spawn_y
    cube_handles.cube.MechanicalObject.position = [
        [0.0, spawn_y, 0.0] + _cube_orientation()
    ]

    _swap_narrowphase(rootnode)
    _retighten_solver(rootnode)
    _set_solver_multithreading(rootnode)
    _enable_lcp_dump(rootnode)
    _enable_broadphase_dump(rootnode)
    return rootnode


def createScene(rootnode):
    """Build the grasp_hold_probe scene, honoring PROBE_* strip toggles."""
    if _bool_env("PROBE_SKIP_GRIPPER"):
        return _create_minimal_scene(rootnode)
    if _bool_env("PROBE_LEGS_ONLY"):
        return _create_legs_only_scene(rootnode)

    import Sofa.Core  # type: ignore

    from labtests.core.base_scene import build_base_scene
    from labtests.core.modules.collision_stl import setup as setup_collision
    from labtests.core.modules.cube_floor import setup as setup_cube_floor
    from labtests.core.modules.motor_playback import setup as setup_playback
    from labtests.core.playback_controller import make_playback_controller
    from labtests.core.plugins import add_required_plugins
    from labtests.core.scene_config import PlaybackConfig

    cfg = PlaybackConfig.from_env(LAB_ROOT)

    nodes = build_base_scene(rootnode, inverse=False, friction=cfg.friction_coef)
    if nodes is None:
        return
    print(f"[contact] friction configured with mu={cfg.friction_coef:.6f}")
    print(f"[cube] mass_start={cfg.cube_mass_start} kg (default unless CUBE_MASS_START set)")

    add_required_plugins(nodes.simulation)
    rootnode.dt = DT

    gripper_collision = setup_collision(
        nodes.emio, cfg.gripper_finger1_mesh_path, cfg.gripper_finger2_mesh_path
    )

    cube_handles = setup_cube_floor(
        nodes.simulation,
        gripper_collision,
        cube_scale=[8, 8, 8],
        cube_mass=cfg.cube_mass_start,
        floor_center_y=cfg.floor_center_y,
        cube_spawn_clearance=cfg.cube_spawn_clearance,
    )

    writer = cfg.trial.attach(rootnode)

    if _bool_env("PROBE_SKIP_PLAYBACK"):
        print("[probe] PROBE_SKIP_PLAYBACK: robot built but never driven — no PlaybackController attached", file=sys.stderr)
        if _bool_env("PROBE_CUBE_UNREACHABLE"):
            spawn_y = cube_handles.cube_spawn_y + 1.0e6
            print(f"[probe] PROBE_CUBE_UNREACHABLE: cube spawned at y={spawn_y} (unreachable)", file=sys.stderr)
        else:
            spawn_y = cube_handles.cube_spawn_y
        cube_handles.cube.MechanicalObject.position = [
            [0.0, spawn_y, 0.0] + _cube_orientation()
        ]
    else:
        playback = setup_playback(nodes.emio, RECORD_FILE)
        Base = make_playback_controller(Sofa.Core.Controller)
        nodes.simulation.addObject(
            Base(
                name="PlaybackController",
                rootnode=rootnode,
                playback=playback,
                cube_handles=cube_handles,
                gripper_collision=gripper_collision,
                writer=writer,
                cfg=cfg,
            )
        )

    _swap_narrowphase(rootnode)
    _retighten_solver(rootnode)
    _set_solver_multithreading(rootnode)
    _enable_lcp_dump(rootnode)
    _enable_broadphase_dump(rootnode)
    return rootnode
