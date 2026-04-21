"""Test registry and launch helpers for ShapeOPT."""

from .registry import TestSpec, get_default_test_names, get_test_catalog, get_test_spec
from .ui import prompt_for_tests

__all__ = [
    "TestSpec",
    "get_default_test_names",
    "get_test_catalog",
    "get_test_spec",
    "prompt_for_tests",
]
