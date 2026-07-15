"""
Lab Leg Generation - UI/optimizer entrypoint.

Reads leg parameters from lab_config.jsonc and exports the leg's
positions (.txt) and visual mesh (.stl) into data/meshes/legs, in the
format parts.leg.Leg (the EmioLabs SOFA prefab) expects.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from _gripper_common import (
    LAB_ROOT,
    ensure_cadquery_runtime,
    load_jsonc,
    params_from_config,
)
from names import LEGS_DIRNAME

_START_TS = time.perf_counter()
ensure_cadquery_runtime()

from geometry.leg_geometry import build_leg  # noqa: E402
from geometry.leg_params import LegParams, validate_params  # noqa: E402


def main() -> None:
    """Read leg parameters from lab_config.jsonc and export positions + STL.

    This function parses CLI arguments, loads the JSONC configuration,
    builds LegParams and runs the leg export pipeline. --name overrides the
    output stem so parallel optimizer trials never clash on the same files.
    """
    parser = argparse.ArgumentParser(
        description="Generate a leg's positions/mesh from a JSONC config."
    )
    parser.add_argument(
        "--config",
        type=str,
        default=str(LAB_ROOT / "config" / "lab_config.jsonc"),
        help="Path to config JSONC file. Defaults to config/lab_config.jsonc in the lab root.",
    )
    parser.add_argument(
        "--name",
        type=str,
        default=None,
        help="Output file stem, overriding LegParams.export_stem (used for "
        "trial-unique names so parallel SOFA processes never clash).",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    cfg = load_jsonc(config_path)
    params = params_from_config(cfg, LegParams())
    if args.name is not None:
        from dataclasses import replace

        params = replace(params, export_stem=args.name)

    validate_params(params)
    centerline = build_leg(params)
    if not centerline.is_valid():
        raise RuntimeError("Leg centerline is self-intersecting; shape is unfeasible.")

    out_dir = LAB_ROOT.parent.parent / "data" / "meshes" / LEGS_DIRNAME
    out_dir.mkdir(parents=True, exist_ok=True)
    txt_path = out_dir / f"{params.export_stem}.txt"
    stl_path = out_dir / f"{params.export_stem}.stl"

    centerline.export_positions(txt_path)
    if not centerline.export_stl(stl_path):
        raise RuntimeError("Leg STL export failed.")

    for path in (txt_path, stl_path):
        print(f"Exported: {path}")

    print(f"Total export time: {time.perf_counter() - _START_TS:.3f}s")


if __name__ == "__main__":
    main()
