"""Known ShapeOPT test definitions."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
SRC_ROOT = SCRIPT_DIR.parent
APP_ROOT = SRC_ROOT.parent
LAB_ROOT = APP_ROOT.parent


@dataclass(frozen=True)
class TestSpec:
    """Metadata for one selectable simulation test."""

    name: str
    label: str
    description: str
    scene_file: Path
    scoring_file: Path
    default_selected: bool = False
    run_count: int = 1

    @property
    def display_label(self) -> str:
        return f"{self.label} — {self.description}"


import json


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
        test_catalog[name] = TestSpec(
            name=name,
            label=label,
            description=description,
            scene_file=scene_file,
            scoring_file=scoring_file,
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
