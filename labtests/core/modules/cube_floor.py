"""
cube_floor — Add a graspable cube and static floor to the simulation node.

Used by all direct-mode tests. Not compatible with inverse mode. The playback
controller is responsible for teleporting the cube to cube_spawn_y at the right
simulation time.
"""

from __future__ import annotations

import os
from typing import NamedTuple


class CubeFloorHandles(NamedTuple):
    """Returned by setup() so the test controller can access these nodes."""

    cube: object
    floor: object
    collision: object  # cube.collision child node
    cube_spawn_y: float  # pre-computed spawn height


def setup(
    simulation,
    gripper_collision,
    *,
    cube_scale: list[float] | None = None,
    cube_mass: float = 0.10,
    floor_center_y: float = -220.0,
    cube_spawn_clearance: float = 10.0,
) -> CubeFloorHandles:
    """Add cube and floor rigid bodies to the simulation node.

    The cube is placed above the scene before spawn; the playback controller
    teleports it to cube_spawn_y at the configured simulation time.

    Args:
        simulation: SOFA simulation node from base_scene.
        gripper_collision: Node returned by collision_stl.setup(), needed to
            wire the ContactListener.
        cube_scale: [x, y, z] scale for the cube mesh. Default [5, 5, 5].
        cube_mass: Initial uniform mass for the cube (kg).
        floor_center_y: Y position of the floor centre.
        cube_spawn_clearance: Extra gap between floor top and cube bottom at spawn.

    Returns:
        CubeFloorHandles with (cube, floor, collision, cube_spawn_y).
    """
    if cube_scale is None:
        cube_scale = [5.0, 5.0, 5.0]

    floor_scale = [2.0, 1.0, 2.0]
    cube_spawn_y = (
        floor_center_y + (cube_scale[1] + floor_scale[1]) * 0.5 + cube_spawn_clearance
    )

    total_mass = 0.10
    volume = 1.0
    inertia_matrix = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]

    # ── Cube ──────────────────────────────────────────────────────────────────

    # Mass-normalized inertia of a solid box (mesh/cube.obj spans ±1, so the
    # full side length is 2 × scale). SOFA multiplies this matrix by the mass
    # internally. NOTE: setting UniformMass.totalMass at runtime RESETS this to
    # identity, so the controller must NOT re-set the mass every frame at a
    # constant value — it only changes mass during the overload ramp.
    side_x, side_y, side_z = (2.0 * s for s in cube_scale)
    inertia_xx = (side_y**2 + side_z**2) / 12.0
    inertia_yy = (side_x**2 + side_z**2) / 12.0
    inertia_zz = (side_x**2 + side_y**2) / 12.0
    cube_inertia = [
        inertia_xx, 0.0, 0.0, 0.0, inertia_yy, 0.0, 0.0, 0.0, inertia_zz
    ]

    cube = simulation.addChild("Cube")
    cube.addObject(
        "MechanicalObject",
        template="Rigid3",
        position=[[0.0, cube_spawn_y, 0.0, 0.0, 0.0, 0.0, 1.0]],
        showObject=True,
    )
    cube.addObject(
        "UniformMass",
        name="cube_mass",
        vertexMass=[cube_mass, 1.0, cube_inertia],
    )

    visu_cube = cube.addChild("Visual")
    visu_cube.addObject(
        "MeshOBJLoader", name="loader", filename="mesh/cube.obj", scale3d=cube_scale
    )
    visu_cube.addObject(
        "OglModel", name="cubeVisual", src=visu_cube.loader.linkpath, color=[1, 0, 0, 1]
    )
    visu_cube.addObject("RigidMapping")

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

    # MinProximityIntersection only generates point↔triangle and line↔line
    # contacts, never triangle↔triangle, so the listener above stays empty and
    # cannot measure the grip. These watch the channels that actually carry the
    # contacts. Created only when contact debugging is on (each listener walks
    # its contact list every step), and consumed by playback_controller.
    if os.environ.get("SHAPEOPT_DEBUG_CONTACTS", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        for model1, model2, suffix in (
            (
                gripper_collision.gripperCollisionPoints,
                collision.cubeCollisionTriangles,
                "gPcT",
            ),
            (
                gripper_collision.gripperCollisionTriangles,
                collision.cubeCollisionPoints,
                "gTcP",
            ),
            (
                gripper_collision.gripperCollisionLines,
                collision.cubeCollisionLines,
                "gLcL",
            ),
        ):
            simulation.addObject(
                "ContactListener",
                name=f"cubeGripperContactDbg_{suffix}",
                collisionModel1=model1.getLinkPath(),
                collisionModel2=model2.getLinkPath(),
            )

    # ── Floor ─────────────────────────────────────────────────────────────────

    floor = simulation.addChild("floor")
    floor.addObject(
        "MechanicalObject",
        name="mstate",
        template="Rigid3",
        translation2=[0.0, floor_center_y, 0.0],
        rotation2=[0.0, 0.0, 0.0],
        showObjectScale=5.0,
    )
    floor.addObject(
        "UniformMass",
        name="mass",
        vertexMass=[total_mass, volume, inertia_matrix[:]],
    )
    floor.addObject("FixedConstraint", indices="0")

    floor_collis = floor.addChild("collision")
    floor_collis.addObject(
        "MeshOBJLoader",
        name="loader",
        filename="mesh/floor.obj",
        triangulate="true",
        scale3d=floor_scale,
    )
    floor_collis.addObject("MeshTopology", src="@loader")
    floor_collis.addObject("MechanicalObject")
    floor_collis.addObject(
        "TriangleCollisionModel", moving=False, simulated=False, group=3
    )
    floor_collis.addObject("LineCollisionModel", moving=False, simulated=False, group=3)
    floor_collis.addObject(
        "PointCollisionModel", moving=False, simulated=False, group=3
    )
    floor_collis.addObject("RigidMapping")

    floor_visu = floor.addChild("VisualModel")
    floor_visu.addObject("MeshOBJLoader", name="loader", filename="mesh/floor.obj")
    floor_visu.addObject(
        "OglModel",
        name="model",
        src="@loader",
        scale3d=floor_scale,
        color=[1.0, 1.0, 0.0],
        updateNormals=False,
    )
    floor_visu.addObject("RigidMapping")

    return CubeFloorHandles(cube, floor, collision, cube_spawn_y)
