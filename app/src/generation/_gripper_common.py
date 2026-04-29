"""
Shared bootstrap, config loading, and parameter building for gripper generation scripts.
"""

from __future__ import annotations

import importlib
import json
import math
import re
import subprocess
import sys
from dataclasses import fields, replace
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = SRC_ROOT.parent
LAB_ROOT = APP_ROOT.parent

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

LAB_SITE_PACKAGES = LAB_ROOT / "runtime" / "modules" / "site-packages"
LAB_REQUIREMENTS = APP_ROOT / "requirements.txt"


def load_jsonc(path: Path) -> dict:
    """Load a JSONC file, stripping // line comments.

    Args:
        path: Path to the JSONC file.

    Returns:
        Parsed JSON content.
    """
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"//.*$", "", text, flags=re.MULTILINE)
    return json.loads(text)


def _bootstrap_lab_site_packages() -> None:
    if LAB_SITE_PACKAGES.exists():
        sys.path.insert(0, str(LAB_SITE_PACKAGES))


_bootstrap_lab_site_packages()


def _has_required_runtime_packages() -> bool:
    try:
        import cadquery  # noqa: F401
        return True
    except ModuleNotFoundError:
        return False


def _install_lab_dependencies_here() -> bool:
    if not LAB_REQUIREMENTS.exists():
        return False
    LAB_SITE_PACKAGES.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            sys.executable, "-m", "pip", "install",
            "--disable-pip-version-check",
            "--target", str(LAB_SITE_PACKAGES),
            "-r", str(LAB_REQUIREMENTS),
        ],
        check=False,
    )
    if result.returncode != 0:
        return False
    importlib.invalidate_caches()
    _bootstrap_lab_site_packages()
    return True


def ensure_cadquery_runtime() -> None:
    """Ensure CadQuery is importable, auto-installing into the lab-local site-packages if needed.

    Raises:
        RuntimeError: If CadQuery cannot be used after the auto-install attempt.
    """
    if _has_required_runtime_packages():
        return
    if _install_lab_dependencies_here() and _has_required_runtime_packages():
        return
    raise RuntimeError(
        "CadQuery is not available in Emio's Python runtime and auto-install "
        "failed. Please ensure pip installation is allowed and retry from Emio."
    )


def params_from_config(cfg: dict, base, fine: bool = False):
    """Build a ModelParams instance from a config dict.

    Converts the polar Bézier representation in the config to absolute XY
    coordinates expected by ModelParams, then applies all other fields.

    Args:
        cfg: Parsed lab_config.jsonc dict.
        base: A default ModelParams instance used for fallback values.
        fine: If True, override mesh settings for high-resolution 3D-print output.

    Returns:
        A new ModelParams instance.
    """
    from core.params import PincerSplinePoint

    p0_hout_dist = float(cfg.get("p0_hout_dist", 0.0))
    p0_hout_angle = math.radians(float(cfg.get("p0_hout_angle_deg", 0.0)))
    p0_hout_x = p0_hout_dist * math.cos(p0_hout_angle)
    p0_hout_y = p0_hout_dist * math.sin(p0_hout_angle)

    p1_dist = float(cfg.get("p1_dist", 80.0))
    p1_angle = math.radians(float(cfg.get("p1_angle_deg", -40.0)))
    p1_x = p1_dist * math.cos(p1_angle)
    p1_y = p1_dist * math.sin(p1_angle)

    p1_hin_dist = float(cfg.get("p1_hin_dist", 0.0))
    p1_hin_angle = math.radians(float(cfg.get("p1_hin_angle_deg", 0.0)))
    p1_hin_x = p1_x + p1_hin_dist * math.cos(p1_hin_angle)
    p1_hin_y = p1_y + p1_hin_dist * math.sin(p1_hin_angle)

    kwargs: dict = dict(
        cylinder_radius=float(cfg.get("cylinder_radius", base.cylinder_radius)),
        cylinder_height=float(cfg.get("cylinder_height", base.cylinder_height)),
        cylinder_hole_thickness=float(cfg.get("cylinder_hole_thickness", base.cylinder_hole_thickness)),
        leg_attachement_tilt_angle=float(cfg.get("leg_attachement_tilt_angle", base.leg_attachement_tilt_angle)),
        pincer_profile_width=float(cfg.get("pincer_profile_width", base.pincer_profile_width)),
        pincer_profile_height=float(cfg.get("pincer_profile_height", base.pincer_profile_height)),
        pincer_profile_samples=int(round(float(cfg.get("pincer_profile_samples", base.pincer_profile_samples)))),
        pincer_round_cap_segments=int(round(float(cfg.get("pincer_round_cap_segments", base.pincer_round_cap_segments)))),
        pincer_path_scale=float(cfg.get("pincer_path_scale", base.pincer_path_scale)),
        pincer_tilt_y_deg=float(cfg.get("pincer_tilt_y_deg", base.pincer_tilt_y_deg)),
        pincer_round_ends=bool(cfg.get("pincer_round_ends", base.pincer_round_ends)),
        pincer_points=(
            PincerSplinePoint(p=(0.0, 0.0), h_in=None, h_out=(p0_hout_x, p0_hout_y)),
            PincerSplinePoint(p=(p1_x, p1_y), h_in=(p1_hin_x, p1_hin_y), h_out=None),
        ),
        mesh_enabled=True,
        mesh_show_viewer=False,
    )

    # Auto-apply any ModelParams scalar field annotated with opt metadata
    # that isn't already set explicitly above. This means adding a new
    # directly-mapped optimisable parameter only requires editing ModelParams.
    for _f in fields(base):
        if _f.name in kwargs:
            continue
        _opt = _f.metadata.get("opt")
        if _opt is None:
            continue
        _raw = cfg.get(_f.name, getattr(base, _f.name))
        _t = _opt.get("type", "float")
        if _t == "int":
            kwargs[_f.name] = int(round(float(_raw)))
        elif _t == "bool":
            kwargs[_f.name] = bool(_raw)
        else:
            kwargs[_f.name] = float(_raw)

    if fine:
        kwargs["mesh_size_max_stl"] = 2.0
        kwargs["mesh_size_min_stl"] = 0.8
        kwargs["export_stem"] = "new_gripper_print"
        current_samples = kwargs.get("pincer_profile_samples", base.pincer_profile_samples)
        kwargs["pincer_profile_samples"] = current_samples * 10

    return replace(base, **kwargs)
