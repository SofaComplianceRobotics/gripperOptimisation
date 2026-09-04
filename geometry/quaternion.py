"""Quaternion math and rotation utilities for frame transformations.

Handles quaternion operations and frame rotations between CadQuery Z-up coordinate
system and SOFA simulation frame conventions.
"""

import math

import cadquery as cq


def _axis_angle_to_quat(
    axis: tuple[float, float, float], angle_deg: float
) -> tuple[float, float, float, float]:
    """Build a normalized quaternion (x, y, z, w) from an axis-angle rotation."""
    ax, ay, az = axis
    norm = math.sqrt((ax * ax) + (ay * ay) + (az * az))
    if norm <= 0.0:
        return (0.0, 0.0, 0.0, 1.0)

    ax /= norm
    ay /= norm
    az /= norm

    half = math.radians(angle_deg) / 2.0
    s = math.sin(half)
    c = math.cos(half)
    return (ax * s, ay * s, az * s, c)


def _quat_mul(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """Hamilton product of quaternions in (x, y, z, w) format."""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        (aw * bx) + (ax * bw) + (ay * bz) - (az * by),
        (aw * by) - (ax * bz) + (ay * bw) + (az * bx),
        (aw * bz) + (ax * by) - (ay * bx) + (az * bw),
        (aw * bw) - (ax * bx) - (ay * by) - (az * bz),
    )


def _normalize_quat(
    q: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """Normalize quaternion to unit length."""
    x, y, z, w = q
    norm = math.sqrt((x * x) + (y * y) + (z * z) + (w * w))
    if norm <= 0.0:
        return (0.0, 0.0, 0.0, 1.0)
    return (x / norm, y / norm, z / norm, w / norm)


def _quat_conjugate(
    q: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """Return the quaternion conjugate."""
    x, y, z, w = q
    return (-x, -y, -z, w)


def _quat_rotate_vector(
    q: tuple[float, float, float, float],
    v: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Rotate a 3D vector by a unit quaternion."""
    vx, vy, vz = v
    v_quat = (vx, vy, vz, 0.0)
    rotated = _quat_mul(_quat_mul(q, v_quat), _quat_conjugate(q))
    return (rotated[0], rotated[1], rotated[2])


def _export_frame_quat() -> tuple[float, float, float, float]:
    """Return the mesh export frame rotation from CadQuery Z-up to SOFA frame."""
    qx = _axis_angle_to_quat((1.0, 0.0, 0.0), -90.0)
    qy = _axis_angle_to_quat((0.0, 1.0, 0.0), 90.0)
    return _normalize_quat(_quat_mul(qy, qx))


def rotate_model_to_export_frame(model: cq.Workplane) -> cq.Workplane:
    """Rotate model from CadQuery Z-up into the mesh export frame."""
    return model.rotate((0, 0, 0), (1, 0, 0), -90).rotate((0, 0, 0), (0, 1, 0), 90)
