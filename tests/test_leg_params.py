"""Unit tests for geometry/leg_params.py — pure parameter math and validation.

Mirrors tests/test_params.py's conventions for the gripper's ModelParams.
"""

from dataclasses import fields, replace
from typing import get_type_hints

import pytest

from geometry.leg_params import LegParams, param_specs, validate_params


def test_field_defaults_match_their_annotations():
    """Every scalar field's default must have exactly its annotated type.

    params_from_config coerces config values based on the runtime type of
    the default, so a float field with an int default silently truncates
    config values for that field.
    """
    hints = get_type_hints(LegParams)
    defaults = LegParams()
    for f in fields(LegParams):
        annotated = hints[f.name]
        if annotated not in (int, float, bool, str):
            continue
        value = getattr(defaults, f.name)
        assert type(value) is annotated, (
            f"{f.name}: default {value!r} is {type(value).__name__}, "
            f"but the field is annotated {annotated.__name__}"
        )


class TestParamSpecs:
    def test_only_opt_annotated_fields_are_specs(self):
        spec_names = {s["name"] for s in param_specs()}
        opt_field_names = {f.name for f in fields(LegParams) if "opt" in f.metadata}
        assert spec_names == opt_field_names

    def test_defaults_within_bounds(self):
        for spec in param_specs():
            assert spec["min"] <= spec["default"] <= spec["max"], (
                f"{spec['name']}: default {spec['default']} outside "
                f"[{spec['min']}, {spec['max']}]"
            )

    def test_base_overrides_reported_defaults(self):
        base = replace(LegParams(), leg_p1_dist=200.0)
        specs = {s["name"]: s for s in param_specs(base)}
        assert specs["leg_p1_dist"]["default"] == 200.0

    def test_structural_fields_are_not_searched(self):
        spec_names = {s["name"] for s in param_specs()}
        assert "num_beams" not in spec_names
        assert "tip_straight_len" not in spec_names
        assert "export_stem" not in spec_names
        # Cross-section is fixed at the stock 10x5; only the spline is searched.
        assert "width" not in spec_names
        assert "thickness" not in spec_names

    def test_only_the_spline_is_searched(self):
        spec_names = {s["name"] for s in param_specs()}
        assert spec_names == {
            "leg_p0_hout_dist",
            "leg_p1_dist",
            "leg_p1_angle_deg",
            "leg_p1_hin_dist",
        }


class TestValidateParams:
    def test_defaults_are_valid(self):
        validate_params(LegParams())

    def test_check_metadata_vocabulary(self):
        """Guard against typos in any field's "check" metadata."""
        for f in fields(LegParams):
            check = f.metadata.get("check")
            if check is None:
                continue
            if isinstance(check, str):
                assert check in ("positive", "non_negative"), f.name
            else:
                assert check[0] in ("ge", "open_closed", "open_open"), f.name

    @pytest.mark.parametrize(
        "field_name, bad_value",
        [
            ("leg_p1_dist", 0.0),
            ("width", -1.0),
            ("thickness", 0.0),
            ("tip_straight_len", -5.0),
            ("num_beams", 4),
            ("leg_p0_hout_dist", -1.0),
            ("leg_p1_hin_dist", 0.0),
        ],
    )
    def test_rejects_invalid_values(self, field_name, bad_value):
        params = replace(LegParams(), **{field_name: bad_value})
        with pytest.raises(ValueError):
            validate_params(params)
