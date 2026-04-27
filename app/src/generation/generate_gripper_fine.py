"""
Lab Gripper Optimisation - Fine Mesh Generation Entrypoint.

Same as generate_gripper.py but uses a much finer mesh suitable for real-life
3D printing. Output is saved as new_gripper_print.stl (separate from the
coarser simulation mesh new_gripper.stl).
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import subprocess
import time
from pathlib import Path
from dataclasses import replace
import math


# ─────────────────────────────────────────────
# Paths & Bootstrap
# ─────────────────────────────────────────────
SRC_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = SRC_ROOT.parent
LAB_ROOT = APP_ROOT.parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

LAB_SITE_PACKAGES = LAB_ROOT / "runtime" / "modules" / "site-packages"
LAB_REQUIREMENTS = APP_ROOT / "requirements.txt"
_START_TS = time.perf_counter()

# Fine-mesh settings (mm). Lower = more triangles = better print quality.
_FINE_MESH_SIZE_MAX = 2.0
_FINE_MESH_SIZE_MIN = 0.8
_FINE_EXPORT_STEM = "new_gripper_print"


def load_jsonc(path: Path) -> dict:
    """Load JSONC file, stripping // comments.

    Args:
        path: Path to JSONC file.

    Returns:
        Parsed JSON content.
    """
    import re

    text = path.read_text(encoding="utf-8")
    text = re.sub(r"//.*$", "", text, flags=re.MULTILINE)
    return json.loads(text)


def _bootstrap_lab_site_packages() -> None:
    """Prepend the lab-local site-packages directory if it exists."""
    if LAB_SITE_PACKAGES.exists():
        sys.path.insert(0, str(LAB_SITE_PACKAGES))


_bootstrap_lab_site_packages()


def _has_required_runtime_packages() -> bool:
    """Return True when CadQuery is importable in the current runtime."""
    try:
        import cadquery  # noqa: F401

        return True
    except ModuleNotFoundError:
        return False


def _install_lab_dependencies_here() -> bool:
    """Install lab requirements into a lab-local site-packages folder.

    Returns:
        True if installation succeeded, False otherwise.
    """
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


def _ensure_cadquery_runtime() -> None:
    """Ensure CadQuery is available, auto-installing if necessary.

    Raises:
        RuntimeError: If CadQuery cannot be used after an auto-install attempt.
    """
    if _has_required_runtime_packages():
        return

    if _install_lab_dependencies_here() and _has_required_runtime_packages():
        return

    raise RuntimeError(
        "CadQuery is not available in Emio's Python runtime and auto-install "
        "failed. Please ensure pip installation is allowed and retry from Emio."
    )


_ensure_cadquery_runtime()

from core.export_pipeline import run_export
from core.params import ModelParams, PincerSplinePoint


# ─────────────────────────────────────────────
# Main Entry Point
# ─────────────────────────────────────────────


def main() -> None:
    """
    Read parameters from lab_config.jsonc and run a fine-mesh export for printing.
    """
    parser = argparse.ArgumentParser(
        description="Generate fine gripper meshes for 3D printing from a JSONC config."
    )
    parser.add_argument(
        "--config",
        type=str,
        default=str(LAB_ROOT / "config" / "lab_config.jsonc"),
        help="Path to config JSONC file. Defaults to config/lab_config.jsonc in the lab root.",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    cfg = load_jsonc(config_path)
    base = ModelParams()

    p0_hout_dist = float(cfg["p0_hout_dist"])
    p0_hout_angle = math.radians(float(cfg["p0_hout_angle_deg"]))
    p0_hout_x = p0_hout_dist * math.cos(p0_hout_angle)
    p0_hout_y = p0_hout_dist * math.sin(p0_hout_angle)

    p1_dist = float(cfg["p1_dist"])
    p1_angle = math.radians(float(cfg["p1_angle_deg"]))
    p1_x = p1_dist * math.cos(p1_angle)
    p1_y = p1_dist * math.sin(p1_angle)

    p1_hin_dist = float(cfg["p1_hin_dist"])
    p1_hin_angle = math.radians(float(cfg["p1_hin_angle_deg"]))
    p1_hin_x = p1_x + p1_hin_dist * math.cos(p1_hin_angle)
    p1_hin_y = p1_y + p1_hin_dist * math.sin(p1_hin_angle)

    params = replace(
        base,
        cylinder_radius=float(cfg["cylinder_radius"]),
        cylinder_height=float(cfg["cylinder_height"]),
        cylinder_hole_thickness=float(cfg["cylinder_hole_thickness"]),
        leg_attachement_tilt_angle=float(cfg["leg_attachement_tilt_angle"]),
        pincer_profile_width=float(cfg["pincer_profile_width"]),
        pincer_profile_height=float(cfg["pincer_profile_height"]),
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
        pincer_path_scale=float(cfg["pincer_path_scale"]),
        pincer_tilt_y_deg=float(cfg["pincer_tilt_y_deg"]),
        pincer_round_ends=bool(cfg.get("pincer_round_ends", base.pincer_round_ends)),
        pincer_points=(
            PincerSplinePoint(
                p=(0.0, 0.0),
                h_in=None,
                h_out=(p0_hout_x, p0_hout_y),
            ),
            PincerSplinePoint(
                p=(p1_x, p1_y),
                h_in=(p1_hin_x, p1_hin_y),
                h_out=None,
            ),
        ),
        # Fine mesh overrides for 3D printing
        mesh_size_max_stl=_FINE_MESH_SIZE_MAX,
        mesh_size_min_stl=_FINE_MESH_SIZE_MIN,
        mesh_enabled=True,
        mesh_show_viewer=False,
        export_stem=_FINE_EXPORT_STEM,
    )

    secondary_dir = LAB_ROOT.parent.parent / "data" / "meshes" / "centerparts"

    stl_path = run_export(params, secondary_dir=secondary_dir)
    if stl_path is None:
        raise RuntimeError("Mesh export did not produce an STL path.")

    json_path = stl_path.with_suffix(".json")
    vtk_path = stl_path.with_suffix(".vtk")

    if stl_path.exists():
        print(f"Exported fine STL: {stl_path}")
    if json_path.exists():
        print(f"Exported JSON: {json_path}")
    if vtk_path.exists():
        print(f"Exported VTK: {vtk_path}")

    elapsed = time.perf_counter() - _START_TS
    print(f"Total export time: {elapsed:.3f}s")
    print(
        f"Mesh settings: max={_FINE_MESH_SIZE_MAX}mm, min={_FINE_MESH_SIZE_MIN}mm "
        f"(finer than simulation mesh — may take longer)"
    )


if __name__ == "__main__":
    main()
