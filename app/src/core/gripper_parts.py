"""
Gripper Parts - Build individual gripper geometry components (ring, legs, pincers).

Provides functions to construct each modular part of the gripper that are
assembled into the final gripper model.
"""

import math
import sys
from pathlib import Path

import cadquery as cq
from cadquery import Edge, Face, Vector, Wire

SRC_ROOT = Path(__file__).resolve().parents[1]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from core.geometry_helpers import annular_sector
from core.params import (
    ModelParams,
    PincerSplinePoint,
    PROFILE_EXTRUDE_MARGIN,
)


def _make_variable_height_ring(
    ro: float,
    ri: float,
    height_func,
    n_samples: int = 16,
) -> cq.Workplane:
    """Create annular ring with smooth height variation using sector-by-sector ruled lofts.

    Each sector is a ruled loft between two radial cross-section rectangles, giving
    smooth height interpolation between adjacent slice angles. Sector-by-sector avoids
    the closed-loop seam issue that OCC's topology upgrader rejects on a full-ring loft.
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
        p: Model parameters.

    Returns:
        Ring solid with 4 thickened sectors.

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
        p: Model parameters.

    Returns:
        Leg attachment solid.
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


def make_pincer_local(p: ModelParams, trailing_fraction: float = 1.0) -> cq.Workplane:
    """Build one pincer in local coordinates.

    Local axes: +X radial, +Y downward, +Z tangential (after placement).

    Args:
        p: Model parameters.
        trailing_fraction: Keep only this trailing fraction of the sampled
            spline centerline before profile extrusion. 1.0 keeps the full pincer.

    Returns:
        One local pincer solid.
    """
    s = p.pincer_path_scale
    scaled_points = tuple(
        PincerSplinePoint(
            p=(pt.p[0] * s, pt.p[1] * s),
            h_in=(None if pt.h_in is None else (pt.h_in[0] * s, pt.h_in[1] * s)),
            h_out=(None if pt.h_out is None else (pt.h_out[0] * s, pt.h_out[1] * s)),
        )
        for pt in p.pincer_points
    )

    def _bezier_to_spline_points(scaled_points, n=4):
        """Approximate cubic bezier with n+1 points for makeSpline."""
        p0 = scaled_points[0].p
        h0 = scaled_points[0].h_out  # absolute
        h1 = scaled_points[1].h_in  # absolute
        p1 = scaled_points[1].p

        pts = []
        for i in range(n + 1):
            t = i / n
            mt = 1 - t
            x = (
                mt**3 * p0[0]
                + 3 * mt**2 * t * h0[0]
                + 3 * mt * t**2 * h1[0]
                + t**3 * p1[0]
            )
            y = (
                mt**3 * p0[1]
                + 3 * mt**2 * t * h0[1]
                + 3 * mt * t**2 * h1[1]
                + t**3 * p1[1]
            )
            pts.append(Vector(x, y, 0))
        return pts

    vectors = _bezier_to_spline_points(
        scaled_points, n=max(4, p.pincer_profile_samples)
    )

    if trailing_fraction < 1.0:
        keep_points = max(2, math.ceil(len(vectors) * trailing_fraction))
        vectors = vectors[-keep_points:]

    def _normalize_xy(x: float, y: float) -> tuple[float, float]:
        length = math.hypot(x, y)
        if length <= 1e-12:
            return (1.0, 0.0)
        return (x / length, y / length)

    def _build_cap_arc_points(
        center: Vector,
        start_pt: tuple[float, float],
        preferred_dir: tuple[float, float],
        segments: int,
    ) -> list[tuple[float, float]]:
        """Build interior points for a semicircular end cap."""
        dx = start_pt[0] - center.x
        dy = start_pt[1] - center.y
        radius = math.hypot(dx, dy)
        if radius <= 1e-12:
            return []

        start_angle = math.atan2(dy, dx)
        pref_x, pref_y = _normalize_xy(preferred_dir[0], preferred_dir[1])
        ccw_mid = (
            math.cos(start_angle + (math.pi / 2.0)),
            math.sin(start_angle + (math.pi / 2.0)),
        )
        cw_mid = (
            math.cos(start_angle - (math.pi / 2.0)),
            math.sin(start_angle - (math.pi / 2.0)),
        )
        sweep = (
            1.0
            if ((ccw_mid[0] * pref_x) + (ccw_mid[1] * pref_y))
            >= ((cw_mid[0] * pref_x) + (cw_mid[1] * pref_y))
            else -1.0
        )

        arc_pts: list[tuple[float, float]] = []
        for i in range(1, segments):
            angle = start_angle + (sweep * math.pi * i / segments)
            arc_pts.append(
                (
                    center.x + (radius * math.cos(angle)),
                    center.y + (radius * math.sin(angle)),
                )
            )
        return arc_pts

    def _build_profile_outline(
        center_pts: list[Vector], width: float, rounded_ends: bool
    ) -> list[tuple[float, float]]:
        """Build a closed 2D strip with flat or rounded end caps."""
        half_w = width / 2.0
        left_pts: list[tuple[float, float]] = []
        right_pts: list[tuple[float, float]] = []

        for i, pt in enumerate(center_pts):
            if i == 0:
                tx = center_pts[i + 1].x - pt.x
                ty = center_pts[i + 1].y - pt.y
            elif i == len(center_pts) - 1:
                tx = pt.x - center_pts[i - 1].x
                ty = pt.y - center_pts[i - 1].y
            else:
                tx = center_pts[i + 1].x - center_pts[i - 1].x
                ty = center_pts[i + 1].y - center_pts[i - 1].y

            tn = math.hypot(tx, ty)
            if tn <= 1e-12:
                if i > 0:
                    tx = pt.x - center_pts[i - 1].x
                    ty = pt.y - center_pts[i - 1].y
                elif len(center_pts) > 1:
                    tx = center_pts[i + 1].x - pt.x
                    ty = center_pts[i + 1].y - pt.y
                else:
                    tx, ty = 1.0, 0.0
                tn = max(math.hypot(tx, ty), 1e-12)

            tx /= tn
            ty /= tn

            # Left normal of tangent (tx, ty)
            nx = -ty
            ny = tx

            left_pts.append((pt.x + (nx * half_w), pt.y + (ny * half_w)))
            right_pts.append((pt.x - (nx * half_w), pt.y - (ny * half_w)))

        if not rounded_ends:
            return left_pts + list(reversed(right_pts))

        cap_segments = max(2, p.pincer_round_cap_segments)
        start_tangent = _normalize_xy(
            center_pts[1].x - center_pts[0].x,
            center_pts[1].y - center_pts[0].y,
        )
        end_tangent = _normalize_xy(
            center_pts[-1].x - center_pts[-2].x,
            center_pts[-1].y - center_pts[-2].y,
        )

        outline: list[tuple[float, float]] = []
        outline.extend(left_pts)
        outline.extend(
            _build_cap_arc_points(
                center_pts[-1],
                left_pts[-1],
                end_tangent,
                cap_segments,
            )
        )
        outline.extend(reversed(right_pts))
        outline.extend(
            _build_cap_arc_points(
                center_pts[0],
                right_pts[0],
                (-start_tangent[0], -start_tangent[1]),
                cap_segments,
            )
        )
        return outline

    spline = Edge.makeSpline(vectors)

    profile_pts = _build_profile_outline(
        vectors, p.pincer_profile_width, p.pincer_round_ends
    )

    return (
        cq.Workplane("XY")
        .polyline(profile_pts)
        .close()
        .extrude(p.pincer_profile_height / 2.0, both=True)
    )


def make_pincer_pair_world(
    p: ModelParams, trailing_fraction: float = 1.0
) -> cq.Workplane:
    """Build and place the two pincers in world space.

    Args:
        p: Model parameters.
        trailing_fraction: Keep only this trailing fraction of each pincer
            path before profile extrusion. 1.0 keeps the full pincer.

    Returns:
        Union of both pincers placed in world space.
    """
    pincer_placement_radius = p.cylinder_radius
    pincer = make_pincer_local(p, trailing_fraction=trailing_fraction).rotate(
        (0, 0, 0), (1, 0, 0), -90
    )

    result = None
    for angle_deg in (0.0, 180.0):
        a = math.radians(angle_deg)
        x = pincer_placement_radius * math.cos(a)
        y = pincer_placement_radius * math.sin(a)

        tilt_y_deg = p.pincer_tilt_y_deg if angle_deg == 0.0 else -p.pincer_tilt_y_deg

        pincer_i = pincer.rotate((0, 0, 0), (0, 0, 1), angle_deg)
        pincer_i = pincer_i.rotate((0, 0, 0), (0, 1, 0), tilt_y_deg)
        pincer_i = pincer_i.translate((x, y, 0))

        result = pincer_i if result is None else result.union(pincer_i)

    if result is not None:
        clip_height = (p.cylinder_height * 4.0) + 200.0
        clip_box = (
            cq.Workplane("XY")
            .box(
                (p.cylinder_radius * 4.0) + 20.0,
                (p.cylinder_radius * 4.0) + 20.0,
                clip_height,
            )
            .translate((0, 0, p.cylinder_height - (clip_height / 2.0)))
        )
        result = result.intersect(clip_box)

    return result


def make_pincer_pair_world_collision(p: ModelParams) -> cq.Workplane:
    """Build collision pincers using only the distal path fraction.

    Args:
        p: Model parameters.

    Returns:
        Union of both collision pincers in world space.
    """
    return make_pincer_pair_world(p, trailing_fraction=p.mesh_collision_tail_fraction)
