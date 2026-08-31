"""
Shared geometry for reach_zone: the sweep (scene.py) and the standalone
viewer (view_scene.py) both need the same sweep constants, mesh
construction, and result file so what the viewer shows always matches what
the sweep actually measured.

The sweep itself is a stack of horizontal grids from Y_MIN to Y_MAX. Each
grid probes every (x, z) point in the fixed square GRID_MIN..GRID_MAX once,
directly -- no searching for a boundary -- and keeps whatever position the
solver actually settled at for that target, whether or not it landed
exactly on it. Stacking several grids across the vertical range gives a 3D
point cloud, and the shape scored/shown is the actual 3D convex hull of
that cloud (build_zone_solid / _convex_hull_3d) -- not a per-grid or
per-column approximation, so no line between two points of the shape can
ever leave it.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

# Operating height sweeps expand outward from.
CENTER_Y = -150.0
# Fixed square footprint probed at every height: x and z each range over
# GRID_MIN..GRID_MAX in GRID_STEP steps (5 values at the defaults below:
# -40/-20/0/20/40, so 5*5 = 25 (x, z) targets per level). +-40 is the range
# gripper_tilt already validated as safe to command.
GRID_MIN = -40.0
GRID_MAX = 40.0
GRID_STEP = 20.0
# (grid points per level) * (levels in Y_MIN..Y_MAX by Y_STEP) * HOLD_FRAMES
# is the total number of SOFA animate() steps the sweep needs -- 25 * 3 * 10
# = 750 at the defaults. Under the optimizer, scenes run through runSofa's
# batch GUI, which has a hard, unconfigurable-from-here cap of 1000
# iterations per run (SOFA's own default -- sofaopt never overrides it) --
# exceed that and the process just exits mid-sweep without ever reaching
# write_score(), which reads as "stuck" in the dashboard (it isn't: it
# already exited, just scoreless). Keep the product safely under ~900 to
# leave room for the robot's initial assembly, which eats a few dozen
# iterations of the same budget.
#
# Frames held per probe, letting the inverse solver settle before measuring
# the result.
HOLD_FRAMES = 10
# The achieved position is the average TCP position over the last this-many
# frames of each hold, not just the final frame -- a single-frame read can
# land on a momentary twitch/overshoot rather than the settled position.
AVERAGE_LAST_N_FRAMES = 3
# Fixed vertical range swept, and the spacing between grids within it.
# -190/-110 (CENTER_Y +-40) is the range gripper_tilt already validated as
# safe to command. 3 levels (-190/-150/-110) at this spacing.
Y_MIN = -190.0
Y_MAX = -110.0
Y_STEP = 40.0


def result_file(lab_root: Path) -> Path:
    """Path to the saved zone-sweep result, shared between scene.py and view_scene.py."""
    return Path(lab_root) / "runtime" / "recordings" / "reach_zone" / "zone_result.json"


def _convex_hull_2d(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Andrew's monotone chain. Returns hull vertices in CCW order."""
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _convex_hull_3d(
    points: list[tuple[float, float, float]], eps: float = 1e-6
) -> tuple[list[list[float]], list[list[int]]]:
    """Full 3D convex hull: every point that's genuinely on the boundary keeps
    its exact position; every point strictly inside is dropped. Unlike a
    per-axis or per-ring convexity check, this guarantees the actual
    definition of convex -- the segment between any two points of the
    result never leaves it -- because a face is only kept when every other
    sample point tests on one single side of its plane.

    Brute-force over point triples (O(n^3) candidate planes, each an O(n)
    check): with the sweep's point counts (tens, not thousands) this is a
    trivial amount of work, and being this literal about the definition
    ("no point on both sides of this plane") is what makes it easy to trust.
    Coplanar points sharing one facet (e.g. a whole ring lying flat on the
    boundary) are merged and re-triangulated as a single flat fan via
    _convex_hull_2d, rather than left as overlapping candidate triangles.

    Returns (vertices, triangles) using only the hull-vertex points, with
    every triangle wound so its outward normal matches the facet's --
    consistent orientation across the whole mesh, which mesh_volume()'s
    divergence-theorem sum depends on.
    """
    n = len(points)
    facets: dict[tuple[float, float, float, float], set[int]] = {}
    for i in range(n):
        for j in range(i + 1, n):
            for k in range(j + 1, n):
                a, b, c = points[i], points[j], points[k]
                ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
                vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
                nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
                nlen = math.sqrt(nx * nx + ny * ny + nz * nz)
                if nlen < eps:
                    continue  # collinear triple, no plane
                nx, ny, nz = nx / nlen, ny / nlen, nz / nlen
                pos = neg = False
                coplanar = []
                for m, p in enumerate(points):
                    d = nx * (p[0] - a[0]) + ny * (p[1] - a[1]) + nz * (p[2] - a[2])
                    if d > eps:
                        pos = True
                    elif d < -eps:
                        neg = True
                    else:
                        coplanar.append(m)
                if pos and neg:
                    continue  # points on both sides -- not a hull face
                if not pos and not neg:
                    continue  # every point exactly coplanar -- degenerate
                if pos:
                    nx, ny, nz = -nx, -ny, -nz  # flip so the normal faces away from the interior
                offset = nx * a[0] + ny * a[1] + nz * a[2]
                key = (round(nx, 6), round(ny, 6), round(nz, 6), round(offset, 3))
                facets.setdefault(key, set()).update(coplanar)

    vertices: list[list[float]] = []
    triangles: list[list[int]] = []
    vertex_map: dict[int, int] = {}

    def _vidx(orig_i: int) -> int:
        if orig_i not in vertex_map:
            vertex_map[orig_i] = len(vertices)
            vertices.append(list(points[orig_i]))
        return vertex_map[orig_i]

    for (nx, ny, nz, _offset), idx_set in facets.items():
        idxs = list(idx_set)
        if len(idxs) < 3:
            continue
        a = points[idxs[0]]
        # An orthonormal (u, v) basis spanning the facet's plane, to
        # triangulate it in 2D via the existing hull code.
        helper = (1.0, 0.0, 0.0) if abs(nx) < 0.9 else (0.0, 1.0, 0.0)
        ux, uy, uz = helper[1] * nz - helper[2] * ny, helper[2] * nx - helper[0] * nz, helper[0] * ny - helper[1] * nx
        ulen = math.sqrt(ux * ux + uy * uy + uz * uz)
        ux, uy, uz = ux / ulen, uy / ulen, uz / ulen
        vx, vy, vz = ny * uz - nz * uy, nz * ux - nx * uz, nx * uy - ny * ux
        local_to_idx: dict[tuple[float, float], int] = {}
        for m in idxs:
            px, py, pz = points[m]
            dxp, dyp, dzp = px - a[0], py - a[1], pz - a[2]
            local_to_idx[(dxp * ux + dyp * uy + dzp * uz, dxp * vx + dyp * vy + dzp * vz)] = m
        ordered = [local_to_idx[p] for p in _convex_hull_2d(list(local_to_idx))]
        if len(ordered) < 3:
            continue
        h0 = ordered[0]
        for t in range(1, len(ordered) - 1):
            triangles.append([_vidx(h0), _vidx(ordered[t]), _vidx(ordered[t + 1])])

    return vertices, triangles


