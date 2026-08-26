"""Unit tests for geometry/leg_geometry.py — the Emio leg centerline.

Only the pure math (path construction, frame sampling, feasibility checks)
is covered here, matching the rest of this suite: mesh export needs the CAD
runtime (cadquery/OCP) and is verified end-to-end under the bundled Python
instead.

The key regression target is the stock blueleg: the default LegParams must
reproduce it — straight leg at z = 22, wrap starting at (0, -22.5, 0), with
frames interchangeable with data/meshes/legs/blueleg.txt.
"""

import math
from dataclasses import replace

import numpy as np
import pytest

from geometry.leg_geometry import (
    CLIP_STRAIGHT_RUN,
    PULLEY_RADIUS,
    STRAIGHT_OFFSET,
    build_leg,
    LegCenterline,
)
from geometry.leg_params import LegParams


def _beams(params: LegParams) -> list[list[float]]:
    return build_leg(params).get_beams(params.num_beams)


class TestDefaultIsStockBlueleg:
    def test_default_is_valid(self):
        assert build_leg(LegParams()).is_valid()

    def test_first_frame_is_the_stock_wrap_start(self):
        first = _beams(LegParams())[0]
        assert first[0] == 0.0
        assert first[1] == pytest.approx(-PULLEY_RADIUS)
        assert first[2] == pytest.approx(0.0)
        # Stock blueleg.txt row 1 quat is (-0.5, -0.5, -0.5, 0.5); q and -q
        # are the same rotation.
        quat = np.array(first[3:])
        stock = np.array([-0.5, -0.5, -0.5, 0.5])
        assert np.allclose(quat, stock) or np.allclose(quat, -stock)

    def test_last_frame_is_the_tip(self):
        p = LegParams()
        last = _beams(p)[-1]
        # Stock straight leg: a=(22,0) + CLIP_STRAIGHT_RUN(0,1)
        # + leg_p1_dist(0,1) + tip_straight_len(0,1).
        expected_v = CLIP_STRAIGHT_RUN + p.leg_p1_dist + p.tip_straight_len
        assert last[1] == pytest.approx(expected_v)
        assert last[2] == pytest.approx(STRAIGHT_OFFSET)

    def test_straight_section_matches_stock_frames(self):
        # Above the wrap the stock leg runs at z=22 with quat (.7071, .7071, 0, 0).
        beams = _beams(LegParams())
        straight = [b for b in beams if b[1] > 20.0]
        assert len(straight) >= 8
        for b in straight:
            assert b[2] == pytest.approx(STRAIGHT_OFFSET, abs=1e-6)
            quat = np.array(b[3:])
            stock = np.array([np.sqrt(0.5), np.sqrt(0.5), 0.0, 0.0])
            assert np.allclose(quat, stock, atol=1e-6) or np.allclose(
                quat, -stock, atol=1e-6
            )

    def test_frames_strictly_ascend(self):
        ys = [b[1] for b in _beams(LegParams())]
        assert all(y2 > y1 for y1, y2 in zip(ys, ys[1:]))

    def test_planar_leg_x_always_zero(self):
        assert all(b[0] == 0.0 for b in _beams(LegParams()))


