"""
Shared bootstrap, config loading, and parameter building for gripper generation scripts.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import fields, replace
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = LAB_ROOT

LAB_SITE_PACKAGES = LAB_ROOT / "runtime" / "modules" / "site-packages"


# Matches a JSON string literal (kept) or a // line comment (stripped).
# Trying the string alternative first prevents '//' inside values
# (e.g. URLs, Windows paths) from being treated as a comment.
_JSONC_STRING_OR_COMMENT = re.compile(r'("(?:\\.|[^"\\])*")|//[^\n]*')


def load_jsonc(path: Path) -> dict:
    """Load a JSONC file, stripping // line comments.

    Args:
        path: Path to the JSONC file.

    Returns:
        Parsed JSON content.
    """
    text = path.read_text(encoding="utf-8")
    text = _JSONC_STRING_OR_COMMENT.sub(lambda m: m.group(1) or "", text)
    return json.loads(text)


def _bootstrap_lab_site_packages() -> None:
    """Prepend the lab-local site-packages directory to sys.path if present.

    This allows generated scripts to import dependencies installed into
    `runtime/modules/site-packages`.
    """
    if LAB_SITE_PACKAGES.exists():
        sys.path.insert(0, str(LAB_SITE_PACKAGES))


def _has_required_runtime_packages() -> bool:
    """Return True if the required runtime packages (e.g. CadQuery) are importable.

    Returns:
        True when CadQuery is available in the current Python environment.
    """
    try:
        import cadquery  # noqa: F401

        return True
    except (ImportError, ModuleNotFoundError):
        return False


def ensure_cadquery_runtime() -> None:
    """Ensure CadQuery is importable, checking the lab-local site-packages.

    Raises:
        RuntimeError: If CadQuery is not importable from the current
            environment or from the lab-local site-packages.
    """
    if _has_required_runtime_packages():
        return
    _bootstrap_lab_site_packages()
    if _has_required_runtime_packages():
        return
    raise RuntimeError(
        "CadQuery is not importable. Install it into the active Python "
        f"environment, or into the lab-local directory: {LAB_SITE_PACKAGES} "
        f'(pip install --target "{LAB_SITE_PACKAGES}" cadquery).'
    )


# Never settable from a config file: the optimizer and SOFA scenes rely on
# the exported file names, so output naming stays a code-level contract.
_CONFIG_EXCLUDED_FIELDS = frozenset({"export_dir", "export_stem"})

# Always forced, regardless of what the config says: batch generation must
# produce meshes and must never block on a viewer window.
_CONFIG_FORCED_FIELDS = {"mesh_enabled": True, "mesh_show_viewer": False}


def params_from_config(cfg: dict, base, fine: bool = False):
    """Build a ModelParams instance from a config dict.

    Every ModelParams field whose name appears in the config is applied,
    coerced to the type of the field's default value. Unknown config keys
    are ignored. Exceptions: _CONFIG_EXCLUDED_FIELDS are never read from
    the config, and _CONFIG_FORCED_FIELDS always win.

    Args:
        cfg: Parsed lab_config.jsonc dict.
        base: A default ModelParams instance used for fallback values.
        fine: If True, override mesh settings for high-resolution 3D-print output.

    Returns:
        A new ModelParams instance.
    """
    kwargs: dict = {}
    for f in fields(base):
        if f.name in _CONFIG_EXCLUDED_FIELDS or f.name not in cfg:
            continue
        raw = cfg[f.name]
        default = getattr(base, f.name)
        # bool before int: bool is a subclass of int in Python.
        if isinstance(default, bool):
            kwargs[f.name] = bool(raw)
        elif isinstance(default, int):
            kwargs[f.name] = int(round(float(raw)))
        elif isinstance(default, float):
            kwargs[f.name] = float(raw)
        else:
            kwargs[f.name] = raw

    kwargs.update(_CONFIG_FORCED_FIELDS)

    if fine:
        kwargs["mesh_size_max_stl"] = 2
        kwargs["mesh_size_min_stl"] = 0.8
        kwargs["export_stem"] = "new_gripper_print"
        kwargs["ring_ramp_samples"] = max(
            kwargs.get("ring_ramp_samples", base.ring_ramp_samples), 64
        )
        current_samples = kwargs.get(
            "pincer_profile_samples", base.pincer_profile_samples
        )
        kwargs["pincer_profile_samples"] = current_samples * 2

    return replace(base, **kwargs)
