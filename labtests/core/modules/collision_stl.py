"""
collision_stl — Attach a collision mesh (STL file) to the gripper center part.

Used by all direct-mode tests. Not compatible with inverse mode. The returned
node must be passed to other modules that require it (e.g. cube_floor for
ContactListener wiring).
"""

from __future__ import annotations


def setup(emio, stl_path: str):
    """Add a collision model child node to emio.centerpart.

    Args:
        emio: The assembled Emio object from base_scene.
        stl_path: Absolute path to the gripper collision STL file.

    Returns:
        The SOFA child node carrying the collision geometry. Store this — other
        modules (e.g. cube_floor) reference it for contact detection.
    """
    gripper_collision = emio.centerpart.addChild("CollisionModel")
    gripper_collision.addObject("MeshSTLLoader", name="loader", filename=stl_path)
    gripper_collision.addObject("MeshTopology", src="@loader")
    gripper_collision.addObject("MechanicalObject")
    gripper_collision.addObject(
        "PointCollisionModel", name="gripperCollisionPoints", group=1
    )
    gripper_collision.addObject(
        "LineCollisionModel", name="gripperCollisionLines", group=1
    )
    gripper_collision.addObject(
        "TriangleCollisionModel", name="gripperCollisionTriangles", group=1
    )
    gripper_collision.addObject("SkinningMapping")

    return gripper_collision