class TestTunableShape:
    def test_requested_beam_count(self):
        p = replace(LegParams(), num_beams=12)
        assert len(build_leg(p).get_beams(12)) == 12

    def test_unit_quaternions(self):
        for b in _beams(LegParams()):
            assert np.linalg.norm(b[3:]) == pytest.approx(1.0, abs=1e-9)

    def test_p1_dist_moves_the_tip(self):
        p = replace(LegParams(), leg_p1_dist=200.0)
        expected_v = CLIP_STRAIGHT_RUN + 200.0 + p.tip_straight_len
        assert _beams(p)[-1][1] == pytest.approx(expected_v)

    def test_p1_angle_moves_the_tip_laterally(self):
        # The fixed tip run now continues along leg_p1_angle_deg too (not
        # forced back to vertical), so it also contributes to the lateral
        # offset — see leg_geometry.py's build_leg docstring.
        p = replace(LegParams(), leg_p1_angle_deg=110.0)
        expected_u = STRAIGHT_OFFSET + (
            p.leg_p1_dist + p.tip_straight_len
        ) * math.cos(math.radians(110.0))
        assert _beams(p)[-1][2] == pytest.approx(expected_u, abs=1e-6)

    @pytest.mark.parametrize(
        "p1_dist, p1_angle, handle_dist",
        [
            (280.0, 120.0, 30.0),
            (280.0, 60.0, 30.0),
            (55.0, 120.0, 30.0),
            (55.0, 60.0, 30.0),
            (280.0, 120.0, 10.0),
            (55.0, 90.0, 5.0),
        ],
    )
    def test_extreme_in_bounds_configs_are_feasible(
        self, p1_dist, p1_angle, handle_dist
    ):
        # Corners of the angle/dist/handle bounds: CMA-ES should not be able
        # to sample an infeasible shape from within the spec bounds.
        p = replace(
            LegParams(),
            leg_p1_dist=p1_dist,
            leg_p1_angle_deg=p1_angle,
            leg_p0_hout_dist=handle_dist,
            leg_p1_hin_dist=handle_dist,
        )
        assert build_leg(p).is_valid()


class TestFeasibilityChecks:
    def test_fold_back_is_rejected(self):
        # A hand-built path that doubles back on itself vertically.
        from beziers.cubicbezier import CubicBezier
        from beziers.path import BezierPath
        from beziers.point import Point

        fold = BezierPath.fromSegments(
            [
                CubicBezier(
                    Point(0, 0), Point(0, 100), Point(0, 100), Point(0, 50)
                )
            ]
        )
        fold.closed = False
        leg = LegCenterline(path=fold, width=10.0, thickness=5.0, num_beams=15)
        assert not leg.is_valid()

    def test_crossing_is_rejected(self):
        # A loop: the path crosses itself.
        from beziers.cubicbezier import CubicBezier
        from beziers.path import BezierPath
        from beziers.point import Point

        loop = BezierPath.fromSegments(
            [
                CubicBezier(
                    Point(0, 0), Point(100, 100), Point(-100, 100), Point(20, 0)
                )
            ]
        )
        loop.closed = False
        leg = LegCenterline(path=loop, width=10.0, thickness=5.0, num_beams=15)
        assert not leg.is_valid()

    def test_short_handles_at_extreme_angle_are_rejected(self):
        # Both handle angles are pinned vertical (matching the fixed arc and
        # tip), so a too-short handle can't smoothly turn the span into an
        # extreme in-bounds angle before it reaches the end point — the
        # curve kinks near the join. This is the runtime safety net the spec
        # bounds alone can't rule out (see leg_params.py).
        p = replace(
            LegParams(),
            leg_p1_dist=100.0,
            leg_p1_angle_deg=120.0,
            leg_p0_hout_dist=5.0,
            leg_p1_hin_dist=5.0,
        )
        assert not build_leg(p).is_valid()


class TestExportPositions:
    def test_writes_one_row_per_beam(self, tmp_path):
        p = replace(LegParams(), num_beams=12)
        leg = build_leg(p)
        txt_path = tmp_path / "leg.txt"
        leg.export_positions(txt_path)

        loaded = np.loadtxt(str(txt_path))
        assert loaded.shape == (12, 7)

    def test_format_is_interchangeable_with_stock(self, tmp_path):
        # Same column layout as blueleg.txt: x y z qx qy qz qw per row.
        leg = build_leg(LegParams())
        txt_path = tmp_path / "leg.txt"
        leg.export_positions(txt_path)
        loaded = np.loadtxt(str(txt_path))
        assert loaded.shape[1] == 7
        assert np.allclose(loaded[:, 0], 0.0)
        assert np.allclose(np.linalg.norm(loaded[:, 3:], axis=1), 1.0)
