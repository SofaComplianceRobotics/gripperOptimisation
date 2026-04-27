"""
Parameters - Data classes for gripper model configuration and design parameters.

Defines the ModelParams dataclass that holds all tunable gripper design parameters
used throughout the generation, assembly, and export pipeline.
"""

from dataclasses import dataclass

# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────
EPS_NORMAL = 1e-6
EPS_LEN = 1e-6
PROFILE_EXTRUDE_MARGIN = 2.0


@dataclass(frozen=True)
class PincerSplinePoint:
    """One cubic-bezier anchor point with optional incoming and outgoing handles.

    Attributes:
        p: Anchor point in XY (mm).
        h_in: Incoming Bezier handle, absolute XY. None for the first point.
        h_out: Outgoing Bezier handle, absolute XY. None for the last point.
    """

    p: tuple[float, float]
    h_in: tuple[float, float] | None
    h_out: tuple[float, float] | None


@dataclass(frozen=True)
class ModelParams:
    """Immutable configuration for one gripper design.

    Groups all tunable shape, mesh, and export parameters in one place so
    every stage of the pipeline (assembly, export, optimization) pulls from
    the same source of truth.
    """

    # Ring
    cylinder_radius: float = 26.5
    cylinder_height: float = 4.0
    cylinder_hole_thickness: float = 3.0

    # Leg attachment
    leg_hole_length: float = 10.0
    leg_hole_width: float = 5.0
    leg_attachment_height: float = 15.0
    leg_wall_thickness: float = 1.5

    # Detailing
    slit_width: float = 0.1
    trapezoid_start_from_top: float = 3.5

    # Assembly
    leg_attachement_inward_offset: float = 3.0
    leg_attachement_tilt_angle: float = -5.0
    leg_attachement_lift: float = 2.5
    leg_attachement_drop_overlap: float = 0.15

    # Pincers
    pincer_profile_width: float = 5.0
    pincer_profile_height: float = 10.0
    pincer_profile_samples: int = 4
    pincer_round_cap_segments: int = 3
    pincer_path_scale: float = 0.20
    pincer_tilt_y_deg: float = 90.0
    pincer_round_ends: bool = True
    pincer_points: tuple[PincerSplinePoint, ...] = (
        PincerSplinePoint(
            p=(0.0, 0.0),
            h_in=None,
            h_out=(24.0, 18.0),
        ),
        PincerSplinePoint(
            p=(150.0, 70.0),
            h_in=(118.0, 24.0),
            h_out=None,
        ),
    )

    # Mesh
    mesh_enabled: bool = True
    mesh_size_max_stl: float = 35
    mesh_size_min_stl: float = 15
    mesh_size_max_vtk: float = 35
    mesh_size_min_vtk: float = 10
    mesh_collision_size: float = 90.0
    mesh_collision_tail_fraction: float = 1.0 / 2.0
    mesh_angle_smooth: float = 20.0
    mesh_size_from_curvature: int = 12
    mesh_show_viewer: bool = True

    # Export
    export_dir: str = "runtime/exports"
    export_stem: str = "new_gripper"


