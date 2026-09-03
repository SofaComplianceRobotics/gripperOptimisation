"""Parametric Emio leg — fixed motor wrap, tunable middle, straight tip.

Replicates the platform's own leg-generation recipe (see the lab_design lab's
freecadbeziercurvetomeshes.py and the stock blueleg): a planar centerline
that wraps the motor pulley, runs up with tunable curvature, and ends in a
straight vertical section that slides into the gripper's leg pocket. The
motor attachment clip (with its snap bumps) is the exact solid extracted from
the platform's leg-cad.FCStd (geometry/data/attachmotor.brep), fused onto
every generated leg.

Output contract, matching what parts.leg.Leg (the EmioLabs SOFA prefab)
expects in data/meshes/legs/:
    <name>.txt — Rigid3 frames (x, y, z, qx, qy, qz, qw) along the leg,
                 one row per beam node, used directly by the beam/cosserat
                 FEM model. Same frame convention as the stock blueleg.txt.
    <name>.stl — surface mesh for the visual model and 3D printing.

Curve coordinates here are (u, v) = (outward, up), mapping to the leg frame
as z = u, y = v, x = 0 (the leg is planar; width extends across x).
"""

from __future__ import annotations

from math import cos, pi, radians, sin
from pathlib import Path

import numpy as np
from beziers.cubicbezier import CubicBezier
from beziers.path import BezierPath
from beziers.point import Point

from geometry.leg_params import LegParams

# Hardware constants measured off the stock blueleg (blueleg.txt / .stl):
# the wrap starts at the bottom of the motor pulley (v = -22.5) and the
# straight section runs at u = 22.0.
PULLEY_RADIUS = 22.5
STRAIGHT_OFFSET = 22.0

# attachmotor.brep's own straight snap-tab extends from v = 0 (the arc's end)
# up to v = 17.0 (its bounding box's own ymax) before the clip's material
# ends. The tunable span must not start bowing before that point, or the
# clip's fixed straight tab pokes out on its own — no longer covered by the
# (now-diverging) swept body — instead of the body picking up cleanly where
# the clip ends.
CLIP_STRAIGHT_RUN = 17.0

# The stock blueleg.stl's cross-section is not centered on the beam
# centerline above (u = 22.0) — it's shifted 0.5mm further from the motor
# pulley (u = 22.5), matching attachmotor.brep's own snap-tab geometry, which
# is centered the same way. Applied to the visual mesh only; the physics
# centerline (get_beams/export_positions) stays exactly on the beam axis, as
# parts.leg.Leg expects.
SECTION_OUTWARD_OFFSET = 0.5

# Cubic-Bezier quarter-arc constant.
_KAPPA = 0.5522847498

# Motor attachment clip (wrap + snap bumps), extracted once from the
# platform's leg-cad.FCStd, already positioned in the leg frame.
ATTACHMOTOR_BREP = Path(__file__).resolve().parent / "data" / "attachmotor.brep"


def _quat_axis_angle(axis: int, angle: float) -> tuple[float, float, float, float]:
    """Unit quaternion (x, y, z, w) for a rotation of `angle` rad about the
    axis 0=x, 1=y, 2=z."""
    s = sin(angle / 2.0)
    xyz = [0.0, 0.0, 0.0]
    xyz[axis] = s
    return (xyz[0], xyz[1], xyz[2], cos(angle / 2.0))


def _quat_mul(a, b):
    """Hamilton product a * b of two (x, y, z, w) quaternions."""
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def _properly_cross(a, b, c, d) -> bool:
    """True if open segments ab and cd cross at an interior point."""

    def cross(o, p, q):
        return (p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0])

    d1, d2 = cross(c, d, a), cross(c, d, b)
    d3, d4 = cross(a, b, c), cross(a, b, d)
    return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))


