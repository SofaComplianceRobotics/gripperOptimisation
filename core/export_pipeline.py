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
from core.io.export_mesh import (
    model_to_stl_collision,
    model_to_stl,
    model_to_vtk,
    run_invariants,
)
from core.io.export_json import export_leg_attachment_json
from core.io.paths import make_versioned_export_path
from core.transforms.quaternion import rotate_model_to_export_frame
from core.params import ModelParams, validate_params

logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")


def run_export(
    params: ModelParams, secondary_dir: Path | None = None, fine: bool = False
) -> Path:
    """Run the full export pipeline for a gripper design.

    Args:
        params: Model configuration object.
        secondary_dir: Optional directory to copy exported files to. If None,
            files are only saved to the exports/ directory.
        fine: When True, only the main STL is generated (no VTK, no collision
            STL, no JSON) — intended for 3D printing exports.

    Returns:
        Path to the generated STL file.

    Raises:
        RuntimeError: If validation or assembly fails.
    """

    validate_params(params)
    result = assemble_model(params)
    run_invariants(result)

    stl_path = None
    if params.mesh_enabled:
        mesh_model = rotate_model_to_export_frame(result)

        stl_path = make_versioned_export_path(params, "stl")

        model_to_stl(mesh_model, params, stl_path)

        if not fine:
            json_path = stl_path.with_suffix(".json")
            vtk_path = stl_path.with_suffix(".vtk")

            export_leg_attachment_json(params, json_path)
            model_to_vtk(mesh_model, params, vtk_path)

            # Collision STL uses only the distal finger fraction for a coarser mesh.
            collision_stl_path = stl_path.parent / f"{params.export_stem}_collision.stl"
            pincers = make_pincer_pair_world_collision(params)
            pincers_export = rotate_model_to_export_frame(pincers)
            model_to_stl_collision(pincers_export, params, collision_stl_path)

        if secondary_dir:
            secondary_dir.mkdir(parents=True, exist_ok=True)
            files_to_copy = [stl_path]
            if not fine:
                files_to_copy += [json_path, collision_stl_path]
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
    """Run the export pipeline with default ModelParams."""
    params = ModelParams()
    run_export(params)


if __name__ == "__main__":
    main()