def build_zone_solid(
    levels: list[tuple[float, list[tuple[float, float, float]]]],
) -> tuple[list[list[float]], list[list[int]]]:
    """The 3D convex hull of every point the sweep measured.

    Args:
        levels: (y, points) pairs from the sweep; only the points
            themselves matter here; the per-level grouping isn't used,
            since the hull is computed over the point cloud as a whole.

    Returns:
        (vertices, triangles) for a single watertight, convex mesh -- see
        _convex_hull_3d.
    """
    points = [p for _y, level_points in levels for p in level_points]
    return _convex_hull_3d(points)


def mesh_volume(vertices: list[list[float]], triangles: list[list[int]]) -> float:
    """Volume (mm^3) enclosed by a closed, consistently-wound triangle mesh.

    Standard signed-tetrahedron-from-origin sum (divergence theorem); exact
    for any watertight mesh regardless of convexity.
    """
    total = 0.0
    for tri in triangles:
        v0, v1, v2 = (vertices[i] for i in tri)
        total += (
            v0[0] * (v1[1] * v2[2] - v1[2] * v2[1])
            - v0[1] * (v1[0] * v2[2] - v1[2] * v2[0])
            + v0[2] * (v1[0] * v2[1] - v1[1] * v2[0])
        )
    return abs(total) / 6.0


def add_mesh_visual(rootnode, vertices: list[list[float]], triangles: list[list[int]]):
    """Add a translucent static mesh to a running scene.

    Builds directly from vertex/triangle data (no file, no
    MechanicalObject/mapping) and initializes just this subtree, so it can
    be added after Sofa.Simulation.initRoot() has already run on the rest
    of the scene.
    """
    import Sofa.Simulation  # type: ignore

    visual = rootnode.addChild("ReachZoneVisual")
    visual.addObject(
        "OglModel",
        name="reachZoneShape",
        position=vertices,
        triangles=triangles,
        color=[0.15, 0.55, 1.0, 0.35],
    )
    Sofa.Simulation.init(visual)
    return visual


def save_result(
    lab_root: Path,
    levels: list[tuple[float, list[tuple[float, float, float]]]],
    volume_mm3: float,
) -> Path:
    """Persist the swept grid stack so view_scene.py can render it in a fresh scene."""
    path = result_file(lab_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "levels": [{"y": y, "points": [list(p) for p in pts]} for y, pts in levels],
        "volume_mm3": volume_mm3,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_result(lab_root: Path) -> dict | None:
    """Load the most recently saved zone result, or None if none exists yet."""
    path = result_file(lab_root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    levels = [(lv["y"], [tuple(p) for p in lv["points"]]) for lv in data["levels"]]
    return {"levels": levels, "volume_mm3": data["volume_mm3"]}