def _polyline_self_intersects(pts: list[tuple[float, float]]) -> bool:
    """Standard O(n^2) crossing test over a polyline, skipping adjacent segments."""
    n = len(pts) - 1
    for i in range(n):
        for j in range(i + 2, n):
            if _properly_cross(pts[i], pts[i + 1], pts[j], pts[j + 1]):
                return True
    return False


class LegCenterline:
    """A leg's planar centerline as a piecewise cubic-Bezier path.

    Feasibility and frame sampling are implemented on dense polyline
    samples rather than the beziers library's analytic routines: those
    degenerate on exactly-straight segments, and the straight leg is this
    model's default shape.
    """

    def __init__(self, path: BezierPath, width: float, thickness: float, num_beams: int):
        self.path = path
        self.width = width
        self.thickness = thickness
        self.num_beams = num_beams

    def _sample(self, per_segment: int = 50) -> tuple[list, list]:
        """Dense (points, unit tangents) along the path, in (u, v) tuples."""
        pts: list[tuple[float, float]] = []
        tans: list[tuple[float, float]] = []
        for seg in self.path.asSegments():
            for i in range(per_segment):
                if pts and i == 0:
                    continue  # junction point equals the previous segment's end
                t = i / (per_segment - 1)
                pt = seg.pointAtTime(t)
                tv = seg.tangentAtTime(t)
                norm = (tv.x**2 + tv.y**2) ** 0.5
                pts.append((pt.x, pt.y))
                tans.append((tv.x / norm, tv.y / norm))
        return pts, tans

    def is_valid(self) -> bool:
        """Reject centerlines that fold back or self-intersect, directly or
        once the cross-section is swept along either edge."""
        pts, tans = self._sample()

        # A fold-back reverses direction between consecutive samples.
        for (tx1, ty1), (tx2, ty2) in zip(tans, tans[1:]):
            if tx1 * tx2 + ty1 * ty2 < 0:
                return False

        if _polyline_self_intersects(pts):
            return False

        # Sweep edges: offset by half the in-plane cross-section dimension.
        # Curvature tighter than thickness/2 makes an edge loop over itself.
        half = self.thickness / 2.0
        for sign in (1, -1):
            edge = [
                (px - ty * half * sign, py + tx * half * sign)
                for (px, py), (tx, ty) in zip(pts, tans)
            ]
            if _polyline_self_intersects(edge):
                return False
        return True

    def get_beams(self, number_of_beams: int) -> list[list[float]]:
        """Sample the path into evenly-spaced (by arclength) Rigid3 frames.

        Same tangent-to-quaternion construction as the platform's
        discretizeAndSaveRigidFrames (lab_design), so the frames are
        interchangeable with the stock blueleg.txt.

        Returns:
            One [x, y, z, qx, qy, qz, qw] row per beam node, x always 0.
        """
        curves = self.path.asSegments()
        lengths = [c.lengthAtTime(1) for c in curves]
        total = sum(lengths)

        beams: list[list[float]] = []
        for i in range(number_of_beams):
            s = total * i / (number_of_beams - 1)
            ci = 0
            while ci < len(curves) - 1 and s > lengths[ci]:
                s -= lengths[ci]
                ci += 1
            curve = curves[ci]

            if s <= 0.0:
                t = 0.0
            elif s >= lengths[ci]:
                t = 1.0
            else:
                lo, hi = 0.0, 1.0
                for _ in range(32):
                    mid = (lo + hi) / 2.0
                    if curve.lengthAtTime(mid) < s:
                        lo = mid
                    else:
                        hi = mid
                t = (lo + hi) / 2.0

            point = curve.pointAtTime(t)
            theta = curve.tangentAtTime(t).angle - pi / 2
            # Rz(pi/2) * Ry(theta) * Rx(pi), scalar-last (x, y, z, w).
            quaternion = _quat_mul(
                _quat_axis_angle(2, pi / 2),
                _quat_mul(_quat_axis_angle(1, theta), _quat_axis_angle(0, pi)),
            )
            beams.append([0.0, point.y, point.x, *quaternion])

        return beams

    def export_positions(self, txt_path) -> None:
        """Write the beam-node Rigid3 frames to `<name>.txt` (parts.leg.Leg format)."""
        np.savetxt(str(txt_path), self.get_beams(self.num_beams))

    def export_stl(self, stl_path) -> bool:
        """Loft the cross-section along the centerline, fuse the motor clip,
        and export the surface mesh. Requires the CAD runtime (cadquery/OCP).

        The surface is meshed with gmsh at a uniform element size rather than
        OCC's tessellator: the visual model follows the bending beam through
        SkinningMapping, which moves mesh vertices — flat faces tessellated
        into corner-only triangles would draw as straight lines no matter how
        the physics bends. The stock blueleg.stl is meshed the same way.

        The body is built as a ruled loft through many densely-sampled,
        explicitly-oriented rectangular stations rather than a single
        OCC BRepOffsetAPI_MakePipeShell sweep: that sweep derives the
        profile's rotation from the path's curvature (Frenet framing), which
        is undefined on the straight or near-straight sections this leg model
        allows — including the default stock-straight shape — and either
        raises BRepOffsetAPI_MakePipeShell::MakeSolid or (with an auxiliary
        spine papering over that) silently warps the cross-section along the
        path. Placing each station's rectangle ourselves, from the same
        tangent samples used for is_valid()/get_beams(), sidesteps OCC's
        framing entirely and keeps the cross-section exactly self.width x
        self.thickness everywhere.
        """
        import cadquery as cq
        from cadquery.occ_impl.geom import Vector
        from OCP.BRep import BRep_Builder
        from OCP.BRepTools import BRepTools
        from OCP.TopoDS import TopoDS_Shape

        pts, tans = self._sample()
        half_w, half_t = self.width / 2.0, self.thickness / 2.0
        wires = []
        for (u, v), (tu, tv) in zip(pts, tans):
            center_line_pt = Vector(0, v, u)
            # In-plane unit normal, rotated so positive is outward (away from
            # the motor pulley); stays continuous in sign since the
            # centerline never folds back (checked by is_valid()).
            outward = Vector(0, -tu, tv)
            center = center_line_pt + outward * SECTION_OUTWARD_OFFSET
            width_vec = Vector(half_w, 0, 0)
            thickness_vec = outward * half_t
            corners = [
                center + width_vec + thickness_vec,
                center + width_vec - thickness_vec,
                center - width_vec - thickness_vec,
                center - width_vec + thickness_vec,
            ]
            wires.append(cq.Wire.makePolygon(corners, close=True))

        body = cq.Solid.makeLoft(wires, ruled=True)
        if body.isNull() or not body.isValid():
            return False

        clip_raw = TopoDS_Shape()
        BRepTools.Read_s(clip_raw, str(ATTACHMOTOR_BREP), BRep_Builder())
        fused = body.fuse(cq.Shape(clip_raw))
        try:
            fused = fused.clean()
        except Exception:
            pass  # cosmetic seam removal only; the unclean union is still correct

        return _mesh_solid_to_stl(fused, stl_path)


