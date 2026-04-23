"""
I/O Utilities - Export gripper models to STL, VTK, and JSON formats.

Handles serialization of CadQuery models to standard mesh and configuration
formats for simulation and visualization.
"""

import os
import tempfile
import json
import math
import sys
from pathlib import Path

import cadquery as cq
from OCP.BRepTools import BRepTools

SRC_ROOT = Path(__file__).resolve().parents[1]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from core.params import ModelParams

RETURN_GMSH_WARNING = 1  # 0=silent, 1=errors only, 5=full
CORE_ROOT = Path(__file__).resolve().parent
APP_ROOT = CORE_ROOT.parent.parent
LAB_ROOT = APP_ROOT.parent


def _axis_angle_to_quat(
    axis: tuple[float, float, float], angle_deg: float
) -> tuple[float, float, float, float]:
    """
    Build a normalized quaternion (x, y, z, w) from axis-angle.
    """
    ax, ay, az = axis
    norm = math.sqrt((ax * ax) + (ay * ay) + (az * az))
    if norm <= 0.0:
        return (0.0, 0.0, 0.0, 1.0)

    ax /= norm
    ay /= norm
    az /= norm

    half = math.radians(angle_deg) / 2.0
    s = math.sin(half)
    c = math.cos(half)
    return (ax * s, ay * s, az * s, c)


def _quat_mul(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """
    Hamilton product of quaternions in (x, y, z, w) format.
    """
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        (aw * bx) + (ax * bw) + (ay * bz) - (az * by),
        (aw * by) - (ax * bz) + (ay * bw) + (az * bx),
        (aw * bz) + (ax * by) - (ay * bx) + (az * bw),
        (aw * bw) - (ax * bx) - (ay * by) - (az * bz),
    )


