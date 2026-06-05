"""
Lab ShapeOPT Inverse Scene - Manual inverse-mode control.

Use this to manually drive the gripper via the inverse solver GUI.
"""

import os
import sys
from pathlib import Path

from launcher.bootstrap import bootstrap_lab

SCRIPT_DIR, SRC_ROOT, APP_ROOT, LAB_ROOT = bootstrap_lab(__file__)

from geometry.timing_config import DT_INVERSE


def createScene(rootnode):
    """Build the inverse-mode scene for manual gripper control via the SOFA ImGui."""
    from utils.header import addHeader, addSolvers
    from parts.gripper import Gripper
    from parts.controllers.assemblycontroller import AssemblyController
    import Sofa.ImGui as MyGui
    from parts.emio import Emio, getParserArgs

    args = getParserArgs()

    # --- Scene root and solvers ---
    settings, modelling, simulation = addHeader(rootnode, inverse=True)
    addSolvers(simulation)

    rootnode.dt = DT_INVERSE
    rootnode.gravity = [0.0, -9810.0, 0.0]
    rootnode.VisualStyle.displayFlags.value = ["hideBehavior", "hideWireframe"]

    # --- Robot ---
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

    # --- Visual tray (display only, no collision) ---
    tray = modelling.addChild("Tray")
    tray_mesh_path = str((LAB_ROOT.parent.parent / "data" / "meshes" / "tray.stl").resolve())
    tray.addObject(
        "MeshSTLLoader",
        filename=tray_mesh_path,
        translation=[0, 10, 0],
    )
    tray.addObject(
        "OglModel", src=tray.MeshSTLLoader.linkpath, color=[0.3, 0.3, 0.3, 0.2]
    )

    # --- Effector chain: 4-point Rigid3 frame mapped onto the gripper ---
    emio.effector.addObject(
        "MechanicalObject", template="Rigid3", position=[0, 0, 0, 0, 0, 0, 1] * 4
    )
    emio.effector.addObject("RigidMapping", rigidIndexPerPoint=[0, 1, 2, 3])

    # --- Inverse target: the ImGui-draggable Rigid3 the effector tracks ---
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

    # TCP mirrors the effector barycenter so the ImGui controller has a handle
    TCP = modelling.addChild("TCP")
    TCP.addObject(
        "MechanicalObject",
        template="Rigid3",
        position=emio.effector.EffectorCoord.barycenter.linkpath,
    )
    MyGui.setIPController(rootnode.Modelling.Target, TCP, rootnode.ConstraintSolver)

    # --- ImGui accessories: opening slider, program window, I/O stream ---
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

    if args.connection:
        emio.addConnectionComponents()

    return rootnode
