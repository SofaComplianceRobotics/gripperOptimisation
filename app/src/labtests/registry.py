"""Known ShapeOPT test definitions."""

from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
SRC_ROOT = SCRIPT_DIR.parent
APP_ROOT = SRC_ROOT.parent
LAB_ROOT = APP_ROOT.parent


def _load_max_score(scoring_file: Path) -> float:
    """
    Import a test's scoring.py and return its MAX_SCORE constant.

    Falls back to 1.0 (i.e. no normalization effect) if the attribute is
    missing or the file cannot be imported, so existing tests without
    MAX_SCORE keep working unchanged.

    Inputs:
        scoring_file (Path): Absolute path to the test's scoring.py.

    Returns:
        float: The declared maximum score for the test.
    """
    try:
        spec = importlib.util.spec_from_file_location("_scoring_tmp", scoring_file)
        if spec is None or spec.loader is None:
            return 1.0
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return float(getattr(mod, "MAX_SCORE", 1.0))
    except Exception as exc:
        print(
            f"[labtests.registry] Could not read MAX_SCORE from {scoring_file}: {exc}"
        )
        return 1.0


@dataclass(frozen=True)
class TestSpec:
    """Metadata for one selectable simulation test."""

    name: str
    label: str
    description: str
    scene_file: Path
    scoring_file: Path
    max_score: float = 1.0
    default_selected: bool = False
    run_count: int = 1

    @property
    def display_label(self) -> str:
        return f"{self.label} — {self.description}"


def get_test_catalog() -> dict[str, TestSpec]:
    """Auto-discover all registered tests from subfolders, loading metadata from test.json."""
    test_catalog = {}
    labtests_dir = SCRIPT_DIR
    for entry in labtests_dir.iterdir():
        if not entry.is_dir() or entry.name.startswith("__"):
            continue
        scene_file = entry / "scene.py"
        scoring_file = entry / "scoring.py"
        meta_file = entry / "test.json"
        if not (scene_file.exists() and scoring_file.exists() and meta_file.exists()):
            continue
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                meta = json.load(f)
        except Exception as exc:
            print(
                f"[labtests.registry] Failed to load metadata for {entry.name}: {exc}"
            )
            continue
        name = entry.name
        label = meta.get("label", name)
        description = meta.get("description", "")
        default_selected = bool(meta.get("default_selected", False))
        run_count = int(meta.get("run_count", 1))
        max_score = _load_max_score(scoring_file)
        test_catalog[name] = TestSpec(
            name=name,
            label=label,
            description=description,
            scene_file=scene_file,
            scoring_file=scoring_file,
            max_score=max_score,
            default_selected=default_selected,
            run_count=run_count,
        )
    return test_catalog


def get_test_spec(test_name: str) -> TestSpec:
    """Resolve one test name to its specification."""
    catalog = get_test_catalog()
    try:
        return catalog[test_name]
    except KeyError as exc:
        available = ", ".join(sorted(catalog)) or "<none>"
        raise KeyError(f"Unknown test '{test_name}'. Available: {available}") from exc


def get_default_test_names() -> tuple[str, ...]:
    """Return the default test selection."""
    catalog = get_test_catalog()
    defaults = tuple(name for name, spec in catalog.items() if spec.default_selected)
    if defaults:
        return defaults
    return (next(iter(catalog)),)


def normalize_test_names(test_names: Iterable[str] | None) -> tuple[str, ...]:
    """Normalize a user-provided test list to known test names."""
    catalog = get_test_catalog()
    resolved: list[str] = []
    seen: set[str] = set()

    if test_names is None:
        return get_default_test_names()

    for raw_name in test_names:
        name = str(raw_name).strip()
        if not name or name in seen:
            continue
        if name not in catalog:
            raise KeyError(
                f"Unknown test '{name}'. Available: {', '.join(sorted(catalog))}"
            )
        resolved.append(name)
        seen.add(name)

    return tuple(resolved) or get_default_test_names()


def parse_test_names(raw_value: str | None) -> tuple[str, ...]:
    """Parse a comma-separated test selection from environment variables."""
    if not raw_value:
        return get_default_test_names()
    return normalize_test_names(part for part in raw_value.split(","))
