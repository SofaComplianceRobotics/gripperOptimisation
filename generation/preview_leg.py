"""
Quick single-leg preview — generate a leg from the current config (with
optional inline overrides) and render it straight to a PNG.

Usage:
    python generation/preview_leg.py
    python generation/preview_leg.py --set leg_p1_angle_deg=110 --set leg_p1_dist=140

Must run under the emio-labs bundled Python (same one prepare_trial uses),
not a bare dev venv — needs gmsh/cadquery for the STL export and pyvista for
the render.
"""

from __future__ import annotations

import argparse
from dataclasses import fields, replace
from pathlib import Path

from _gripper_common import LAB_ROOT, ensure_cadquery_runtime, load_jsonc, params_from_config

ensure_cadquery_runtime()

from geometry.leg_geometry import build_leg  # noqa: E402
from geometry.leg_params import LegParams, validate_params  # noqa: E402

PREVIEW_DIR = LAB_ROOT / "runtime" / "leg_preview"


def _plot_debug(centerline, png_path: Path) -> None:
    """Draw the raw (u, v) centerline and its swept edges to a PNG, so a
    folded/self-intersecting shape can be inspected without a CAD viewer.
    Preview-only: not part of the geometry module the optimizer runs."""
    import matplotlib.pyplot as plt

    pts, tans = centerline._sample()
    us, vs = [p[0] for p in pts], [p[1] for p in pts]

    half = centerline.thickness / 2.0
    edges = [
        [(px - ty * half * sign, py + tx * half * sign) for (px, py), (tx, ty) in zip(pts, tans)]
        for sign in (1, -1)
    ]

    fig, ax = plt.subplots(figsize=(6, 8))
    ax.plot(us, vs, "-o", color="#4a90d9", markersize=2, linewidth=1.5, label="centerline")
    for edge, style in zip(edges, ("--", ":")):
        ax.plot([p[0] for p in edge], [p[1] for p in edge], style, color="#d94a4a", linewidth=1)
    ax.set_aspect("equal")
    ax.set_xlabel("u (outward)")
    ax.set_ylabel("v (up)")
    ax.set_title("Leg centerline — self-intersecting")
    ax.legend()
    fig.tight_layout()
    fig.savefig(str(png_path), dpi=150)
    plt.close(fig)


def _parse_overrides(raw: list[str], base: LegParams) -> dict:
    """Parse repeated ``--set field=value`` args, coerced to each field's type."""
    field_types = {f.name: type(getattr(base, f.name)) for f in fields(base)}
    overrides = {}
    for item in raw:
        if "=" not in item:
            raise ValueError(f"--set must be field=value, got {item!r}")
        key, value = item.split("=", 1)
        key = key.strip()
        if key not in field_types:
            raise ValueError(f"Unknown LegParams field: {key!r}")
        overrides[key] = field_types[key](value)
    return overrides


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate and render a single leg for a quick look."
    )
    parser.add_argument(
        "--config",
        type=str,
        default=str(LAB_ROOT / "config" / "lab_config.jsonc"),
        help="Base JSONC config (defaults missing fields).",
    )
    parser.add_argument(
        "--set",
        dest="overrides",
        action="append",
        default=[],
        metavar="field=value",
        help="Override one LegParams field, e.g. --set p1_x=40. Repeatable.",
    )
    args = parser.parse_args()

    cfg = load_jsonc(Path(args.config))
    params = params_from_config(cfg, LegParams())
    params = replace(params, **_parse_overrides(args.overrides, params))

    validate_params(params)
    centerline = build_leg(params)
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    if not centerline.is_valid():
        debug_png = PREVIEW_DIR / "leg_preview_debug.png"
        _plot_debug(centerline, debug_png)
        raise RuntimeError(
            "Leg centerline is self-intersecting; shape is unfeasible with these params. "
            f"Debug plot: {debug_png}"
        )

    stl_path = PREVIEW_DIR / "leg_preview.stl"
    png_path = PREVIEW_DIR / "leg_preview.png"

    if not centerline.export_stl(stl_path):
        raise RuntimeError("Leg STL export failed.")

    import pyvista as pv

    plotter = pv.Plotter(off_screen=True, window_size=(900, 700))
    mesh = pv.read(str(stl_path))
    plotter.add_mesh(mesh, color="#4a90d9", pbr=True, metallic=0.1, roughness=0.4)
    plotter.add_light(pv.Light(position=(200, 200, 400), intensity=0.8))
    plotter.background_color = "white"
    # Leg is planar in (u, v) = (z, y), running lengthwise along y; view
    # straight down the x axis with y held vertical for the actual bending
    # silhouette, instead of pyvista's default isometric angle.
    plotter.enable_parallel_projection()
    center = mesh.center
    plotter.camera_position = [
        (center[0] + 1.0, center[1], center[2]),
        center,
        (0, 1, 0),
    ]
    plotter.reset_camera()
    plotter.screenshot(str(png_path))
    plotter.close()

    print(f"PNG: {png_path}")


if __name__ == "__main__":
    main()
