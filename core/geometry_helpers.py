"""
Geometry Helpers - Utility functions for gripper geometry construction.

Provides low-level geometric primitives and transformations used throughout
the gripper design and assembly pipeline.
"""

import math

import cadquery as cq

from core.params import EPS_LEN, EPS_NORMAL


def annular_sector(
    mid_r: float,
    thickness: float,
    start_deg: float,
    sweep_deg: float,
    height: float,
) -> cq.Workplane:
    """Create an annular sector (ring slice) extruded along +Z.

    Args:
        mid_r: Mid-radius of the annulus.
        thickness: Radial thickness of the annulus.
        start_deg: Start angle in degrees.
        sweep_deg: Sweep angle in degrees.
        height: Extrusion height.

    Returns:
        Annular sector solid.

    Raises:
        ValueError: If dimensions are invalid.
    """
    if thickness <= 0 or height <= 0:
        raise ValueError("thickness and height must be > 0.")

    ro = mid_r + (thickness / 2.0)
    ri = mid_r - (thickness / 2.0)
    if ro <= 0:
        raise ValueError("Outer radius must be > 0.")

    outer = cq.Solid.makeCylinder(
        ro, height, cq.Vector(0, 0, 0), cq.Vector(0, 0, 1), sweep_deg
    )
    sector = (
        cq.Workplane("XY").newObject([outer]).rotate((0, 0, 0), (0, 0, 1), start_deg)
    )

    if ri > 0:
        inner = cq.Solid.makeCylinder(
            ri, height, cq.Vector(0, 0, 0), cq.Vector(0, 0, 1), sweep_deg
        )
        inner_wp = (
            cq.Workplane("XY")
            .newObject([inner])
            .rotate((0, 0, 0), (0, 0, 1), start_deg)
        )
        sector = sector.cut(inner_wp)

    return sector


def make_vertical_drop_from_low_face(
    solid_wp: cq.Workplane,
    target_z: float,
    overlap: float,
    expected_normal: tuple[float, float, float],
    min_final_z: float | None = None,
) -> cq.Workplane:
    """Create a vertical (-Z) drop solid from a downward-facing planar face.

    Args:
        solid_wp: Solid to analyze.
        target_z: Z level to reach.
        overlap: Extra penetration below target_z.
        expected_normal: Expected world-space normal of the source bottom face.
        min_final_z: Optional clamp plane; the extruded drop will not extend
            below this global Z.

    Returns:
        Vertical drop solid.

    Raises:
        RuntimeError: If the source solid has no planar face aligned with
            the expected normal, or if extrusion fails unexpectedly.
    """
    shape = solid_wp.val()
    faces = shape.Faces()
    if not faces:
        raise RuntimeError("Source solid has no faces for drop extrusion.")

    planar = [f for f in faces if f.geomType() == "PLANE"]
    if not planar:
        raise RuntimeError("Source solid has no planar face for drop extrusion.")

    ex, ey, ez = expected_normal
    en = math.sqrt((ex * ex) + (ey * ey) + (ez * ez))
    if en <= EPS_NORMAL:
        raise RuntimeError("Expected normal for drop extrusion is degenerate.")

    ex /= en
    ey /= en
    ez /= en

    face = max(
        planar,
        key=lambda f: (
            (f.normalAt().x * ex) + (f.normalAt().y * ey) + (f.normalAt().z * ez),
            f.Area(),
        ),
    )
    alignment = (
        (face.normalAt().x * ex) + (face.normalAt().y * ey) + (face.normalAt().z * ez)
    )
    if alignment < 1.0 - 1e-5:
        raise RuntimeError(
            "Could not find a planar face aligned with the expected bottom normal. "
            f"Best alignment was {alignment:.6f}."
        )

    bbox = face.BoundingBox()
    zmax = bbox.zmax
    zmin = bbox.zmin

    base_drop_len = max(0.0, zmax - (target_z - overlap))
    if min_final_z is None:
        drop_len = base_drop_len
    else:
        # Keep the original target-driven drop, but cap it so the translated
        # face never goes below the clamp plane.
        max_drop_len = max(0.0, zmin - min_final_z)
        drop_len = min(base_drop_len, max_drop_len)

    if drop_len <= EPS_LEN:
        return cq.Workplane("XY")

    try:
        drop = cq.Solid.extrudeLinear(
            face.outerWire(),
            face.innerWires(),
            cq.Vector(0, 0, -drop_len),
        )
    except ValueError as exc:
        raise RuntimeError(
            "Failed to extrude vertical drop from selected face."
        ) from exc

    return cq.Workplane("XY").newObject([drop])
