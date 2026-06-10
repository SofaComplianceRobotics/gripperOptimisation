"""Tests for labtests/registry.py — runs against the real labtests/ folder.

These are light integration tests: the registry's job is to discover the
actual test folders, so the real directory is the right fixture.
"""

import pytest

from labtests.registry import (
    get_default_test_names,
    get_test_catalog,
    get_test_spec,
    normalize_test_names,
    parse_test_names,
)

KNOWN_TESTS = ("grasp_hold", "random_cube_pick", "gripper_tilt")


class TestDiscovery:
    def test_known_tests_discovered(self):
        catalog = get_test_catalog()
        for name in KNOWN_TESTS:
            assert name in catalog

    def test_spec_files_exist_and_metadata_loaded(self):
        spec = get_test_spec("grasp_hold")
        assert spec.scene_file.exists()
        assert spec.scoring_file.exists()
        assert spec.max_score > 0
        assert spec.run_count >= 1
        assert spec.label

    def test_unknown_test_raises_and_lists_available(self):
        with pytest.raises(KeyError, match="Unknown test"):
            get_test_spec("does_not_exist")

    def test_defaults_are_a_nonempty_subset_of_catalog(self):
        catalog = get_test_catalog()
        defaults = get_default_test_names()
        assert len(defaults) >= 1
        assert all(name in catalog for name in defaults)


class TestNameParsing:
    def test_normalize_dedups(self):
        assert normalize_test_names(["grasp_hold", "grasp_hold"]) == ("grasp_hold",)

    def test_normalize_rejects_unknown(self):
        with pytest.raises(KeyError, match="Unknown test"):
            normalize_test_names(["nope"])

    def test_normalize_none_returns_defaults(self):
        assert normalize_test_names(None) == get_default_test_names()

    def test_parse_comma_separated(self):
        assert parse_test_names("grasp_hold,gripper_tilt") == (
            "grasp_hold",
            "gripper_tilt",
        )

    def test_parse_empty_returns_defaults(self):
        assert parse_test_names(None) == get_default_test_names()
        assert parse_test_names("") == get_default_test_names()
