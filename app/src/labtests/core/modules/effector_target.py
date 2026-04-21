"""
Module: effector_target

Adds the inverse-mode effector MechanicalObject, a controllable target,
and wires up the ImGui GUI controls (move window, program window, IO window).

Used by all inverse-mode tests (gripper_tilt, future manual-control tests).
Not compatible with direct mode.

Usage:
    from labtests.core.modules.effector_target import setup, EffectorHandles
    handles = setup(nodes, emio, config)
    # handles.effector_mo    — effector MechanicalObject
    # handles.target_mo      — target MechanicalObject (set position to move gripper)
    # handles.effector_target_node  — the SOFA Target node itself
"""

from __future__ import annotations

import os
from typing import NamedTuple


class EffectorHandles(NamedTuple):
    """Inverse-mode objects a hook controller will typically need."""

    effector_mo: object  # emio.effector MechanicalState
    target_mo: object  # Target node MechanicalState
    effector_target_node: object  # The full Target SOFA node


def setup(
    nodes,  # SceneNodes from base_scene
    emio,
    *,
    initial_target_pos: list[float] | None = None,
    gripper_opening_min: float = 5.0,
    gripper_opening_max: float = 70.0,
    program_file: str | None = None,
    io_gripper_path: str = "/Gripper",
) -> EffectorHandles:
    """
    Add effector MO, effector target, inverse components, and ImGui controls.

    Inputs:
        nodes:               SceneNodes from base_scene (provides modelling node).
        emio:                The assembled Emio object.
        initial_target_pos:  7-element Rigid3 position for the target at t=0.
                             Default: [0, -150, 0, 0, 0, 0, 1]
        gripper_opening_min: Lower bound for opening slider (mm).
        gripper_opening_max: Upper bound for opening slider (mm).
        program_file:        Absolute path to a .crprog program file to pre-load,
                             or None to skip.
        io_gripper_path:     IOWindow subscription path for the gripper opening.

    Returns:
        EffectorHandles with (effector_mo, target_mo, effector_target_node)
    """
    import Sofa.ImGui as MyGui  # type: ignore

    if initial_target_pos is None:
        initial_target_pos = [0, -150, 0, 0, 0, 0, 1]

    modelling = nodes.modelling

    # ── Effector ──────────────────────────────────────────────────────────────

    emio.effector.addObject(
        "MechanicalObject",
        template="Rigid3",
        position=[0, 0, 0, 0, 0, 0, 1] * 4,
    )
    emio.effector.addObject("RigidMapping", rigidIndexPerPoint=[0, 1, 2, 3])

    # ── Effector target ───────────────────────────────────────────────────────

    effector_target = modelling.addChild("Target")
    effector_target.addObject("EulerImplicitSolver", firstOrder=True)
    effector_target.addObject(
        "CGLinearSolver", iterations=50, tolerance=1e-10, threshold=1e-10
    )
    effector_target.addObject(
        "MechanicalObject",
        template="Rigid3",
        position=[initial_target_pos],
        showObject=True,
        showObjectScale=20,
    )

    # ── Inverse components ────────────────────────────────────────────────────

    emio.addInverseComponentAndGUI(
        effector_target.getMechanicalState().position.linkpath, barycentric=True
    )

    TCP = modelling.addChild("TCP")
    TCP.addObject(
        "MechanicalObject",
        template="Rigid3",
        position=emio.effector.EffectorCoord.barycenter.linkpath,
    )
    MyGui.setIPController(
        nodes.rootnode.Modelling.Target, TCP, nodes.rootnode.ConstraintSolver
    )

    # ── ImGui controls ────────────────────────────────────────────────────────

    rest_lengths = emio.centerpart.Effector.Distance.DistanceMapping.restLengths

    MyGui.MoveWindow.addAccessory(
        "Gripper's opening (mm)",
        rest_lengths,
        gripper_opening_min,
        gripper_opening_max,
    )
    MyGui.ProgramWindow.addGripper(
        rest_lengths, gripper_opening_min, gripper_opening_max
    )

    if program_file and os.path.exists(program_file):
        MyGui.ProgramWindow.importProgram(program_file)

    MyGui.IOWindow.addSubscribableData(io_gripper_path, rest_lengths)

    effector_mo = emio.effector.getMechanicalState()
    target_mo = effector_target.getMechanicalState()

    return EffectorHandles(effector_mo, target_mo, effector_target)
