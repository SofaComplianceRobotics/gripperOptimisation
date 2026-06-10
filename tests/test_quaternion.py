"""Unit tests for the quaternion helpers in geometry/transforms/quaternion.py.

The module imports cadquery for a single type annotation; conftest.py
registers a stub so the pure math is testable without the CAD runtime.

Quaternions here are (x, y, z, w) tuples. The key invariants tested:
unit length, identity behaviour, rotation correctness on known vectors,
and the CadQuery→SOFA export frame mapping.
"""

import math

import pytest

from geometry.transforms.quaternion import (
    _axis_angle_to_quat,
    _export_frame_quat,
    _normalize_quat,
    _quat_conjugate,
    _quat_mul,
    _quat_rotate_vector,
)

SQRT2_2 = math.sqrt(2.0) / 2.0
IDENTITY = (0.0, 0.0, 0.0, 1.0)


def _length(v: tuple) -> float:
    return math.sqrt(sum(c * c for c in v))


class TestAxisAngleToQuat:
    def test_90deg_about_z(self):
        q = _axis_angle_to_quat((0.0, 0.0, 1.0), 90.0)
        assert q == pytest.approx((0.0, 0.0, SQRT2_2, SQRT2_2))

    def test_axis_is_normalised_before_use(self):
        scaled = _axis_angle_to_quat((0.0, 0.0, 10.0), 90.0)
        unit = _axis_angle_to_quat((0.0, 0.0, 1.0), 90.0)
        assert scaled == pytest.approx(unit)

    def test_zero_axis_returns_identity(self):
        assert _axis_angle_to_quat((0.0, 0.0, 0.0), 45.0) == IDENTITY

    def test_result_is_unit_length(self):
        q = _axis_angle_to_quat((3.0, -2.0, 5.0), 123.0)
        assert _length(q) == pytest.approx(1.0)


class TestQuatAlgebra:
    def test_identity_is_neutral_for_multiplication(self):
        q = _axis_angle_to_quat((1.0, 2.0, 3.0), 33.0)
        assert _quat_mul(q, IDENTITY) == pytest.approx(q)
        assert _quat_mul(IDENTITY, q) == pytest.approx(q)

    def test_quat_times_conjugate_is_identity(self):
        q = _axis_angle_to_quat((1.0, 1.0, 0.0), 70.0)
        assert _quat_mul(q, _quat_conjugate(q)) == pytest.approx(IDENTITY)

    def test_normalize_restores_unit_length(self):
        q = (2.0, 0.0, 0.0, 2.0)
        assert _length(_normalize_quat(q)) == pytest.approx(1.0)

    def test_normalize_zero_quat_returns_identity(self):
        assert _normalize_quat((0.0, 0.0, 0.0, 0.0)) == IDENTITY


class TestRotateVector:
    def test_90deg_about_z_sends_x_to_y(self):
        q = _axis_angle_to_quat((0.0, 0.0, 1.0), 90.0)
        rotated = _quat_rotate_vector(q, (1.0, 0.0, 0.0))
        assert rotated == pytest.approx((0.0, 1.0, 0.0), abs=1e-12)

    def test_rotation_about_own_axis_is_a_no_op(self):
        q = _axis_angle_to_quat((0.0, 0.0, 1.0), 137.0)
        rotated = _quat_rotate_vector(q, (0.0, 0.0, 4.2))
        assert rotated == pytest.approx((0.0, 0.0, 4.2))

    def test_rotation_preserves_length(self):
        q = _axis_angle_to_quat((3.0, -2.0, 5.0), 123.0)
        v = (1.0, 2.0, -3.0)
        assert _length(_quat_rotate_vector(q, v)) == pytest.approx(_length(v))


class TestExportFrame:
    def test_is_unit_length(self):
        assert _length(_export_frame_quat()) == pytest.approx(1.0)

    def test_maps_cadquery_z_up_to_sofa_y_up(self):
        # CadQuery builds Z-up; the SOFA scenes are Y-up (gravity is -Y).
        q = _export_frame_quat()
        rotated = _quat_rotate_vector(q, (0.0, 0.0, 1.0))
        assert rotated == pytest.approx((0.0, 1.0, 0.0), abs=1e-12)

    def test_matches_rotate_model_composition(self):
        # rotate_model_to_export_frame applies R_x(-90) then R_y(+90);
        # the quaternion must encode the same composed rotation.
        q = _export_frame_quat()
        qx = _axis_angle_to_quat((1.0, 0.0, 0.0), -90.0)
        qy = _axis_angle_to_quat((0.0, 1.0, 0.0), 90.0)
        for v in [(1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)]:
            two_step = _quat_rotate_vector(qy, _quat_rotate_vector(qx, v))
            assert _quat_rotate_vector(q, v) == pytest.approx(two_step, abs=1e-12)