def validate_params(p: ModelParams) -> None:
    """Validate all model parameters before build.

    Args:
        p: Parameter set to validate.

    Raises:
        ValueError: If any parameter is invalid or geometrically infeasible.
    """
    positive_fields = {
        "cylinder_radius": p.cylinder_radius,
        "cylinder_height": p.cylinder_height,
        "cylinder_hole_thickness": p.cylinder_hole_thickness,
        "leg_hole_length": p.leg_hole_length,
        "leg_hole_width": p.leg_hole_width,
        "leg_attachment_height": p.leg_attachment_height,
        "leg_wall_thickness": p.leg_wall_thickness,
    }

    for name, value in positive_fields.items():
        if value <= 0:
            raise ValueError(f"{name} must be > 0. Got {value}.")

    if p.slit_width < 0:
        raise ValueError(f"slit_width must be >= 0. Got {p.slit_width}.")
    if p.leg_attachement_inward_offset < 0:
        raise ValueError(
            f"leg_attachement_inward_offset must be >= 0. Got {p.leg_attachement_inward_offset}."
        )
    if p.leg_attachement_drop_overlap < 0:
        raise ValueError(
            f"leg_attachement_drop_overlap must be >= 0. Got {p.leg_attachement_drop_overlap}."
        )
    if p.trapezoid_start_from_top < 0:
        raise ValueError(
            f"trapezoid_start_from_top must be >= 0. Got {p.trapezoid_start_from_top}."
        )
    if p.cylinder_hole_thickness >= 2.0 * p.cylinder_radius:
        raise ValueError(
            "cylinder_hole_thickness is too large for cylinder_radius; "
            "inner radius would be <= 0."
        )

    thickened_thickness = p.leg_hole_width + (2.0 * p.leg_wall_thickness)
    sector_inner_r = p.cylinder_radius - (thickened_thickness / 2.0)
    target_center_distance = p.leg_hole_length + (2.0 * p.leg_wall_thickness)

    if sector_inner_r <= 0:
        raise ValueError("Inner radius of thickened sector must be > 0.")
    if target_center_distance > 2.0 * sector_inner_r:
        raise ValueError(
            "Cannot satisfy thickened-sector distance constraint: "
            "target distance > inner diameter."
        )

    if p.pincer_profile_width <= 0:
        raise ValueError(
            f"pincer_profile_width must be > 0. Got {p.pincer_profile_width}."
        )
    if p.pincer_profile_height <= 0:
        raise ValueError(
            f"pincer_profile_height must be > 0. Got {p.pincer_profile_height}."
        )
    if p.pincer_path_scale <= 0:
        raise ValueError(f"pincer_path_scale must be > 0. Got {p.pincer_path_scale}.")
    if p.pincer_profile_samples < 4:
        raise ValueError(
            "pincer_profile_samples must be >= 4. " f"Got {p.pincer_profile_samples}."
        )
    if p.pincer_round_cap_segments < 2:
        raise ValueError(
            "pincer_round_cap_segments must be >= 2. "
            f"Got {p.pincer_round_cap_segments}."
        )
    if len(p.pincer_points) < 2:
        raise ValueError("pincer_points must contain at least 2 spline points.")

    for i, pt in enumerate(p.pincer_points):
        if i == 0 and pt.h_out is None:
            raise ValueError("First pincer spline point must define h_out.")
        if i == len(p.pincer_points) - 1 and pt.h_in is None:
            raise ValueError("Last pincer spline point must define h_in.")

    if p.mesh_enabled:
        if p.mesh_size_max_stl <= 0:
            raise ValueError(
                f"mesh_size_max_stl must be > 0. Got {p.mesh_size_max_stl}."
            )
        if p.mesh_size_min_stl <= 0:
            raise ValueError(
                f"mesh_size_min_stl must be > 0. Got {p.mesh_size_min_stl}."
            )
        if p.mesh_size_max_vtk <= 0:
            raise ValueError(
                f"mesh_size_max_vtk must be > 0. Got {p.mesh_size_max_vtk}."
            )
        if p.mesh_size_min_vtk <= 0:
            raise ValueError(
                f"mesh_size_min_vtk must be > 0. Got {p.mesh_size_min_vtk}."
            )
        if p.mesh_collision_size <= 0:
            raise ValueError(
                f"mesh_collision_size must be > 0. Got {p.mesh_collision_size}."
            )
        if not (0.0 < p.mesh_collision_tail_fraction <= 1.0):
            raise ValueError(
                "mesh_collision_tail_fraction must be in (0, 1]. "
                f"Got {p.mesh_collision_tail_fraction}."
            )
        if p.mesh_size_from_curvature < 0:
            raise ValueError(
                f"mesh_size_from_curvature must be >= 0. Got {p.mesh_size_from_curvature}."
            )
        if not (0.0 < p.mesh_angle_smooth < 90.0):
            raise ValueError(
                f"mesh_angle_smooth must be between 0 and 90 exclusive. "
                f"Got {p.mesh_angle_smooth}."
            )
