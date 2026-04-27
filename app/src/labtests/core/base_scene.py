"""
Core scene builder shared by all ShapeOPT tests.

Every test calls build_base_scene() to get a configured rootnode,
the three standard SOFA node handles, and the assembled Emio robot.
Nothing test-specific lives here.
"""

from __future__ import annotations

from typing import NamedTuple


class SceneNodes(NamedTuple):
    """Handles returned to the test scene after base setup."""

    rootnode: object
    settings: object
    modelling: object
    simulation: object
    emio: object


def build_base_scene(rootnode, *, inverse: bool, friction: float = 0.6) -> SceneNodes:
    """Configure rootnode and build the Emio robot.

    This is the only code that runs for every single test.
    Modules and hooks are layered on top by each test's scene.py.

    Args:
        rootnode: SOFA root node passed in by createScene().
        inverse: True → inverse solver header (tilt, manual control).
                 False → direct/forward dynamics header (grasp, scoring).
        friction: Contact friction coefficient (direct mode only; ignored for
            inverse scenes which have no collision pipeline).

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
        multithreading=False,
    )

    addSolvers(simulation)

    rootnode.animate = not inverse  # inverse scenes start paused for GUI control
    rootnode.dt = 0.05 if inverse else 0.01
    rootnode.gravity = [0.0, -9810.0, 0.0]
    rootnode.VisualStyle.displayFlags.value = ["hideBehavior", "hideWireframe"]

    if not inverse:
        local_min_dist = rootnode.getObject("LocalMinDistance")
        if local_min_dist is not None:
            local_min_dist.alarmDistance = 5
            local_min_dist.contactDistance = 1.5

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
        return None  # caller should check and bail out of createScene

    simulation.addChild(emio)
    emio.attachCenterPartToLegs()

    return SceneNodes(rootnode, settings, modelling, simulation, emio)
