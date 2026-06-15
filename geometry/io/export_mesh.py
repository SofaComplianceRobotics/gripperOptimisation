"""Mesh export functions for STL, VTK, and collision mesh formats.

Handles conversion of CadQuery models to standard mesh formats using Gmsh
with configurable meshing parameters.
"""

import os
import tempfile
from pathlib import Path

import cadquery as cq
from OCP.BRepTools import BRepTools

from geometry.params import ModelParams

RETURN_GMSH_WARNING = 1  # 0=silent, 1=errors only, 5=full


def run_invariants(model: cq.Workplane) -> None:
    """
    Run basic geometry sanity checks.

    Args:
        model: Built model.

    Raises:
        ValueError: If model is invalid.
    """
    solid = model.val()
    if solid.isNull():
        raise ValueError("Model is null.")
    if solid.Volume() <= 0:
        raise ValueError("Model volume must be > 0.")


def _export_with_gmsh(
    model: cq.Workplane,
    p: ModelParams,
    output_path: Path,
    *,
    export_3d: bool,
) -> None:
    """
    Export the model mesh through a shared Gmsh pipeline.
    """
    import gmsh

    fd, tmp_name = tempfile.mkstemp(suffix=".brep")
    os.close(fd)
    brep_path = Path(tmp_name)
    initialized = False

    try:
        BRepTools.Write_s(model.val().wrapped, str(brep_path))

        gmsh.initialize()
        gmsh.option.setNumber("General.Verbosity", RETURN_GMSH_WARNING)
        initialized = True

        gmsh.model.occ.importShapes(str(brep_path))

        try:
            gmsh.model.occ.removeAllDuplicates()
        except Exception:
            # Some OCC imports do not need or support duplicate cleanup.
            pass

        gmsh.model.occ.synchronize()

        mesh_size_max = p.mesh_size_max_vtk if export_3d else p.mesh_size_max_stl
        mesh_size_min = p.mesh_size_min_vtk if export_3d else p.mesh_size_min_stl

        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("Mesh.CharacteristicLengthMax", mesh_size_max)
        gmsh.option.setNumber("Mesh.CharacteristicLengthMin", mesh_size_min)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", p.mesh_size_from_curvature)

        # When curvature sizing is disabled, also disable other local sizing
        # sources to avoid dense mesh patches on rounded regions.
        if p.mesh_size_from_curvature <= 0:
            gmsh.option.setNumber("Mesh.CharacteristicLengthExtendFromBoundary", 0)
            gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
            gmsh.option.setNumber("Mesh.MeshSizeFromParametricPoints", 0)
            try:
                gmsh.option.setNumber("Mesh.CharacteristicLengthFromCurvature", 0)
            except Exception:
                pass

            uniform_tag = gmsh.model.mesh.field.add("MathEval")
            gmsh.model.mesh.field.setString(uniform_tag, "F", str(mesh_size_max))
            gmsh.model.mesh.field.setAsBackgroundMesh(uniform_tag)

        gmsh.option.setNumber("Mesh.Algorithm", 6)

        if export_3d:
            gmsh.option.setNumber("Mesh.Algorithm3D", 10)  # HXT tetrahedra.
            # HXT only supports triangles; do not recombine to quads.
            gmsh.option.setNumber("Mesh.RecombineAll", 0)
            gmsh.option.setNumber("Mesh.Binary", 0)  # ASCII VTK for compatibility.
            gmsh.model.mesh.generate(2)
            gmsh.model.mesh.generate(3)
        else:
            gmsh.option.setNumber("Mesh.AngleSmoothNormals", p.mesh_angle_smooth)
            # Recombine triangles to quads for more efficient surface mesh.
            gmsh.option.setNumber("Mesh.RecombineAll", 0)
            # Aggressive smoothing to blend stepped geometry into smooth slopes
            gmsh.option.setNumber("Mesh.Smoothing", 10)  # Multiple smoothing passes
            gmsh.option.setNumber(
                "Mesh.Optimize", 2
            )  # Level 2 optimization (more aggressive)
            gmsh.option.setNumber("Mesh.OptimizeNetgen", 1)  # Additional Netgen pass
            gmsh.option.setNumber("Mesh.Binary", 1)
            gmsh.model.mesh.generate(2)

        gmsh.write(str(output_path))

    finally:
        if initialized:
            gmsh.finalize()
        if brep_path.exists():
            brep_path.unlink()


def model_to_stl(model: cq.Workplane, p: ModelParams, output_path: Path) -> None:
    """Convert a CadQuery workplane to STL using Gmsh.

    Args:
        model: Model to mesh.
        p: Meshing parameters.
        output_path: Destination STL path.
    """
    _export_with_gmsh(model, p, output_path, export_3d=False)


def model_to_vtk(model: cq.Workplane, p: ModelParams, output_path: Path) -> None:
    """Convert a CadQuery workplane to VTK using Gmsh.

    Args:
        model: Model to mesh.
        p: Meshing parameters.
        output_path: Destination VTK path.
    """
    _export_with_gmsh(model, p, output_path, export_3d=True)


def model_to_stl_collision(
    model: cq.Workplane, p: ModelParams, output_path: Path
) -> None:
    """
    Export a coarse collision STL with all curvature-based refinement disabled.

    Uses an explicit collision mesh size from params (mesh_collision_size),
    ignoring curvature-driven sources so the resulting mesh remains coarse
    and predictable.

    Args:
        model: Model to mesh (typically fingers only).
        p: Meshing parameters. mesh_collision_size controls the target element
            size for this collision export.
        output_path: Destination STL path.
    """
    import gmsh

    fd, tmp_name = tempfile.mkstemp(suffix=".brep")
    os.close(fd)
    brep_path = Path(tmp_name)
    initialized = False

    try:
        BRepTools.Write_s(model.val().wrapped, str(brep_path))

        gmsh.initialize()
        gmsh.option.setNumber("General.Verbosity", RETURN_GMSH_WARNING)
        initialized = True

        gmsh.model.occ.importShapes(str(brep_path))

        try:
            gmsh.model.occ.removeAllDuplicates()
        except Exception:
            # Some OCC imports do not need or support duplicate cleanup.
            pass

        gmsh.model.occ.synchronize()

        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("Mesh.CharacteristicLengthExtendFromBoundary", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromParametricPoints", 0)

        # Force a uniform collision mesh size from a single explicit parameter.
        tag = gmsh.model.mesh.field.add("MathEval")
        gmsh.model.mesh.field.setString(tag, "F", str(p.mesh_collision_size))
        gmsh.model.mesh.field.setAsBackgroundMesh(tag)

        gmsh.option.setNumber("Mesh.CharacteristicLengthMax", p.mesh_collision_size)
        gmsh.option.setNumber("Mesh.CharacteristicLengthMin", p.mesh_collision_size)

        gmsh.option.setNumber("Mesh.MeshSizeFromCurvature", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
        gmsh.option.setNumber("Mesh.MeshSizeFromParametricPoints", 0)
        gmsh.option.setNumber("Mesh.RecombineAll", 0)

        gmsh.option.setNumber("Mesh.Algorithm", 6)
        gmsh.option.setNumber("Mesh.Optimize", 1)
        gmsh.option.setNumber("Mesh.Smoothing", 1)
        gmsh.option.setNumber("Mesh.Binary", 1)

        gmsh.model.mesh.generate(2)

        gmsh.write(str(output_path))

    finally:
        if initialized:
            gmsh.finalize()
        if brep_path.exists():
            brep_path.unlink()
