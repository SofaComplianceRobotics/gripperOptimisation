"""Shared assembly for the manual inverse-control scenes.

lab_shapeOPT_inverse and lab_shapeOPT_recording drive the same robot with
the same effector-target and ImGui setup; they differ only in what they add
on top. This module owns the common part.
"""

from pathlib import Path

from labtests.core.base_scene import build_base_scene


def build_manual_scene(rootnode, lab_root: Path):
    """Build the shared manual-control scene: robot, tray, effector target, ImGui.

    Args:
        rootnode: SOFA root node passed in by createScene().
        lab_root: Lab root directory (locates the tray mesh).

    Returns:
        Tuple (nodes, args). `nodes` is the SceneNodes from build_base_scene,
        or None when the robot failed to assemble — the caller must bail out.
        `args` is the parsed runSofa CLI namespace (provides args.connection).
    """
    import Sofa.ImGui as MyGui
    from parts.controllers.assemblycontroller import AssemblyController
    from parts.emio import getParserArgs

    args = getParserArgs()

    nodes = build_base_scene(rootnode, inverse=True, multithreading=True)
    if nodes is None:
        return None, args

    modelling, emio = nodes.modelling, nodes.emio

    assembly = AssemblyController(emio)
    assembly.duration = 0.1
    emio.addObject(assembly)

    # --- Visual tray (display only, no collision) ---
    tray = modelling.addChild("Tray")
    tray_mesh_path = str(
        (lab_root.parent.parent / "data" / "meshes" / "tray.stl").resolve()
    )
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

    return nodes, args