"""Parameters — tunable shape of the Emio leg that clips onto a motor and
slides into the gripper's leg-attachment pockets.

The shape model follows the platform's own leg contract (see the lab_design
lab and the stock blueleg): a fixed base that wraps the motor pulley, a
tunable single-span Bezier spline from that base to a free end point, and a
fixed straight tip run continuing in whatever direction the span was
actually heading at that end point. The default parameter set reproduces the
stock blueleg (straight leg). One leg shape is generated per trial and used
for all four leg attachments.

The end point is parametrized in polar form (dist, angle_deg), matching
geometry/params.py's pincer spline convention (and reusing its
p1_dist/p1_angle_deg/p1_hin_dist names, since this is the same shape: a
fixed start point with a tunable end point and handles). angle_deg = 90
means "straight up" (the neutral/straight direction) in the leg's local
(u=outward, v=up) plane. The start point's outgoing handle keeps its angle
fixed at 90 (only its length is tunable) so the join with the fixed
motor-wrap arc stays G1-continuous. The end point's incoming handle sits
along the *same* angle as the end point itself (leg_p1_angle_deg) — the span
arrives at its end already heading in that direction, and the fixed tip run
continues straight along it, so a bowed leg's tip stays tangent to the bow
instead of snapping back to vertical. With every point/handle at its neutral
angle (90) the whole spline is exactly straight, reproducing the stock leg.

Only the spline is searched; the cross-section is fixed at the stock 10x5mm,
which exactly matches the gripper pocket (ModelParams.leg_hole_length /
leg_hole_width).

Mirrors geometry/params.py's dataclass-with-metadata convention so the same
param_specs_from_dataclass / validate machinery applies to both.
"""

from dataclasses import dataclass, field, fields

from geometry.params import apply_check
from names import LEG_WORKING_NAME


@dataclass(frozen=True)
class LegParams:
    """Immutable configuration for one leg design."""

    # Handle at the start point (end of the fixed motor-wrap arc). Direction
    # is fixed vertical (tangent-matched to the arc); only its length varies.
    # "leg_" prefix on every field below to avoid colliding with
    # ModelParams's identically-named pincer spline fields (p1_dist,
    # p1_angle_deg, ...) — the optimizer's selection file is a flat set of
    # field names shared across both dataclasses.
    leg_p0_hout_dist: float = field(
        default=25.0,
        metadata={
            "opt": {"type": "float", "min": 5.0, "max": 200.0},
            "check": "positive",
        },
    )

    # End anchor point, polar from the start point (the end of the fixed
    # motor-clip straight run — see CLIP_STRAIGHT_RUN in leg_geometry.py).
    leg_p1_dist: float = field(
        default=160.0,
        metadata={
            "opt": {"type": "float", "min": 70.0, "max": 200.0},
            "check": "positive",
        },
    )
    leg_p1_angle_deg: float = field(
        default=90.0, metadata={"opt": {"type": "float", "min": 60.0, "max": 120.0}}
    )
    # Handle into the end point. Direction is fixed vertical (straight entry
    # into the fixed tip run); only its length varies.
    leg_p1_hin_dist: float = field(
        default=25.0,
        metadata={
            "opt": {"type": "float", "min": 5.0, "max": 200.0},
            "check": "positive",
        },
    )

    # Cross-section — fixed at the stock 10x5 that the gripper pocket and the
    # motor clip were designed for. Not searched, not config-tunable bounds;
    # kept as fields because the geometry needs the values.
    width: float = field(default=10.0, metadata={"check": "positive"})
    thickness: float = field(default=5.0, metadata={"check": "positive"})

    # Straight vertical run at the top that slides into the gripper pocket.
    # Structural, not searched.
    tip_straight_len: float = field(default=25.0, metadata={"check": "positive"})

    # Beam-node density of the exported positions file. Structural.
    num_beams: int = field(default=15, metadata={"check": ("ge", 8)})

    # Export — the lab's own working name, never the shared stock LEG_NAME.
    export_stem: str = LEG_WORKING_NAME


def param_specs(base: "LegParams | None" = None) -> list[dict]:
    """Build parameter specs from LegParams field metadata (see geometry.params.param_specs)."""
    if base is None:
        base = LegParams()
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


def validate_params(p: LegParams) -> None:
    """Validate leg parameters.

    Per-field rules come from "check" metadata. Geometric feasibility (fold-
    back, self-intersection, swept-edge overlap) is not a closed-form
    cross-field rule here — it's checked on the built centerline by
    LegCenterline.is_valid() instead.
    """
    for f in fields(p):
        check = f.metadata.get("check")
        if check is None:
            continue
        apply_check(f.name, getattr(p, f.name), check)
