"""
Shared bootstrap, config loading, and parameter building for gripper generation scripts.
"""

from __future__ import annotations

import importlib
import json
import re
import subprocess
import sys
from dataclasses import fields, replace
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1]
LAB_ROOT = SRC_ROOT
APP_ROOT = LAB_ROOT

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

LAB_SITE_PACKAGES = LAB_ROOT / "runtime" / "modules" / "site-packages"
LAB_REQUIREMENTS = LAB_ROOT / "requirements.txt"


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
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--target",
            str(LAB_SITE_PACKAGES),
            "-r",
            str(LAB_REQUIREMENTS),
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

    Args:
        cfg: Parsed lab_config.jsonc dict.
        base: A default ModelParams instance used for fallback values.
        fine: If True, override mesh settings for high-resolution 3D-print output.

    Returns:
        A new ModelParams instance.
    """
    _legacy_h = cfg.get("cylinder_height")
    _h_fallback = float(_legacy_h) if _legacy_h is not None else None

    kwargs: dict = dict(
        cylinder_radius=float(cfg.get("cylinder_radius", base.cylinder_radius)),
        cylinder_hole_thickness=float(
            cfg.get("cylinder_hole_thickness", base.cylinder_hole_thickness)
        ),
        cylinder_height_A=float(
            cfg.get(
                "cylinder_height_A",
                _h_fallback if _h_fallback is not None else base.cylinder_height_A,
            )
        ),
        cylinder_height_B=float(
            cfg.get(
                "cylinder_height_B",
                _h_fallback if _h_fallback is not None else base.cylinder_height_B,
            )
        ),
        cylinder_height_C=float(
            cfg.get(
                "cylinder_height_C",
                _h_fallback if _h_fallback is not None else base.cylinder_height_C,
            )
        ),
        cylinder_plateau_A_deg=float(
            cfg.get("cylinder_plateau_A_deg", base.cylinder_plateau_A_deg)
        ),
        cylinder_plateau_B_deg=float(
            cfg.get("cylinder_plateau_B_deg", base.cylinder_plateau_B_deg)
        ),
        cylinder_plateau_C_deg=float(
            cfg.get("cylinder_plateau_C_deg", base.cylinder_plateau_C_deg)
        ),
        leg_attachement_tilt_angle=float(
            cfg.get("leg_attachement_tilt_angle", base.leg_attachement_tilt_angle)
        ),
        pincer_profile_width=float(
            cfg.get("pincer_profile_width", base.pincer_profile_width)
        ),
        pincer_profile_height=float(
            cfg.get("pincer_profile_height", base.pincer_profile_height)
        ),
        pincer_profile_samples=int(
            round(float(cfg.get("pincer_profile_samples", base.pincer_profile_samples)))
        ),
        pincer_round_cap_segments=int(
            round(
                float(
                    cfg.get("pincer_round_cap_segments", base.pincer_round_cap_segments)
                )
            )
        ),
        pincer_path_scale=float(cfg.get("pincer_path_scale", base.pincer_path_scale)),
        pincer_tilt_y_deg=float(cfg.get("pincer_tilt_y_deg", base.pincer_tilt_y_deg)),
        pincer_round_ends=bool(cfg.get("pincer_round_ends", base.pincer_round_ends)),
        ring_ramp_samples=int(
            round(float(cfg.get("ring_ramp_samples", base.ring_ramp_samples)))
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
        kwargs["ring_ramp_samples"] = max(
            kwargs.get("ring_ramp_samples", base.ring_ramp_samples), 64
        )
        current_samples = kwargs.get(
            "pincer_profile_samples", base.pincer_profile_samples
        )
        kwargs["pincer_profile_samples"] = current_samples * 10

    return replace(base, **kwargs)
