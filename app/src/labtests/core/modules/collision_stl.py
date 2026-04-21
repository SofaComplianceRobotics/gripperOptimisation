"""
Module: collision_stl

Attaches a collision mesh (STL file) to the gripper center part.
Used by all direct-mode tests. Not compatible with inverse mode.

Usage:
    from labtests.core.modules.collision_stl import setup
    gripper_collision = setup(emio, stl_path)
    # gripper_collision is the SOFA node — pass it to other modules that need it
    # (e.g. cube_floor needs it for the ContactListener)
"""

from __future__ import annotations


def setup(emio, stl_path: str):
    """
    Add a collision model child node to emio.centerpart.

    Inputs:
        emio:     The assembled Emio object from base_scene.
        stl_path: Absolute path to the gripper collision STL file.

    Returns:
        gripper_collision: The SOFA child node carrying the collision geometry.
                           Store this — other modules reference it.
    """
    gripper_collision = emio.centerpart.addChild("CollisionModel")
    gripper_collision.addObject("MeshSTLLoader", name="loader", filename=stl_path)
    gripper_collision.addObject("MeshTopology", src="@loader")
    gripper_collision.addObject("MechanicalObject")
    gripper_collision.addObject("PointCollisionModel", group=1)
    gripper_collision.addObject("LineCollisionModel", group=1)
    gripper_collision.addObject(
        "TriangleCollisionModel", name="gripperCollisionTriangles", group=1
    )
    gripper_collision.addObject("SkinningMapping")

    return gripper_collision
