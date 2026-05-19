"""JSON export for gripper attachment and configuration data.

Handles serialization of leg attachment poses and gripper configuration
to JSON format for SOFA simulation.
"""

import json
import math
from pathlib import Path

from core.params import ModelParams
from core.transforms.quaternion import (
    _axis_angle_to_quat,
    _quat_mul,
    _normalize_quat,
    _quat_rotate_vector,
    _export_frame_quat,
)


def _leg_attachment_pose(
    p: ModelParams, angle_deg: float, leg_index: int = 0
) -> list[float]:
    """
    Return [x, y, z, qx, qy, qz, qw] for one leg-attachment anchor.

    Position is the base-center of the leg attachment after placement.
    Orientation matches the leg attachment frame after Z rotation and tilt.

    Args:
        p: Model parameters.
        angle_deg: Placement angle in degrees.
        leg_index: Leg index (0-3); applies q2 rotation leg_index times.

    Returns:
        [x, y, z, qx, qy, qz, qw] pose for one attachment.
    """
    placement_radius = p.cylinder_radius - p.leg_attachement_inward_offset
    a = math.radians(angle_deg)

    x = placement_radius * math.cos(a)
    y = placement_radius * math.sin(a)
    ring_h = p.cylinder_height_at(float(angle_deg))
    z = ring_h + p.leg_attachement_lift

    # Exported mesh files are already rotated into SOFA frame in export_pipeline.py.
    # Rotate each attachment pose into that same local frame so anchors lie on the mesh.
    q_export = _export_frame_quat()
    x, y, z = _quat_rotate_vector(q_export, (x, y, z))

    q1 = _axis_angle_to_quat((0.0, 0.0, 1.0), -90.0)
    q3 = _axis_angle_to_quat((1.0, 0.0, 0.0), 90.0)
    q2 = _axis_angle_to_quat((0.0, 1.0, 0.0), 90.0)

    q = _normalize_quat(_quat_mul(q1, q3))
    for _ in range(leg_index):
        q = _normalize_quat(_quat_mul(q2, q))

    a = math.radians(angle_deg)

    # Legs 1 and 3 tilt around the radial axis; 0 and 2 around the tangent axis.
    if leg_index in (1, 3):
        tilt_axis_x = math.cos(a)
        tilt_axis_y = math.sin(a)
        tilt_angle = (
            -p.leg_attachement_tilt_angle
            if leg_index == 1
            else p.leg_attachement_tilt_angle
        )
    else:
        tilt_axis_x = -math.sin(a)
        tilt_axis_y = math.cos(a)
        tilt_angle = (
            p.leg_attachement_tilt_angle
            if leg_index == 0
            else -p.leg_attachement_tilt_angle
        )

    tilt_axis_z = 0.0
    q_tilt = _axis_angle_to_quat((tilt_axis_x, tilt_axis_y, tilt_axis_z), tilt_angle)
    q = _normalize_quat(_quat_mul(q, q_tilt))

    y_rotations = {0: -90.0, 1: 90.0, 2: -90.0, 3: 90.0}
    # Per-leg Y-axis correction to align the attachment frame with the SOFA leg orientation.
    q4 = _axis_angle_to_quat((0.0, 1.0, 0.0), y_rotations[leg_index])
    q = _normalize_quat(_quat_mul(q4, q))

    # Summary of the steps above:
    # 1) compute radial position of an attachment on the ring
    # 2) transform this position into the export frame (SOFA)
    # 3) compose rotations to orient the anchor according to the leg index
    # The result is a pose [x,y,z,qx,qy,qz,qw] ready for use in SOFA.

    return [x, y, z, q[0], q[1], q[2], q[3]]


def export_leg_attachment_json(p: ModelParams, output_path: Path) -> None:
    """
    Export leg attachment anchors and orientations in JSON format.

    Args:
        p: Model parameters.
        output_path: Destination JSON path.
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
