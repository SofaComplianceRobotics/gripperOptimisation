"""Unit tests for generation/_gripper_common.py — JSONC loading and the
config-dict → ModelParams mapping.

These pin the exact mapping behaviour (type coercion, fine-mode
overrides) before any refactor of params_from_config.
"""

import pytest

from generation._gripper_common import load_jsonc, params_from_config
from geometry.params import ModelParams
from names import GRIPPER_PRINT_NAME


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

    def test_slashes_inside_string_values_survive(self, tmp_path):
        text = '{"url": "http://example.com"}'
        assert load_jsonc(_write_jsonc(tmp_path, text)) == {
            "url": "http://example.com"
        }

    def test_comment_after_string_value_stripped(self, tmp_path):
        text = '{"path": "C://stuff" // windows-style path\n}'
        assert load_jsonc(_write_jsonc(tmp_path, text)) == {"path": "C://stuff"}

    def test_escaped_quote_inside_string(self, tmp_path):
        text = '{"label": "say \\"hi\\" // not a comment"}'
        assert load_jsonc(_write_jsonc(tmp_path, text)) == {
            "label": 'say "hi" // not a comment'
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

    def test_heights_applied_individually(self):
        cfg = {"cylinder_height_A": 3.0, "cylinder_height_B": 1.2}
        params = params_from_config(cfg, ModelParams())
        assert params.cylinder_height_A == 3.0
        assert params.cylinder_height_B == 1.2
        assert params.cylinder_height_C == ModelParams().cylinder_height_C

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

    def test_non_opt_field_applied_from_config(self):
        # All fields are configurable, not only the opt-annotated ones.
        params = params_from_config({"mesh_size_max_stl": 30.0}, ModelParams())
        assert params.mesh_size_max_stl == 30.0

    def test_export_naming_cannot_be_set_from_config(self):
        cfg = {"export_stem": "evil", "export_dir": "elsewhere"}
        params = params_from_config(cfg, ModelParams())
        assert params.export_stem == ModelParams().export_stem
        assert params.export_dir == ModelParams().export_dir


class TestParamsFromConfigFine:
    def test_fine_overrides_mesh_and_stem(self):
        params = params_from_config({}, ModelParams(), fine=True)
        assert params.export_stem == GRIPPER_PRINT_NAME
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
