"""
Parameters - Data classes for gripper model configuration and design parameters.

Defines the ModelParams dataclass that holds all tunable gripper design parameters
used throughout the generation, assembly, and export pipeline.
"""

import math
from dataclasses import dataclass, field, fields

from names import GRIPPER_NAME

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
    cylinder_radius: float = field(
        default=26.5,
        metadata={"opt": {"type": "float", "min": 0, "max": 0}, "check": "positive"},
    )
    cylinder_hole_thickness: float = field(
        default=3.0,
        metadata={"opt": {"type": "float", "min": 0, "max": 0}, "check": "positive"},
    )
    cylinder_height_A: float = field(
        default=1.0,
        metadata={"opt": {"type": "float", "min": 0, "max": 0}, "check": "positive"},
    )
    cylinder_height_B: float = field(
        default=1.0,
        metadata={"opt": {"type": "float", "min": 0, "max": 0}, "check": "positive"},
    )
    cylinder_height_C: float = field(
        default=1.0,
        metadata={"opt": {"type": "float", "min": 0, "max": 0}, "check": "positive"},
    )
    cylinder_plateau_A_deg: float = field(
        default=0.0, metadata={"opt": {"type": "float", "min": 0, "max": 0}}
    )
    cylinder_plateau_B_deg: float = field(
        default=0.0, metadata={"opt": {"type": "float", "min": 0, "max": 0}}
    )
    # Effective max = 45 - max(plateau_A, plateau_B); clamped in the optimizer after sampling.
    cylinder_plateau_C_deg: float = field(
        default=0.0, metadata={"opt": {"type": "float", "min": 0, "max": 0}}
    )

    # Leg attachment
    leg_hole_length: float = field(default=10.0, metadata={"check": "positive"})
    leg_hole_width: float = field(default=5.0, metadata={"check": "positive"})
    leg_attachment_height: float = field(default=15.0, metadata={"check": "positive"})
    leg_wall_thickness: float = field(default=1.5, metadata={"check": "positive"})

    # Detailing
    slit_width: float = field(default=0.1, metadata={"check": "non_negative"})
    trapezoid_start_from_top: float = field(
        default=3.5, metadata={"check": "non_negative"}
    )

    # Assembly
    leg_attachement_inward_offset: float = field(
        default=3.0, metadata={"check": "non_negative"}
    )
    leg_attachement_tilt_angle: float = field(
        default=15.0, metadata={"opt": {"type": "float", "min": 0, "max": 30.0}}
    )
    leg_attachement_lift: float = 2.5
    leg_attachement_drop_overlap: float = field(
        default=0.15, metadata={"check": "non_negative"}
    )

    # Pincers
    pincer_profile_width: float = field(
        default=5.0,
        metadata={
            "opt": {"type": "float", "min": 0, "max": 0},
            "check": "positive",
        },
    )
    pincer_profile_height: float = field(
        default=10.0,
        metadata={
            "opt": {"type": "float", "min": 0, "max": 0},
            "check": "positive",
        },
    )
    pincer_profile_samples: int = field(default=4, metadata={"check": ("ge", 4)})
    pincer_round_cap_segments: int = field(default=3, metadata={"check": ("ge", 2)})
    pincer_path_scale: float = field(
        default=1.0,
        metadata={"opt": {"type": "float", "min": 0, "max": 0}, "check": "positive"},
    )
    pincer_tilt_y_deg: float = field(
        default=90.0, metadata={"opt": {"type": "float", "min": 0, "max": 0}}
    )
    pincer_round_ends: bool = field(
        default=True, metadata={"opt": {"type": "bool", "min": 0, "max": 0}}
    )
    # Bézier spline in polar form — absolute XY computed by pincer_points property
    p0_hout_dist: float = field(
        default=0.0, metadata={"opt": {"type": "float", "min": 0.0, "max": 32.0}}
    )
    p0_hout_angle_deg: float = field(
        default=0.0, metadata={"opt": {"type": "float", "min": -90.0, "max": 90.0}}
    )
    p1_dist: float = field(
        default=40.0, metadata={"opt": {"type": "float", "min": 36, "max": 48}}
    )
    p1_angle_deg: float = field(
        default=-40.0, metadata={"opt": {"type": "float", "min": -70.0, "max": 0}}
    )
    p1_hin_dist: float = field(
        default=0.0, metadata={"opt": {"type": "float", "min": 0.0, "max": 32.0}}
    )
    p1_hin_angle_deg: float = field(
        default=0.0, metadata={"opt": {"type": "float", "min": -10.0, "max": 260.0}}
    )

    def cylinder_height_at(self, theta_deg: float) -> float:
        """Return the ring height at a given angle (degrees)."""
        cps = [
            (0.0, self.cylinder_height_A, self.cylinder_plateau_A_deg),
            (45.0, self.cylinder_height_C, self.cylinder_plateau_C_deg),
            (90.0, self.cylinder_height_B, self.cylinder_plateau_B_deg),
            (135.0, self.cylinder_height_C, self.cylinder_plateau_C_deg),
            (180.0, self.cylinder_height_A, self.cylinder_plateau_A_deg),
            (225.0, self.cylinder_height_C, self.cylinder_plateau_C_deg),
            (270.0, self.cylinder_height_B, self.cylinder_plateau_B_deg),
            (315.0, self.cylinder_height_C, self.cylinder_plateau_C_deg),
        ]
        theta = theta_deg % 360.0
        gap = 45.0
        n = len(cps)
        for i in range(n):
            angle_i, height_i, plateau_i = cps[i]
            _, height_j, plateau_j = cps[(i + 1) % n]
            rel = (theta - angle_i) % 360.0
            if rel > gap + 1e-9:
                continue
            half_i = min(plateau_i / 2.0, gap / 2.0)
            half_j = min(plateau_j / 2.0, gap / 2.0)
            if half_i + half_j >= gap:
                t = rel / gap
                t_s = (1.0 - math.cos(math.pi * t)) / 2.0
                return height_i + t_s * (height_j - height_i)
            if rel <= half_i:
                return height_i
            transition_end = gap - half_j
            if rel >= transition_end:
                return height_j
            t = (rel - half_i) / (transition_end - half_i)
            t_s = (1.0 - math.cos(math.pi * t)) / 2.0
            return height_i + t_s * (height_j - height_i)
        return self.cylinder_height_A

    @property
    def cylinder_height(self) -> float:
        return max(
            self.cylinder_height_A, self.cylinder_height_B, self.cylinder_height_C
        )

    @property
    def pincer_points(self) -> tuple[PincerSplinePoint, ...]:
        p0_hout_x = self.p0_hout_dist * math.cos(math.radians(self.p0_hout_angle_deg))
        p0_hout_y = self.p0_hout_dist * math.sin(math.radians(self.p0_hout_angle_deg))
        p1_x = self.p1_dist * math.cos(math.radians(self.p1_angle_deg))
        p1_y = self.p1_dist * math.sin(math.radians(self.p1_angle_deg))
        p1_hin_x = p1_x + self.p1_hin_dist * math.cos(
            math.radians(self.p1_hin_angle_deg)
        )
        p1_hin_y = p1_y + self.p1_hin_dist * math.sin(
            math.radians(self.p1_hin_angle_deg)
        )
        return (
            PincerSplinePoint(p=(0.0, 0.0), h_in=None, h_out=(p0_hout_x, p0_hout_y)),
            PincerSplinePoint(p=(p1_x, p1_y), h_in=(p1_hin_x, p1_hin_y), h_out=None),
        )

    # Mesh — size/quality checks only apply when meshing is on (check_if).
    ring_ramp_samples: int = field(default=32, metadata={"check": ("ge", 8)})
    mesh_enabled: bool = True
    mesh_size_max_stl: float = field(
        default=45.0, metadata={"check": "positive", "check_if": "mesh_enabled"}
    )
    mesh_size_min_stl: float = field(
        default=15.0, metadata={"check": "positive", "check_if": "mesh_enabled"}
    )
    mesh_size_max_vtk: float = field(
        default=45.0, metadata={"check": "positive", "check_if": "mesh_enabled"}
    )
    mesh_size_min_vtk: float = field(
        default=10.0, metadata={"check": "positive", "check_if": "mesh_enabled"}
    )
    mesh_collision_size: float = field(
        default=90.0,
        metadata={
            "opt": {"type": "float", "min": 0, "max": 0},
            "check": "positive",
            "check_if": "mesh_enabled",
        },
    )
    mesh_collision_tail_fraction: float = field(
        default=1.0,
        metadata={"check": ("open_closed", 0.0, 1.0), "check_if": "mesh_enabled"},
    )
    mesh_angle_smooth: float = field(
        default=20.0,
        metadata={
            "opt": {"type": "float", "min": 0, "max": 0},
            "check": ("open_open", 0.0, 90.0),
            "check_if": "mesh_enabled",
        },
    )
    mesh_size_from_curvature: int = field(
        default=12,
        metadata={
            "opt": {"type": "int", "min": 0, "max": 0},
            "check": "non_negative",
            "check_if": "mesh_enabled",
        },
    )
    mesh_show_viewer: bool = False

    # Export
    export_dir: str = "runtime/exports"
    export_stem: str = GRIPPER_NAME


