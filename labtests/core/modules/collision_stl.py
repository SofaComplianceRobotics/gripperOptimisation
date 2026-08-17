"""
collision_stl — Attach the gripper's two finger collision meshes (STL files).

Each finger is loaded as its own CollisionModel node with a distinct SOFA
collision `group`. Groups matter: SOFA skips contact generation between any
two collision models that share a group id, which is exactly how a single
merged whole-gripper mesh (the old approach here) could never register a
finger-vs-finger contact — both fingers were literally the same model/group.
Splitting them into two models with two different groups lets SOFA's narrow
phase test finger1 against finger2 while each still collides normally with
the cube (group 2) and floor (group 3) set up in cube_floor.py.

Used by all direct-mode tests. Not compatible with inverse mode. The returned
list of finger nodes must be passed to other modules that need per-finger
collision access (e.g. cube_floor for ContactListener wiring).
"""

from __future__ import annotations

# Distinct from cube_floor.py's group=2 (cube) and group=3 (floor), and from
# each other, so every pair of the four bodies (finger1, finger2, cube,
# floor) is eligible for contact detection.
_FINGER_GROUPS = (1, 4)


def setup(emio, finger1_stl_path: str, finger2_stl_path: str) -> list:
    """Add the two finger collision meshes as child nodes of the gripper.

    Args:
        emio: The assembled Emio object from base_scene.
        finger1_stl_path: Absolute path to finger 1's collision STL.
        finger2_stl_path: Absolute path to finger 2's collision STL.

    Returns:
        [finger1_node, finger2_node] — SOFA nodes carrying each finger's
        collision geometry, in that order. Store this — other modules (e.g.
        cube_floor, and the _sim_query helpers) operate over both.
    """
    fingers = []
    for i, (stl_path, group) in enumerate(
        zip((finger1_stl_path, finger2_stl_path), _FINGER_GROUPS), start=1
    ):
        finger = emio.centerpart.addChild(f"CollisionModelFinger{i}")
        finger.addObject("MeshSTLLoader", name="loader", filename=stl_path)
        finger.addObject("MeshTopology", src="@loader")
        finger.addObject("MechanicalObject")
        finger.addObject(
            "PointCollisionModel", name="gripperCollisionPoints", group=group
        )
        finger.addObject(
            "LineCollisionModel", name="gripperCollisionLines", group=group
        )
        finger.addObject(
            "TriangleCollisionModel", name="gripperCollisionTriangles", group=group
        )
        finger.addObject("SkinningMapping")
        fingers.append(finger)

    return fingers
