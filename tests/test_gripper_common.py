"""Unit tests for generation/_gripper_common.py — JSONC loading and the
config-dict → ModelParams mapping.

These pin the exact mapping behaviour (legacy fallback, type coercion,
fine-mode overrides) before any refactor of params_from_config.
"""

import pytest

from generation._gripper_common import load_jsonc, params_from_config
from geometry.params import ModelParams


def _write_jsonc(tmp_path, text: str):
    path = tmp_path / "cfg.jsonc"
    path.write_text(text, encoding="utf-8")
    return path


class TestLoadJsonc:
    def test_plain_json_passes_through(self, tmp_path):
        cfg = load_jsonc(_write_jsonc(tmp_path, '{"a": 1, "b": [2, 3]}'))
        assert cfg == {"a": 1, "b": [2, 3]}

    def test_full_line_comments_stripped(self, tmp_path):
        text = '{\n// header comment\n"a": 1\n}'
        assert load_jsonc(_write_jsonc(tmp_path, text)) == {"a": 1}

    def test_trailing_comments_stripped(self, tmp_path):
        text = '{\n"a": 1, // explains a\n"b": 2\n}'
        assert load_jsonc(_write_jsonc(tmp_path, text)) == {"a": 1, "b": 2}

    @pytest.mark.xfail(
        reason="the comment regex also strips '//' inside string values",
        strict=True,
    )
    def test_slashes_inside_string_values_survive(self, tmp_path):
        text = '{"url": "http://example.com"}'
        assert load_jsonc(_write_jsonc(tmp_path, text)) == {
            "url": "http://example.com"
        }


class TestParamsFromConfig:
    def test_empty_config_returns_defaults(self):
        assert params_from_config({}, ModelParams()) == ModelParams()

    def test_unknown_keys_are_ignored(self):
        assert params_from_config({"nonsense_key": 5}, ModelParams()) == ModelParams()

    def test_explicitly_mapped_field_applied(self):
        params = params_from_config({"cylinder_radius": 27.5}, ModelParams())
        assert params.cylinder_radius == 27.5

    def test_metadata_auto_field_applied(self):
        # p1_dist has no manual mapping — it must arrive via the opt-metadata loop.
        params = params_from_config({"p1_dist": 42.0}, ModelParams())
        assert params.p1_dist == 42.0

    def test_legacy_cylinder_height_fills_all_three(self):
        params = params_from_config({"cylinder_height": 3.0}, ModelParams())
        assert params.cylinder_height_A == 3.0
        assert params.cylinder_height_B == 3.0
        assert params.cylinder_height_C == 3.0

    def test_explicit_height_beats_legacy_fallback(self):
        cfg = {"cylinder_height": 3.0, "cylinder_height_B": 1.2}
        params = params_from_config(cfg, ModelParams())
        assert params.cylinder_height_A == 3.0
        assert params.cylinder_height_B == 1.2
        assert params.cylinder_height_C == 3.0

    def test_int_fields_round_from_float(self):
        params = params_from_config({"ring_ramp_samples": 64.7}, ModelParams())
        assert params.ring_ramp_samples == 65
        assert isinstance(params.ring_ramp_samples, int)

    def test_bool_field_coerced(self):
        params = params_from_config({"pincer_round_ends": 0}, ModelParams())
        assert params.pincer_round_ends is False

    def test_mesh_flags_forced_regardless_of_config(self):
        cfg = {"mesh_enabled": False, "mesh_show_viewer": True}
        params = params_from_config(cfg, ModelParams())
        assert params.mesh_enabled is True
        assert params.mesh_show_viewer is False


class TestParamsFromConfigFine:
    def test_fine_overrides_mesh_and_stem(self):
        params = params_from_config({}, ModelParams(), fine=True)
        assert params.export_stem == "new_gripper_print"
        assert params.mesh_size_max_stl == 2
        assert params.mesh_size_min_stl == 0.8

    def test_fine_raises_ring_samples_to_at_least_64(self):
        params = params_from_config({}, ModelParams(), fine=True)
        assert params.ring_ramp_samples >= 64

    def test_fine_keeps_higher_explicit_ring_samples(self):
        params = params_from_config({"ring_ramp_samples": 128}, ModelParams(), fine=True)
        assert params.ring_ramp_samples == 128

    def test_fine_doubles_profile_samples(self):
        base = ModelParams()
        params = params_from_config({}, base, fine=True)
        assert params.pincer_profile_samples == base.pincer_profile_samples * 2
