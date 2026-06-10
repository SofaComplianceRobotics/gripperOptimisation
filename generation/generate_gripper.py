"""
Lab Gripper Optimisation - UI Generation Entrypoint.

Reads parameters from lab_config.jsonc and exports STL/VTK/JSON.
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
from names import CENTERPARTS_DIRNAME

_START_TS = time.perf_counter()
ensure_cadquery_runtime()

from geometry.export_pipeline import run_export  # noqa: E402
from geometry.params import ModelParams  # noqa: E402


def main() -> None:
    """Read parameters from lab_config.jsonc and run the mesh export pipeline.

    This function parses CLI arguments, loads the JSONC configuration, builds
    model parameters and runs the export pipeline producing STL/JSON/VTK files.
    """
    parser = argparse.ArgumentParser(
        description="Generate gripper meshes from a JSONC config."
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
    params = params_from_config(cfg, ModelParams())

    secondary_dir = LAB_ROOT.parent.parent / "data" / "meshes" / CENTERPARTS_DIRNAME

    stl_path = run_export(params, secondary_dir=secondary_dir)
    if stl_path is None:
        raise RuntimeError("Mesh export did not produce an STL path.")

    for path in (stl_path, stl_path.with_suffix(".json"), stl_path.with_suffix(".vtk")):
        if path.exists():
            print(f"Exported: {path}")

    print(f"Total export time: {time.perf_counter() - _START_TS:.3f}s")


if __name__ == "__main__":
    main()
