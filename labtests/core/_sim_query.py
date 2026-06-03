"""Low-level SOFA node queries for reading and writing simulation state."""

from __future__ import annotations


def get_cube_y(rootnode) -> float:
    """Return the current Y position of the cube centre of mass.

    Args:
        rootnode: SOFA root node.

    Returns:
        Y coordinate of the cube mechanical state.
    """
    return float(
        rootnode.Simulation.Cube.getMechanicalState().position.value[0][1]
    )


def set_cube_mass(rootnode, value: float) -> None:
    """Set the cube's total mass.

    Clamped to 0.0001 to avoid SOFA physics instability at near-zero mass.

    Args:
        rootnode: SOFA root node.
        value: Desired mass value.
    """
    mass = max(0.0001, float(value))
    try:
        rootnode.Simulation.Cube.cube_mass.totalMass.value = mass
    except Exception:
        pass


def get_cube_collision_min_y(rootnode) -> float | None:
    """Return the minimum Y of all cube collision mesh vertices.

    Args:
        rootnode: SOFA root node.

    Returns:
        Minimum Y coordinate, or None if the node is unavailable.
    """
    try:
        points = rootnode.Simulation.Cube.collision.getMechanicalState().position.value
        ys = [float(p[1]) for p in points if len(p) >= 2]
        return min(ys) if ys else None
    except Exception:
        return None


def get_gripper_collision_min_y(gripper_collision) -> float | None:
    """Return the minimum Y of all gripper collision mesh vertices.

    Args:
        gripper_collision: SOFA gripper collision node.

    Returns:
        Minimum Y coordinate, or None if the node is unavailable.
    """
    try:
        points = gripper_collision.getMechanicalState().position.value
        ys = [float(p[1]) for p in points if len(p) >= 2]
        return min(ys) if ys else None
    except Exception:
        return None


def collision_aabb(collision_node) -> tuple | None:
    """Return the axis-aligned bounding box of a collision node.

    Args:
        collision_node: SOFA collision node with a mechanical state.

    Returns:
        Tuple (xmin, xmax, ymin, ymax, zmin, zmax), or None if unavailable.
    """
    try:
        points = collision_node.getMechanicalState().position.value
    except Exception:
        return None
    if not len(points):
        return None
    xs = [float(p[0]) for p in points if len(p) >= 3]
    ys = [float(p[1]) for p in points if len(p) >= 3]
    zs = [float(p[2]) for p in points if len(p) >= 3]
    if not xs:
        return None
    return min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)


def get_cube_gripper_contact_count(rootnode) -> int:
    """Return the number of active contact points between cube and gripper.

    Args:
        rootnode: SOFA root node.

    Returns:
        Contact count, or 0 if the listener object is missing.
    """
    try:
        listener = rootnode.Simulation.getObject("cubeGripperContactListener")
        return int(listener.getNumberOfContacts())
    except Exception:
        return 0


def spawn_overlap_detected(rootnode, gripper_collision) -> bool:
    """Return True if the cube and gripper overlap at the moment of spawn.

    Uses the contact listener first; falls back to AABB intersection when the
    listener reports zero contacts (contacts may not register on the very first
    frame after teleport).

    Args:
        rootnode: SOFA root node.
        gripper_collision: SOFA gripper collision node.

    Returns:
        True if an overlap is detected.
    """
    if get_cube_gripper_contact_count(rootnode) > 0:
        return True
    cube_aabb = collision_aabb(rootnode.Simulation.Cube.collision)
    gripper_aabb = collision_aabb(gripper_collision)
    if cube_aabb is None or gripper_aabb is None:
        return False
    cx0, cx1, cy0, cy1, cz0, cz1 = cube_aabb
    gx0, gx1, gy0, gy1, gz0, gz1 = gripper_aabb
    return (
        cx0 <= gx1
        and cx1 >= gx0
        and cy0 <= gy1
        and cy1 >= gy0
        and cz0 <= gz1
        and cz1 >= gz0
    )
