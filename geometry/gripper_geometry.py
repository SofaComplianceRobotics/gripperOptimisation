"""
Gripper geometry helpers.

Provides lower-level geometry builders for ring and leg-attachment geometry
used when assembling the full gripper model.
"""

import math

import cadquery as cq
from cadquery import Vector, Wire

from .geometry_helpers import annular_sector
from .params import ModelParams, PROFILE_EXTRUDE_MARGIN


def _make_variable_height_ring(
    ro: float,
    ri: float,
    height_func,
    n_samples: int = 16,
) -> cq.Workplane:
    """Create an annular ring with smooth height variation.

    This constructs the ring by creating multiple small sector lofts which
    avoids full-ring loft seam issues.

    Args:
        ro (float): Outer radius.
        ri (float): Inner radius.
        height_func (Callable[[float], float]): Function mapping angle (degrees)
            to a height value.
        n_samples (int): Number of angular sectors to create.

    Returns:
        cq.Workplane: The constructed ring solid.
    """
    result = None
    for i in range(n_samples):
        angle_start = i * 360.0 / n_samples
        angle_end = angle_start + 360.0 / n_samples

        wires = []
        for angle_deg in (angle_start, angle_end):
            angle_rad = math.radians(angle_deg)
            h = height_func(angle_deg % 360.0)
            ca, sa = math.cos(angle_rad), math.sin(angle_rad)
            pts = [
                Vector(ri * ca, ri * sa, 0),
                Vector(ro * ca, ro * sa, 0),
                Vector(ro * ca, ro * sa, h),
                Vector(ri * ca, ri * sa, h),
                Vector(ri * ca, ri * sa, 0),
            ]
            wires.append(Wire.makePolygon(pts))

        sector = cq.Workplane().add(cq.Solid.makeLoft(wires, ruled=True))
        result = sector if result is None else result.union(sector)

    return result


def make_circle(p: ModelParams) -> cq.Workplane:
    """Build the main ring and four thickened sectors.

    Args:
        p (ModelParams): Model parameters.

    Returns:
        cq.Workplane: Ring solid with four thickened sectors.

    Raises:
        ValueError: If geometric constraints cannot be satisfied.
    """
    base_thickness = p.cylinder_hole_thickness
    thickened_thickness = p.leg_hole_width + (2.0 * p.leg_wall_thickness)

    base_ro = p.cylinder_radius + (base_thickness / 2.0)
    base_ri = p.cylinder_radius - (base_thickness / 2.0)

    result = _make_variable_height_ring(
        base_ro,
        max(base_ri, 0.0),
        p.cylinder_height_at,
        n_samples=p.ring_ramp_samples,
    )

    sector_mid_r = p.cylinder_radius
    sector_inner_r = sector_mid_r - (thickened_thickness / 2.0)
    target_center_distance = p.leg_hole_length + (2.0 * p.leg_wall_thickness)

    ratio = target_center_distance / (2.0 * sector_inner_r)
    ratio = max(-1.0, min(1.0, ratio))

    span = math.degrees(2.0 * math.asin(ratio))

    for center_deg in (0, 90, 180, 270):
        start_deg = center_deg - (span / 2.0)
        result = result.union(
            annular_sector(
                sector_mid_r,
                thickened_thickness,
                start_deg,
                span,
                p.cylinder_height_at(float(center_deg)),
            )
        )

    return result


def make_leg_attachment(p: ModelParams) -> cq.Workplane:
    """Build the leg attachment body with slit and trapezoid roof cut.

    Args:
        p (ModelParams): Model parameters.

    Returns:
        cq.Workplane: Leg attachment solid.
    """
    outer_length = p.leg_hole_length + (2.0 * p.leg_wall_thickness)
    outer_width = p.leg_hole_width + (2.0 * p.leg_wall_thickness)

    result = (
        cq.Workplane("XY")
        .rect(outer_length, outer_width)
        .rect(p.leg_hole_length, p.leg_hole_width)
        .extrude(p.leg_attachment_height)
    )

    result = (
        result.faces(">Y")
        .workplane()
        .center(0, p.leg_attachment_height / 2.0)
        .rect(p.slit_width, p.leg_attachment_height)
        .cutBlind(-p.leg_wall_thickness)
    )

    half_l = outer_length / 2.0
    min_start_z = max(0.0, p.leg_attachment_height - half_l)
    max_drop_from_top = p.leg_attachment_height - min_start_z
    drop_from_top = max(0.0, min(p.trapezoid_start_from_top, max_drop_from_top))
    start_z = p.leg_attachment_height - drop_from_top

    rise = p.leg_attachment_height - start_z
    top_half = half_l - rise

    trapezoid_profile = (
        cq.Workplane("XZ")
        .polyline(
            [
                (-half_l, 0),
                (half_l, 0),
                (half_l, start_z),
                (top_half, p.leg_attachment_height),
                (-top_half, p.leg_attachment_height),
                (-half_l, start_z),
            ]
        )
        .close()
        .extrude(outer_width + PROFILE_EXTRUDE_MARGIN, both=True)
    )

    return result.intersect(trapezoid_profile)
