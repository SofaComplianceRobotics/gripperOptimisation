"""Unit tests for the pure parsing helpers in optimization/config.py.

Importing optimization.config requires several SOFA_* env vars at module
level; conftest.py supplies dummies so the import succeeds. Only the
pure string/JSON parsing functions are tested here — nothing launches.
"""

import json

import pytest

from optimization.config import _parse_gated_test_names, _parse_test_weights

TESTS = ["alpha", "beta"]


class TestParseTestWeights:
    def test_missing_env_gives_equal_split(self):
        assert _parse_test_weights(None, TESTS) == {"alpha": 0.5, "beta": 0.5}

    def test_empty_string_gives_equal_split(self):
        assert _parse_test_weights("", TESTS) == {"alpha": 0.5, "beta": 0.5}

    def test_percentages_normalised_to_fractions(self):
        raw = json.dumps({"alpha": 70, "beta": 30})
        weights = _parse_test_weights(raw, TESTS)
        assert weights["alpha"] == pytest.approx(0.7)
        assert weights["beta"] == pytest.approx(0.3)

    def test_weights_always_sum_to_one(self):
        raw = json.dumps({"alpha": 1, "beta": 3})
        weights = _parse_test_weights(raw, TESTS)
        assert sum(weights.values()) == pytest.approx(1.0)
        assert weights["beta"] == pytest.approx(0.75)

    def test_malformed_json_falls_back_to_equal(self):
        assert _parse_test_weights("{not json", TESTS) == {"alpha": 0.5, "beta": 0.5}

    def test_non_dict_json_falls_back_to_equal(self):
        assert _parse_test_weights("[1, 2]", TESTS) == {"alpha": 0.5, "beta": 0.5}

    def test_missing_test_key_falls_back_to_equal(self):
        raw = json.dumps({"alpha": 100})
        assert _parse_test_weights(raw, TESTS) == {"alpha": 0.5, "beta": 0.5}

    def test_extra_keys_ignored(self):
        raw = json.dumps({"alpha": 50, "beta": 50, "ghost": 999})
        weights = _parse_test_weights(raw, TESTS)
        assert set(weights) == {"alpha", "beta"}

    def test_zero_total_falls_back_to_equal(self):
        raw = json.dumps({"alpha": 0, "beta": 0})
        assert _parse_test_weights(raw, TESTS) == {"alpha": 0.5, "beta": 0.5}

    def test_empty_test_list_gives_empty_dict(self):
        assert _parse_test_weights(None, []) == {}


class TestParseGatedTestNames:
    def test_missing_env_gives_empty(self):
        assert _parse_gated_test_names(None, TESTS) == ()
        assert _parse_gated_test_names("", TESTS) == ()

    def test_filters_to_selected_tests_only(self):
        assert _parse_gated_test_names("alpha,ghost", TESTS) == ("alpha",)

    def test_dedups_and_keeps_order(self):
        assert _parse_gated_test_names("beta,alpha,beta", TESTS) == ("beta", "alpha")

    def test_whitespace_stripped(self):
        assert _parse_gated_test_names(" alpha , beta ", TESTS) == ("alpha", "beta")
