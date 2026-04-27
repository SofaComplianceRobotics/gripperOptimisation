"""
Lab ShapeOPT Inverse Scene - Manual inverse-mode control.

Use this to manually drive the gripper via the inverse solver GUI.
"""

import os
import sys
from pathlib import Path

sys.path.append(os.path.dirname(os.path.realpath(__file__)) + "/../../")

LAB_ROOT = Path(__file__).resolve().parent
APP_SRC = LAB_ROOT / "app" / "src"
if str(APP_SRC) not in sys.path:
    sys.path.insert(0, str(APP_SRC))


def createScene(rootnode):
    """Build the inverse-mode scene for manual gripper control via the SOFA ImGui."""
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

    if args.connection:
        emio.addConnectionComponents()

    return rootnode
