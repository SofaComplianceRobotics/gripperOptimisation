"""
Assembly - Combine gripper components (ring, legs, pincers) into a complete model.

Orchestrates the assembly of individual gripper parts into a fully-formed
gripping device ready for simulation or export.
"""

import math

import cadquery as cq

from geometry.geometry_helpers import make_vertical_drop_from_low_face
from geometry.params import ModelParams
from geometry.gripper_parts import make_circle, make_leg_attachment, make_pincer_pair_world


def _rotate_vector_axis_angle(
    v: tuple[float, float, float],
    axis: tuple[float, float, float],
    angle_deg: float,
) -> tuple[float, float, float]:
    """Rotate vector v around axis by angle_deg using Rodrigues' formula.

    Args:
        v: Vector to rotate.
        axis: Rotation axis (need not be normalised).
        angle_deg: Rotation angle in degrees.

    Returns:
        Rotated vector.
    """
    vx, vy, vz = v
    ax, ay, az = axis
    an = math.sqrt((ax * ax) + (ay * ay) + (az * az))
    if an <= 0.0:
        return v

    ax /= an
    ay /= an
    az /= an

    t = math.radians(angle_deg)
    ct = math.cos(t)
    st = math.sin(t)

    dot = (vx * ax) + (vy * ay) + (vz * az)
    cx = (ay * vz) - (az * vy)
    cy = (az * vx) - (ax * vz)
    cz = (ax * vy) - (ay * vx)

    rx = (vx * ct) + (cx * st) + (ax * dot * (1.0 - ct))
    ry = (vy * ct) + (cy * st) + (ay * dot * (1.0 - ct))
    rz = (vz * ct) + (cz * st) + (az * dot * (1.0 - ct))
    return (rx, ry, rz)


def assemble_model(p: ModelParams) -> cq.Workplane:
    """Assemble ring, four leg attachments, and two opposite underside pincers.

    Args:
        p: Model parameters.

    Returns:
        Final combined solid.
    """
    base = make_circle(p)
    leg = make_leg_attachment(p)
    leg_placement_radius = p.cylinder_radius - p.leg_attachement_inward_offset

    leg_and_drop_solids: list[cq.Workplane] = []
    for angle_deg in (0, 90, 180, 270):
        a = math.radians(angle_deg)
        x = leg_placement_radius * math.cos(a)
        y = leg_placement_radius * math.sin(a)
        ring_h = p.cylinder_height_at(float(angle_deg))

        leg_base = leg.rotate((0, 0, 0), (0, 0, 1), angle_deg + 90).translate(
            (x, y, ring_h + p.leg_attachement_lift)
        )

        axis_start = (x, y, ring_h + p.leg_attachement_lift)
        axis_end = (
            x - math.sin(a),
            y + math.cos(a),
            ring_h + p.leg_attachement_lift,
        )
        tilt_axis = (axis_end[0] - axis_start[0], axis_end[1] - axis_start[1], 0.0)
        expected_bottom_normal = _rotate_vector_axis_angle(
            (0.0, 0.0, -1.0), tilt_axis, p.leg_attachement_tilt_angle
        )

        leg_i = leg_base.rotate(axis_start, axis_end, p.leg_attachement_tilt_angle)
        drop_i = make_vertical_drop_from_low_face(
            leg_i,
            target_z=ring_h,
            overlap=p.leg_attachement_drop_overlap,
            expected_normal=expected_bottom_normal,
            min_final_z=0.0,
        )

        leg_combo = leg_i
        if drop_i.solids().size() > 0:
            leg_combo = leg_combo.union(drop_i)

        leg_and_drop_solids.append(leg_combo)

    result = base
    for solid in leg_and_drop_solids:
        result = result.union(solid)
    result = result.union(make_pincer_pair_world(p))

    return result
