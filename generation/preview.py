"""Render the current config's gripper and/or leg to a PNG — a quick visual check.

Standalone dev tool. Builds the shape(s) from ``config/lab_config.jsonc`` (with
optional inline overrides), writes them to ``runtime/previews/`` and renders a
PNG. Nothing here writes to the real generation outputs.

Usage:
    python generation/preview.py                              # gripper + leg
    python generation/preview.py --part gripper
    python generation/preview.py --part leg --set leg_p1_dist=140 --set leg_p1_angle_deg=110

The optimizer does not call this: it renders its own per-trial thumbnail in
``sofaopt_project.py``, which imports :func:`render_mesh_grid` from here so the
two stay identical.

Must run under the emio-labs bundled Python (gmsh/cadquery for the mesh export,
pyvista for the render), not a bare dev venv.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import fields, replace
from pathlib import Path

_LAB_ROOT = Path(__file__).resolve().parents[1]
PREVIEW_DIR = _LAB_ROOT / "runtime" / "previews"

# Run as a script (only generation/ on sys.path) or imported as
# generation.preview (only the lab root) — make both work before any
# `from _gripper_common import` / `from geometry...` below.
for _p in (str(_LAB_ROOT), str(_LAB_ROOT / "generation")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_MESH_COLOR = "#4a90d9"


# --- rendering (pyvista only — import stays cheap and side-effect free) --------

def _aim_head_on(plotter, mesh) -> None:
    """Point the camera straight down the x axis with y held vertical, in
    parallel projection — the true bending/opening silhouette rather than
    pyvista's default isometric angle."""
    plotter.enable_parallel_projection()
    c = mesh.center
    plotter.camera_position = [(c[0] + 1.0, c[1], c[2]), c, (0, 1, 0)]
    plotter.reset_camera()


def render_mesh_png(stl_path, png_path, *, title: str | None = None,
                    window_size: tuple[int, int] = (900, 700)) -> None:
    """Render one STL to a PNG."""
    import pyvista as pv

    plotter = pv.Plotter(off_screen=True, window_size=window_size)
    try:
        mesh = pv.read(str(stl_path))
        plotter.add_mesh(mesh, color=_MESH_COLOR, pbr=True, metallic=0.1, roughness=0.4)
        plotter.add_light(pv.Light(position=(200, 200, 400), intensity=0.8))
        plotter.background_color = "white"
        if title:
            plotter.add_text(title, font_size=14)
        _aim_head_on(plotter, mesh)
        plotter.screenshot(str(png_path))
    finally:
        plotter.close()


def render_mesh_grid(items, png_path,
                     window_size: tuple[int, int] = (1600, 600)) -> None:
    """Render several STLs side by side into one PNG.

    Args:
        items: Sequence of ``(title, stl_path)`` pairs, one subplot each.
        png_path: Destination PNG.
        window_size: Full canvas size in pixels.
    """
    import pyvista as pv

    items = list(items)
    plotter = pv.Plotter(off_screen=True, shape=(1, len(items)), window_size=window_size)
    try:
        for col, (title, stl_path) in enumerate(items):
            plotter.subplot(0, col)
            mesh = pv.read(str(stl_path))
            plotter.add_mesh(mesh, color=_MESH_COLOR, pbr=True, metallic=0.1, roughness=0.4)
            plotter.add_light(pv.Light(position=(200, 200, 400), intensity=0.8))
            plotter.add_text(title, font_size=14)
            plotter.background_color = "white"
            _aim_head_on(plotter, mesh)
        plotter.screenshot(str(png_path))
    finally:
        plotter.close()


# --- shape building ----------------------------------------------------------

def _apply_overrides(raw: list[str], base):
    """Apply repeated ``--set field=value`` args, each coerced to the field's type."""
    field_types = {f.name: type(getattr(base, f.name)) for f in fields(base)}
    out = {}
    for item in raw:
        if "=" not in item:
            raise ValueError(f"--set must be field=value, got {item!r}")
        key, value = (part.strip() for part in item.split("=", 1))
        if key not in field_types:
            raise ValueError(f"Unknown {type(base).__name__} field: {key!r}")
        out[key] = field_types[key](value)
    return replace(base, **out) if out else base


