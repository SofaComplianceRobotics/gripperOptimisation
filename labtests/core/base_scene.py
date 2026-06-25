"""
Core scene builder shared by all ShapeOPT tests.

Every test calls build_base_scene() to get a configured rootnode,
the three standard SOFA node handles, and the assembled Emio robot.
Nothing test-specific lives here.
"""

from __future__ import annotations

import os
from typing import NamedTuple

from geometry.timing_config import DT_INVERSE, DT_DIRECT
from names import GRIPPER_NAME, LEG_NAME


class SceneNodes(NamedTuple):
    """Handles returned to the test scene after base setup."""

    rootnode: object
    settings: object
    modelling: object
    simulation: object
    emio: object


def build_base_scene(
    rootnode,
    *,
    inverse: bool,
    friction: float = 0.6,
    multithreading: bool = False,
) -> SceneNodes:
    """Configure rootnode and build the Emio robot.

    This is the only code that runs for every single test.
    Modules and hooks are layered on top by each test's scene.py.

    Args:
        rootnode: SOFA root node passed in by createScene().
        inverse: True → inverse solver header (tilt, manual control).
                 False → direct/forward dynamics header (grasp, scoring).
        friction: Contact friction coefficient (direct mode only; ignored for
            inverse scenes which have no collision pipeline).
        multithreading: Enable SOFA multithreading. Off for optimization runs
            (many parallel SOFA processes), on for interactive manual scenes.

    Returns:
        SceneNodes with (rootnode, settings, modelling, simulation, emio).
    """
    from utils.header import addHeader, addSolvers  # type: ignore
    from parts.gripper import Gripper  # type: ignore
    from parts.emio import Emio  # type: ignore

    import utils.header as _uh  # diagnostic: which utils tree are we loading?

    print(f"[env] utils.header loaded from {_uh.__file__}")

    settings, modelling, simulation = addHeader(
        rootnode,
        inverse=inverse,
        withCollision=not inverse,
        friction=friction,
        multithreading=multithreading,
    )

    addSolvers(simulation)

    force_paused = os.environ.get("SHAPEOPT_FORCE_PAUSED", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    rootnode.animate = False if force_paused else not inverse
    rootnode.dt = DT_INVERSE if inverse else DT_DIRECT
    rootnode.gravity = [0.0, -9810.0, 0.0]
    rootnode.VisualStyle.displayFlags.value = ["hideBehavior", "hideWireframe"]

    if not inverse:
        # SOFA builds differ in the intersection method addHeader installs. Some
        # use the LocalMinDistance component, which prunes contacts to local
        # minima and leaves a flat cube resting on too few points, so it tips and
        # tunnels through the floor. Normalize to MinProximityIntersection, which
        # keeps the broader contact set a stable flat cube-floor grasp needs.
        local_min_dist = rootnode.getObject("LocalMinDistance")
        _isect_class = None if local_min_dist is None else local_min_dist.getClassName()
        print(f"[collision] intersection method on load: {_isect_class}")
        if local_min_dist is not None and _isect_class == "LocalMinDistance":
            rootnode.removeObject(local_min_dist)
            rootnode.addObject(
                "MinProximityIntersection",
                name="LocalMinDistance",
                alarmDistance=5.0,
                contactDistance=1.0,
            )
            local_min_dist = rootnode.getObject("LocalMinDistance")
            print(f"[collision] swapped intersection -> {local_min_dist.getClassName()}")

        if local_min_dist is not None:
            # alarmDistance must stay above the cube's per-step fall distance at
            # floor impact (~4.4mm after the spawn-clearance drop) so contacts
            # are detected before it tunnels. contactDistance tightened to 1.0mm
            # (from 1.5) to reduce the cushion the cube rested on without
            # starving the flat cube-floor contact.
            local_min_dist.alarmDistance = 5.0
            local_min_dist.contactDistance = 1.0

        # Relax the contact constraint solver (lab-local; the shared
        # utils.header sets it to tolerance=1e-10 / maxIterations=1500, which is
        # research-grade precision a grasp demo does not need). Every contact is
        # an iterative Lagrangian constraint, so loosening these is the cheapest
        # way to keep the sim interactive when many contacts are active. Kept
        # here (not in utils.header) so other labs are unaffected.
        constraint_solver = rootnode.getObject("ConstraintSolver")
        if constraint_solver is not None:
            constraint_solver.tolerance = 1e-3
            constraint_solver.maxIterations = 250

    # Gripper finger stiffness. The measured beam value (parameters.youngModulus
    # = 3.5e4) leaves the fingers too stiff to conform to the rigid cube: they
    # stay rigid under the squeeze and the cube is ejected instead of held.
    # Softening the gripper centerpart ~10x lets the fingers wrap around and hold
    # it. Deliberately unphysical, but required for a stable grasp in this
    # rigid-cube setup. Direct (grasp) scenes only — the inverse control scene
    # keeps the measured stiffness. Override with SHAPEOPT_YOUNG_MODULUS.
    GRIPPER_YOUNG_MODULUS = 3.5e3
    emio_kwargs: dict = {}
    if not inverse:
        ym = float(os.environ.get("SHAPEOPT_YOUNG_MODULUS", GRIPPER_YOUNG_MODULUS))
        emio_kwargs["centerPartYoungModulus"] = ym
        print(f"[gripper] centerPartYoungModulus = {ym}")

    emio = Emio(
        name="Emio",
        legsName=[LEG_NAME],
        legsModel=["beam"],
        legsPositionOnMotor=[
            "counterclockwisedown",
            "clockwisedown",
            "counterclockwisedown",
            "clockwisedown",
        ],
        centerPartName=GRIPPER_NAME,
        centerPartType="deformable",
        centerPartModel="beam",
        centerPartClass=Gripper,
        platformLevel=2,
        extended=True,
        **emio_kwargs,
    )

    if not emio.isValid():
        return None  # caller should check and bail out of createScene

    simulation.addChild(emio)
    emio.attachCenterPartToLegs()

    return SceneNodes(rootnode, settings, modelling, simulation, emio)
