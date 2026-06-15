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
        local_min_dist = rootnode.getObject("LocalMinDistance")
        if local_min_dist is not None:
            # alarmDistance must stay above the cube's per-step fall distance at
            # floor impact (~4.4mm after the spawn-clearance drop) so contacts
            # are detected before it tunnels. contactDistance tightened to 1.0mm
            # (from 1.5) to reduce the cushion the cube rested on without
            # starving the flat cube-floor contact.
            local_min_dist.alarmDistance = 5.0
            local_min_dist.contactDistance = 1.0

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
    )

    if not emio.isValid():
        return None  # caller should check and bail out of createScene

    simulation.addChild(emio)
    emio.attachCenterPartToLegs()

    return SceneNodes(rootnode, settings, modelling, simulation, emio)