def _build_gripper_stl(cfg: dict, overrides: list[str]) -> Path:
    """Assemble the gripper and export its STL into PREVIEW_DIR."""
    from geometry.assembly import assemble_model
    from geometry.io.export_mesh import model_to_stl, run_invariants
    from geometry.params import ModelParams, validate_params
    from geometry.quaternion import rotate_model_to_export_frame
    from _gripper_common import params_from_config

    params = _apply_overrides(overrides, params_from_config(cfg, ModelParams()))
    validate_params(params)
    result = assemble_model(params)
    run_invariants(result)

    stl_path = PREVIEW_DIR / "gripper_preview.stl"
    model_to_stl(rotate_model_to_export_frame(result), params, stl_path)
    return stl_path


def _build_leg_stl(cfg: dict, overrides: list[str]) -> Path:
    """Build the leg centreline and export its STL into PREVIEW_DIR.

    Raises RuntimeError (after writing a debug plot) if the centreline folds
    on itself — that shape is not manufacturable.
    """
    from geometry.leg_geometry import build_leg
    from geometry.leg_params import LegParams, validate_params
    from _gripper_common import params_from_config

    params = _apply_overrides(overrides, params_from_config(cfg, LegParams()))
    validate_params(params)
    centerline = build_leg(params)

    if not centerline.is_valid():
        debug_png = PREVIEW_DIR / "leg_preview_debug.png"
        _plot_leg_debug(centerline, debug_png)
        raise RuntimeError(
            "Leg centreline is self-intersecting — unfeasible with these params. "
            f"Debug plot: {debug_png}"
        )

    stl_path = PREVIEW_DIR / "leg_preview.stl"
    if not centerline.export_stl(stl_path):
        raise RuntimeError("Leg STL export failed.")
    return stl_path


def _plot_leg_debug(centerline, png_path: Path) -> None:
    """Draw the raw (u, v) centreline and its swept edges to a PNG so a
    folded shape can be inspected without a CAD viewer."""
    import matplotlib.pyplot as plt

    pts, tans = centerline._sample()
    half = centerline.thickness / 2.0
    edges = [
        [(px - ty * half * s, py + tx * half * s)
         for (px, py), (tx, ty) in zip(pts, tans)]
        for s in (1, -1)
    ]

    fig, ax = plt.subplots(figsize=(6, 8))
    ax.plot([p[0] for p in pts], [p[1] for p in pts], "-o", color=_MESH_COLOR,
            markersize=2, linewidth=1.5, label="centreline")
    for edge, style in zip(edges, ("--", ":")):
        ax.plot([p[0] for p in edge], [p[1] for p in edge], style,
                color="#d94a4a", linewidth=1)
    ax.set_aspect("equal")
    ax.set_xlabel("u (outward)")
    ax.set_ylabel("v (up)")
    ax.set_title("Leg centreline — self-intersecting")
    ax.legend()
    fig.tight_layout()
    fig.savefig(str(png_path), dpi=150)
    plt.close(fig)


# --- CLI --------------------------------------------------------------------

def main() -> None:
    from _gripper_common import ensure_cadquery_runtime, load_jsonc

    parser = argparse.ArgumentParser(
        description="Render the current config's gripper and/or leg to a PNG."
    )
    parser.add_argument("--part", choices=("gripper", "leg", "both"), default="both")
    parser.add_argument(
        "--config", default=str(_LAB_ROOT / "config" / "lab_config.jsonc"),
        help="Base JSONC config (missing fields fall back to the dataclass defaults).",
    )
    parser.add_argument(
        "--set", dest="overrides", action="append", default=[], metavar="field=value",
        help="Override one parameter, e.g. --set leg_p1_dist=140. Repeatable.",
    )
    args = parser.parse_args()

    ensure_cadquery_runtime()
    cfg = load_jsonc(Path(args.config))
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

    rendered: list[tuple[str, Path]] = []
    if args.part in ("gripper", "both"):
        rendered.append(("Gripper", _build_gripper_stl(cfg, args.overrides)))
    if args.part in ("leg", "both"):
        rendered.append(("Leg", _build_leg_stl(cfg, args.overrides)))

    if len(rendered) == 1:
        title, stl = rendered[0]
        png = PREVIEW_DIR / f"{title.lower()}_preview.png"
        render_mesh_png(stl, png, title=title)
    else:
        png = PREVIEW_DIR / "preview.png"
        render_mesh_grid(rendered, png)

    print(f"PNG: {png}")


if __name__ == "__main__":
    main()