def param_specs(base: ModelParams | None = None) -> list[dict]:
    """Build parameter specs from ModelParams field metadata.

    One spec dict per field annotated with "opt" metadata. Consumers:
    the optimizer builds its search space from these, the dashboard
    renders the bounds tab from them.

    Fields with min == max == 0 are "frozen": listed, but consumers
    treat them as fixed at their default rather than searchable.

    Args:
        base: Instance providing default values. A fresh ModelParams()
            is used if None.

    Returns:
        List of dicts with keys: name, type, min, max, default.
    """
    if base is None:
        base = ModelParams()
    specs = []
    for f in fields(base):
        opt = f.metadata.get("opt")
        if opt is None:
            continue
        specs.append(
            {
                "name": f.name,
                "type": opt["type"],
                "min": opt["min"],
                "max": opt["max"],
                "default": getattr(base, f.name),
            }
        )
    return specs


def _apply_check(name: str, value, check) -> None:
    """Enforce one field's "check" metadata rule.

    Supported rules:
        "positive"               — value > 0
        "non_negative"           — value >= 0
        ("ge", n)                — value >= n
        ("open_closed", lo, hi)  — lo < value <= hi
        ("open_open", lo, hi)    — lo < value < hi

    Raises:
        ValueError: If the value violates the rule, or the rule is unknown.
    """
    if check == "positive":
        if value <= 0:
            raise ValueError(f"{name} must be > 0. Got {value}.")
    elif check == "non_negative":
        if value < 0:
            raise ValueError(f"{name} must be >= 0. Got {value}.")
    elif check[0] == "ge":
        if value < check[1]:
            raise ValueError(f"{name} must be >= {check[1]}. Got {value}.")
    elif check[0] == "open_closed":
        lo, hi = check[1], check[2]
        if not (lo < value <= hi):
            raise ValueError(f"{name} must be in ({lo}, {hi}]. Got {value}.")
    elif check[0] == "open_open":
        lo, hi = check[1], check[2]
        if not (lo < value < hi):
            raise ValueError(
                f"{name} must be between {lo} and {hi} exclusive. Got {value}."
            )
    else:
        raise ValueError(f"Unknown check rule {check!r} on field {name}.")


def validate_params(p: ModelParams) -> None:
    """Validate all model parameters before build.

    Per-field rules are declared as "check" metadata on each ModelParams
    field (optionally gated by "check_if") and enforced generically.
    Only cross-field geometric constraints are written out below.

    Args:
        p: Parameter set to validate.

    Raises:
        ValueError: If any parameter is invalid or geometrically infeasible.
    """
    for f in fields(p):
        check = f.metadata.get("check")
        if check is None:
            continue
        gate = f.metadata.get("check_if")
        if gate is not None and not getattr(p, gate):
            continue
        _apply_check(f.name, getattr(p, f.name), check)

    # ── Cross-field geometric constraints ──
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

    if len(p.pincer_points) < 2:
        raise ValueError("pincer_points must contain at least 2 spline points.")

    for i, pt in enumerate(p.pincer_points):
        if i == 0 and pt.h_out is None:
            raise ValueError("First pincer spline point must define h_out.")
        if i == len(p.pincer_points) - 1 and pt.h_in is None:
            raise ValueError("Last pincer spline point must define h_in.")
