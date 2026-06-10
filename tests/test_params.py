"""Unit tests for geometry/params.py — pure parameter math and validation.

Covers the ring height interpolation, the polar→cartesian pincer spline
points, and the validate_params() rejection rules.
"""

from dataclasses import fields, replace
from typing import get_type_hints

import pytest

from geometry.params import ModelParams, validate_params


def test_field_defaults_match_their_annotations():
    """Every scalar field's default must have exactly its annotated type.

    params_from_config coerces config values based on the runtime type of
    the default, so a float field with an int default (e.g. 45 instead of
    45.0) silently truncates config values for that field.
    """
    hints = get_type_hints(ModelParams)
    defaults = ModelParams()
    for f in fields(ModelParams):
        annotated = hints[f.name]
        if annotated not in (int, float, bool, str):
            continue
        value = getattr(defaults, f.name)
        assert type(value) is annotated, (
            f"{f.name}: default {value!r} is {type(value).__name__}, "
            f"but the field is annotated {annotated.__name__}"
        )


class TestCylinderHeightAt:
    def test_anchor_angles_return_their_heights(self):
        # A sits at 0°/180°, B at 90°/270°, C at the 45° diagonals.
        p = ModelParams(
            cylinder_height_A=2.0, cylinder_height_B=4.0, cylinder_height_C=3.0
        )
        assert p.cylinder_height_at(0.0) == pytest.approx(2.0)
        assert p.cylinder_height_at(45.0) == pytest.approx(3.0)
        assert p.cylinder_height_at(90.0) == pytest.approx(4.0)
        assert p.cylinder_height_at(180.0) == pytest.approx(2.0)
        assert p.cylinder_height_at(270.0) == pytest.approx(4.0)
        assert p.cylinder_height_at(315.0) == pytest.approx(3.0)

    def test_uniform_heights_make_constant_ring(self):
        p = ModelParams(
            cylinder_height_A=2.5, cylinder_height_B=2.5, cylinder_height_C=2.5
        )
        for theta in range(0, 360, 7):
            assert p.cylinder_height_at(float(theta)) == pytest.approx(2.5)

    def test_periodic_in_360_degrees(self):
        p = ModelParams(cylinder_height_A=1.0, cylinder_height_B=5.0)
        for theta in (12.3, 100.0, 250.5):
            assert p.cylinder_height_at(theta + 360.0) == pytest.approx(
                p.cylinder_height_at(theta)
            )
            assert p.cylinder_height_at(theta - 360.0) == pytest.approx(
                p.cylinder_height_at(theta)
            )

    def test_midpoint_between_anchors_is_average_without_plateaus(self):
        # Cosine easing passes through the exact average halfway between anchors.
        p = ModelParams(cylinder_height_A=2.0, cylinder_height_C=4.0)
        assert p.cylinder_height_at(22.5) == pytest.approx(3.0)

    def test_plateau_holds_height_flat_around_anchor(self):
        # A 20° plateau on A keeps the ring at height_A for 10° on each side of 0°.
        p = ModelParams(
            cylinder_height_A=2.0,
            cylinder_height_B=4.0,
            cylinder_height_C=4.0,
            cylinder_plateau_A_deg=20.0,
        )
        assert p.cylinder_height_at(8.0) == pytest.approx(2.0)
        assert p.cylinder_height_at(352.0) == pytest.approx(2.0)
        # Outside the plateau the transition has started.
        assert p.cylinder_height_at(20.0) > 2.0

    def test_cylinder_height_property_is_max_of_three(self):
        p = ModelParams(
            cylinder_height_A=1.0, cylinder_height_B=5.0, cylinder_height_C=3.0
        )
        assert p.cylinder_height == 5.0


class TestPincerPoints:
    def test_two_points_with_endpoint_handles(self):
        pts = ModelParams().pincer_points
        assert len(pts) == 2
        assert pts[0].h_in is None and pts[0].h_out is not None
        assert pts[-1].h_out is None and pts[-1].h_in is not None

    def test_p0_anchored_at_origin(self):
        assert ModelParams().pincer_points[0].p == (0.0, 0.0)

    def test_p1_polar_to_cartesian(self):
        p = ModelParams(p1_dist=40.0, p1_angle_deg=-90.0)
        p1 = p.pincer_points[1]
        assert p1.p[0] == pytest.approx(0.0, abs=1e-9)
        assert p1.p[1] == pytest.approx(-40.0)

    def test_p0_handle_along_x_axis(self):
        p = ModelParams(p0_hout_dist=10.0, p0_hout_angle_deg=0.0)
        h_out = p.pincer_points[0].h_out
        assert h_out[0] == pytest.approx(10.0)
        assert h_out[1] == pytest.approx(0.0, abs=1e-9)

    def test_p1_hin_is_offset_from_p1_not_from_origin(self):
        p = ModelParams(
            p1_dist=40.0, p1_angle_deg=0.0, p1_hin_dist=5.0, p1_hin_angle_deg=90.0
        )
        p1 = p.pincer_points[1]
        assert p1.p[0] == pytest.approx(40.0)
        assert p1.h_in[0] == pytest.approx(40.0)
        assert p1.h_in[1] == pytest.approx(5.0)


class TestValidateParams:
    def test_defaults_are_valid(self):
        validate_params(ModelParams())

    @pytest.mark.parametrize(
        "field_name, bad_value",
        [
            ("cylinder_radius", 0.0),
            ("cylinder_height_A", -1.0),
            ("cylinder_hole_thickness", 0.0),
            ("leg_hole_length", 0.0),
            ("leg_wall_thickness", -0.5),
            ("slit_width", -0.1),
            ("leg_attachement_inward_offset", -1.0),
            ("pincer_profile_width", 0.0),
            ("pincer_profile_height", -2.0),
            ("pincer_path_scale", 0.0),
            ("mesh_size_max_stl", 0.0),
            ("mesh_collision_size", -1.0),
            ("mesh_angle_smooth", 90.0),
            ("mesh_collision_tail_fraction", 0.0),
        ],
    )
    def test_bad_value_rejected(self, field_name, bad_value):
        params = replace(ModelParams(), **{field_name: bad_value})
        with pytest.raises(ValueError, match=field_name):
            validate_params(params)

    def test_hole_thickness_larger_than_diameter_rejected(self):
        params = replace(ModelParams(), cylinder_hole_thickness=100.0)
        with pytest.raises(ValueError, match="cylinder_hole_thickness"):
            validate_params(params)

    def test_too_few_ring_ramp_samples_rejected(self):
        params = replace(ModelParams(), ring_ramp_samples=4)
        with pytest.raises(ValueError, match="ring_ramp_samples"):
            validate_params(params)

    def test_too_few_profile_samples_rejected(self):
        params = replace(ModelParams(), pincer_profile_samples=3)
        with pytest.raises(ValueError, match="pincer_profile_samples"):
            validate_params(params)
