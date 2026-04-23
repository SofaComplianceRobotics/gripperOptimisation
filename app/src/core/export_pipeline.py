"""
Export Pipeline - Generates STL/VTK/JSON meshes from gripper parameters.

Can be called directly via run_export(params) or used as CLI entry point.
"""

import logging
import shutil
import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from core.assembly import assemble_model
from core.gripper_parts import make_pincer_pair_world_collision
from core.io_utils import (
    model_to_stl_collision,
    export_leg_attachment_json,
    make_versioned_export_path,
    model_to_stl,
    model_to_vtk,
    rotate_model_to_export_frame,
    run_invariants,
)
from core.params import ModelParams, validate_params

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")


def run_export(params: ModelParams, secondary_dir: Path | None = None) -> Path:
    """
    Run the export pipeline with given parameters.

    Inputs:
        params (ModelParams): Model configuration object.
        secondary_dir (Path | None): Optional directory to copy exported files to.
                                      If None, files are only saved to the exports/ directory.

    Returns:
        Path: Path to the generated STL file.

    Raises:
        RuntimeError: If validation or assembly fails.
    """

    # ─────────────────────────────────────────────
    # Export Pipeline
    # ─────────────────────────────────────────────

    t_step = 0.0
    validate_params(params)

    t_step = 0.0
    result = assemble_model(params)

    t_step = 0.0
    run_invariants(result)

    stl_path = None
    if params.mesh_enabled:
        t_step = 0.0
        mesh_model = rotate_model_to_export_frame(result)

        stl_path = make_versioned_export_path(params, "stl")
        json_path = stl_path.with_suffix(".json")
        vtk_path = stl_path.with_suffix(".vtk")

        t_step = 0.0
        model_to_stl(mesh_model, params, stl_path)

        t_step = 0.0
        export_leg_attachment_json(params, json_path)

        t_step = 0.0
        model_to_vtk(mesh_model, params, vtk_path)

        # Export coarse collision STL (fingers only)
        collision_stl_path = stl_path.parent / "new_gripper_collision.stl"
        t_step = 0.0
        pincers = make_pincer_pair_world_collision(params)

        t_step = 0.0
        pincers_export = rotate_model_to_export_frame(pincers)

        t_step = 0.0
        model_to_stl_collision(pincers_export, params, collision_stl_path)

        # Copy to secondary directory if provided
        if secondary_dir:
            t_step = 0.0
            secondary_dir.mkdir(parents=True, exist_ok=True)
            files_to_copy = [stl_path, json_path, collision_stl_path]
            if vtk_path.exists():
                files_to_copy.append(vtk_path)

            for src_path in files_to_copy:
                shutil.copy2(src_path, secondary_dir / src_path.name)

        if params.mesh_show_viewer:
            import gmsh

            gmsh.initialize()
            gmsh.merge(str(stl_path))
            gmsh.fltk.run()
            gmsh.finalize()

    return stl_path


def main() -> None:
    """CLI entry point that creates params and runs export."""
    params = ModelParams()
    run_export(params)


if __name__ == "__main__":
    main()
