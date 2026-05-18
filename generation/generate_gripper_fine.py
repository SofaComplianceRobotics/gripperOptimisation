"""
Lab Gripper Optimisation - Fine Mesh Generation Entrypoint.

Same as generate_gripper.py but uses a much finer mesh suitable for real-life
3D printing. Output is saved as new_gripper_print.stl (separate from the
coarser simulation mesh new_gripper.stl).
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

_START_TS = time.perf_counter()
ensure_cadquery_runtime()

from core.export_pipeline import run_export  # noqa: E402
from core.params import ModelParams  # noqa: E402


def main() -> None:
    """Read parameters from lab_config.jsonc and run a fine-mesh export for printing."""
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
    params = params_from_config(cfg, ModelParams(), fine=True)

    secondary_dir = LAB_ROOT.parent.parent / "data" / "meshes" / "centerparts"

    stl_path = run_export(params, secondary_dir=secondary_dir, fine=True)
    if stl_path is None:
        raise RuntimeError("Mesh export did not produce an STL path.")

    if stl_path.exists():
        print(f"Exported: {stl_path}")

    elapsed = time.perf_counter() - _START_TS
    print(f"Total export time: {elapsed:.3f}s")
    print("Mesh settings: max=2.0mm, min=0.8mm (finer than simulation mesh — may take longer)")


if __name__ == "__main__":
    main()
