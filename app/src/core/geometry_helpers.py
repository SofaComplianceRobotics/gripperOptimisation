"""
Geometry Helpers - Utility functions for gripper geometry construction.

Provides low-level geometric primitives and transformations used throughout
the gripper design and assembly pipeline.
"""

import logging
import math
import sys
from pathlib import Path

import cadquery as cq

SRC_ROOT = Path(__file__).resolve().parents[1]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from core.params import EPS_LEN, EPS_NORMAL

logger = logging.getLogger(__name__)


def annular_sector(
    mid_r: float,
    thickness: float,
    start_deg: float,
    sweep_deg: float,
    height: float,
) -> cq.Workplane:
    """
    Create an annular sector (ring slice) extruded along +Z.

    Inputs:
        mid_r (float): Mid-radius of the annulus.
        thickness (float): Radial thickness of the annulus.
        start_deg (float): Start angle in degrees.
        sweep_deg (float): Sweep angle in degrees.
        height (float): Extrusion height.

    Returns:
        cadquery.Workplane: Annular sector solid.

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
    """
    Create a vertical (-Z) drop solid from a downward-facing planar face.

    Inputs:
        solid_wp (cadquery.Workplane): Solid to analyze.
        target_z (float): Z level to reach.
        overlap (float): Extra penetration below target_z.
        expected_normal (tuple[float, float, float]): Expected world-space
            normal of the source bottom face.
        min_final_z (float | None): Optional clamp plane for the final drop.
            If provided, the extruded drop will not extend below this global Z.

    Returns:
        cadquery.Workplane: Vertical drop solid.

    Raises:
        RuntimeError: If the source solid does not expose a planar face aligned
            with the expected normal, or if extrusion fails unexpectedly.
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