def _mesh_solid_to_stl(solid, stl_path, size_max: float = 5.0, size_min: float = 2.0) -> bool:
    """Mesh a CadQuery solid's surface with gmsh at a uniform element size and
    write a binary STL. Element size ~5mm matches the stock blueleg.stl, dense
    enough for SkinningMapping to draw the beam's curvature."""
    import os
    import tempfile

    import gmsh
    from OCP.BRepTools import BRepTools

    fd, tmp_name = tempfile.mkstemp(suffix=".brep")
    os.close(fd)
    initialized = False
    try:
        BRepTools.Write_s(solid.wrapped, tmp_name)

        gmsh.initialize()
        initialized = True
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.occ.importShapes(tmp_name)
        gmsh.model.occ.synchronize()

        gmsh.option.setNumber("Mesh.CharacteristicLengthMax", size_max)
        gmsh.option.setNumber("Mesh.CharacteristicLengthMin", size_min)
        # Frontal-Delaunay — the algorithm the gripper pipeline already uses;
        # algorithm 9 heap-crashes this gmsh build on swept geometry.
        gmsh.option.setNumber("Mesh.Algorithm", 6)
        gmsh.option.setNumber("Mesh.Binary", 1)
        gmsh.model.mesh.generate(2)
        gmsh.write(str(stl_path))
        return True
    except Exception as e:
        print(f"[leg] gmsh surface meshing failed: {e}")
        return False
    finally:
        if initialized:
            gmsh.finalize()
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _line_as_cubic(a: Point, b: Point) -> CubicBezier:
    """A straight segment as a degenerate cubic, so the whole path stays one
    BezierPath for sampling and validity checks."""
    return CubicBezier(
        a,
        Point(a.x + (b.x - a.x) / 3.0, a.y + (b.y - a.y) / 3.0),
        Point(a.x + 2.0 * (b.x - a.x) / 3.0, a.y + 2.0 * (b.y - a.y) / 3.0),
        b,
    )