def _normalize_quat(
    q: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """
    Normalize quaternion to unit length.
    """
    x, y, z, w = q
    norm = math.sqrt((x * x) + (y * y) + (z * z) + (w * w))
    if norm <= 0.0:
        return (0.0, 0.0, 0.0, 1.0)
    return (x / norm, y / norm, z / norm, w / norm)


def _quat_conjugate(
    q: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """
    Return the quaternion conjugate.
    """
    x, y, z, w = q
    return (-x, -y, -z, w)


def _quat_rotate_vector(
    q: tuple[float, float, float, float],
    v: tuple[float, float, float],
) -> tuple[float, float, float]:
    """
    Rotate a 3D vector by a unit quaternion.
    """
    vx, vy, vz = v
    v_quat = (vx, vy, vz, 0.0)
    rotated = _quat_mul(_quat_mul(q, v_quat), _quat_conjugate(q))
    return (rotated[0], rotated[1], rotated[2])


def _export_frame_quat() -> tuple[float, float, float, float]:
    """
    Return the mesh export frame rotation from CadQuery Z-up to SOFA frame.
    """
    qx = _axis_angle_to_quat((1.0, 0.0, 0.0), -90.0)
    qy = _axis_angle_to_quat((0.0, 1.0, 0.0), 90.0)
    return _normalize_quat(_quat_mul(qy, qx))


def _leg_attachment_pose(
    p: ModelParams, angle_deg: float, leg_index: int = 0
) -> list[float]:
    """
    Return [x, y, z, qx, qy, qz, qw] for one leg-attachment anchor.

    Position is the base-center of the leg attachment after placement.
    Orientation matches the leg attachment frame after Z rotation and tilt.

    Inputs:
        p (ModelParams): Model parameters.
        angle_deg (float): Placement angle in degrees.
        leg_index (int): Leg index (0-3); applies q2 rotation leg_index times.

    Returns:
        list[float]: [x, y, z, qx, qy, qz, qw] pose for one attachment.
    """
    placement_radius = p.cylinder_radius - p.leg_attachement_inward_offset
    a = math.radians(angle_deg)

    x = placement_radius * math.cos(a)
    y = placement_radius * math.sin(a)
    z = p.cylinder_height + p.leg_attachement_lift

    # Exported mesh files are already rotated into SOFA frame in export_pipeline.py.
    # Rotate each attachment pose into that same local frame so anchors lie on the mesh.
    q_export = _export_frame_quat()
    x, y, z = _quat_rotate_vector(q_export, (x, y, z))

    # Set orientation: 90-degree rotation around Z axis
    q1 = _axis_angle_to_quat((0.0, 0.0, 1.0), -90.0)
    q3 = _axis_angle_to_quat((1.0, 0.0, 0.0), 90.0)
    q2 = _axis_angle_to_quat((0.0, 1.0, 0.0), 90.0)

    # Apply q2 rotation leg_index times
    q = _normalize_quat(_quat_mul(q1, q3))
    for _ in range(leg_index):
        q = _normalize_quat(_quat_mul(q2, q))

    # Apply tilt angle rotation (before per-leg tweaks)
    a = math.radians(angle_deg)

    # Legs 0 and 2 use tangent axis, legs 1 and 3 use radial axis
    if leg_index in (1, 3):
        # Radial axis for side legs
        tilt_axis_x = math.cos(a)
        tilt_axis_y = math.sin(a)
        # Leg 1 negative, leg 3 positive
        tilt_angle = (
            -p.leg_attachement_tilt_angle
            if leg_index == 1
            else p.leg_attachement_tilt_angle
        )
    else:
        # Tangent axis for front/back legs
        tilt_axis_x = -math.sin(a)
        tilt_axis_y = math.cos(a)
        # Legs 0 and 2 have opposite directions
        tilt_angle = (
            p.leg_attachement_tilt_angle
            if leg_index == 0
            else -p.leg_attachement_tilt_angle
        )

    tilt_axis_z = 0.0
    q_tilt = _axis_angle_to_quat((tilt_axis_x, tilt_axis_y, tilt_axis_z), tilt_angle)
    q = _normalize_quat(_quat_mul(q, q_tilt))

    # Apply leg-specific Y-axis rotation (after tilt)
    y_rotations = {0: -90.0, 1: 90.0, 2: -90.0, 3: 90.0}
    q4 = _axis_angle_to_quat((0.0, 1.0, 0.0), y_rotations[leg_index])
    q = _normalize_quat(_quat_mul(q4, q))

    return [x, y, z, q[0], q[1], q[2], q[3]]


def rotate_model_to_export_frame(model: cq.Workplane) -> cq.Workplane:
    """
    Rotate model from CadQuery Z-up into the mesh export frame.
    """
    return model.rotate((0, 0, 0), (1, 0, 0), -90).rotate((0, 0, 0), (0, 1, 0), 90)


def export_leg_attachment_json(p: ModelParams, output_path: Path) -> None:
    """
    Export leg attachment anchors and orientations in JSON format.

    Inputs:
        p (ModelParams): Model parameters.
        output_path (Path): Destination JSON path.

    Returns:
        None
    """
    payload = {
        "initialPosition": [[0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]],
        "attachPositionInLocalCoord": [
            _leg_attachment_pose(p, angle_deg, leg_index=leg_idx)
            for leg_idx, angle_deg in enumerate(
                (180.0, 270.0, 0.0, 90.0)
            )  # CCW order starting from +Y
        ],
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def make_versioned_export_path(p: ModelParams, extension: str) -> Path:
    """
    Build a fixed export path inside the configured export directory.

    Inputs:
        p (ModelParams): Model parameters.
        extension (str): File extension, with or without leading dot.

    Returns:
        Path: Full output path using the base filename new_gripper.
    """
    out_dir = LAB_ROOT / p.export_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    ext = extension.lstrip(".")
    return out_dir / f"new_gripper.{ext}"


def run_invariants(model: cq.Workplane) -> None:
    """
    Run basic geometry sanity checks.

    Inputs:
        model (cadquery.Workplane): Built model.

    Returns:
        None

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

        # Stable global default for surface mesh generation.
        gmsh.option.setNumber("Mesh.Algorithm", 6)
        # 2D mesh algorithm (1: MeshAdapt, 2: Automatic, 3: Initial mesh only, 5: Delaunay, 6: Frontal-Delaunay, 7: BAMG, 8: Frontal-Delaunay for Quads, 9: Packing of Parallelograms, 11: Quasi-structured Quad)

        if export_3d:
            gmsh.option.setNumber("Mesh.Algorithm3D", 10)  # HXT tetrahedra.
            # 3D mesh algorithm (1: Delaunay, 3: Initial mesh only, 4: Frontal, 7: MMG3D, 9: R-tree, 10: HXT)
            gmsh.option.setNumber("Mesh.RecombineAll", 0)
            gmsh.option.setNumber("Mesh.Binary", 0)  # ASCII VTK for compatibility.
            gmsh.model.mesh.generate(2)
            gmsh.model.mesh.generate(3)
        else:
            gmsh.option.setNumber("Mesh.AngleSmoothNormals", p.mesh_angle_smooth)
            # Keep STL as pure triangles for robustness; quad recombination can
            # create invalid facets on extreme coarse meshes.
            gmsh.option.setNumber("Mesh.RecombineAll", 0)
            gmsh.option.setNumber("Mesh.Smoothing", 1)
            gmsh.option.setNumber("Mesh.Optimize", 1)
            gmsh.option.setNumber("Mesh.Binary", 1)
            gmsh.model.mesh.generate(2)

        gmsh.write(str(output_path))

    finally:
        if initialized:
            gmsh.finalize()
        if brep_path.exists():
            brep_path.unlink()


def model_to_stl(model: cq.Workplane, p: ModelParams, output_path: Path) -> None:
    """
    Convert a CadQuery workplane to STL using Gmsh.

    Inputs:
        model (cadquery.Workplane): Model to mesh.
        p (ModelParams): Meshing parameters.
        output_path (Path): Destination STL path.

    Returns:
        None
    """
    _export_with_gmsh(model, p, output_path, export_3d=False)


def model_to_vtk(model: cq.Workplane, p: ModelParams, output_path: Path) -> None:
    """
    Convert a CadQuery workplane to VTK using Gmsh.

    Inputs:
        model (cadquery.Workplane): Model to mesh.
        p (ModelParams): Meshing parameters.
        output_path (Path): Destination VTK path.

    Returns:
        None
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

    Inputs:
        model (cadquery.Workplane): Model to mesh (typically fingers only).
        p (ModelParams): Meshing parameters. mesh_collision_size controls
            the target element size for this collision export.
        output_path (Path): Destination STL path.

    Returns:
        None
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

        # Disable all curvature-based refinement
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