def _polar(origin: Point, dist: float, angle_deg: float) -> Point:
    """A point offset from origin by dist at angle_deg (0 = +u, 90 = +v)."""
    rad = radians(angle_deg)
    return Point(origin.x + dist * cos(rad), origin.y + dist * sin(rad))


def build_leg(p: LegParams) -> LegCenterline:
    """Build the leg centerline from tunable LegParams.

    Fixed base: quarter wrap from the bottom of the motor pulley (0, -22.5)
    to the stock straight line (22.0, 0), tangents horizontal->vertical, then
    a further fixed straight run of CLIP_STRAIGHT_RUN: the tunable span must
    not start bowing while it's still inside the motor clip's own footprint,
    or the clip's fixed straight tab pokes out uncovered.

    Tunable span: a single Bezier segment from the start point a (fixed
    position, end of the clip-straight run) to the free end point p1, polar
    from a. The start point's outgoing handle is fixed at 90 (vertical) so
    the join with the fixed base stays G1-continuous; only its length is
    tunable. The end point's incoming handle sits along the same chord angle
    as p1 itself (leg_p1_angle_deg), so the span arrives at p1 already
    heading in that direction rather than snapping back to vertical. With
    every point/handle at its neutral angle (90) the whole spline is exactly
    straight, reproducing the stock leg.

    Fixed tip: straight run of tip_straight_len continuing from p1 in that
    same direction (leg_p1_angle_deg) — an extension of wherever the span was
    actually heading, not forced back to vertical (whatever position p1
    lands at — the end point is not pinned to the stock lateral offset).
    """
    u0 = STRAIGHT_OFFSET
    arc = CubicBezier(
        Point(0.0, -PULLEY_RADIUS),
        Point(_KAPPA * u0, -PULLEY_RADIUS),
        Point(u0, -_KAPPA * PULLEY_RADIUS),
        Point(u0, 0.0),
    )
    clip_run_end = Point(u0, CLIP_STRAIGHT_RUN)
    clip_run = _line_as_cubic(Point(u0, 0.0), clip_run_end)

    a = clip_run_end
    p1 = _polar(a, p.leg_p1_dist, p.leg_p1_angle_deg)
    tip_end = _polar(p1, p.tip_straight_len, p.leg_p1_angle_deg)

    a_hout = _polar(a, p.leg_p0_hout_dist, 90.0)
    p1_hin = _polar(p1, p.leg_p1_hin_dist, p.leg_p1_angle_deg - 180.0)

    span = CubicBezier(a, a_hout, p1_hin, p1)
    tip = _line_as_cubic(p1, tip_end)

    path = BezierPath.fromSegments([arc, clip_run, span, tip])
    path.closed = False

    return LegCenterline(
        path=path, width=p.width, thickness=p.thickness, num_beams=p.num_beams
    )
