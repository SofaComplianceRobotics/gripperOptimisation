"""
Scene: gripper_tilt

Inverse-mode tilt test.
Moves the gripper through a sequence of target positions and measures
the Y-spread of the effector points as a proxy for achievable tilt.

What this file owns:
  - WAYPOINTS (default + optional JSON env-var override)
  - TiltController (waypoints + Y-spread measurement + scoring)
  - createScene() wiring

Everything else comes from core.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


sys.path.insert(0, str(next(c for c in Path(__file__).parents if (c / "labtests").is_dir())))
from launcher.bootstrap import bootstrap_lab

SCRIPT_DIR, SRC_ROOT, APP_ROOT, LAB_ROOT = bootstrap_lab(__file__)

from labtests.core.scene_config import OptunaMeta  # noqa: E402

META = OptunaMeta.from_env()

# Waypoints: list of [[x,y,z, qx,qy,qz,qw], hold_frames]
WAYPOINTS = [
    ([0, -150, 40, 0, 0, 0, 1], 10),  # straight forward
    ([40, -150, 0, 0, 0, 0, 1], 10),  # left
]

PROGRAM_FILE = str(SCRIPT_DIR / "mypickandplace.crprog")


def createScene(rootnode):
    """Build the gripper_tilt inverse-mode scene with waypoint sequencing and scoring."""
    import Sofa.Core  # type: ignore

    from labtests.core.base_scene import build_base_scene
    from labtests.core.modules.effector_target import setup as setup_effector
    from labtests.core.scoring import ScoreWriter
    from parts.controllers.assemblycontroller import AssemblyController  # type: ignore

    nodes = build_base_scene(rootnode, inverse=True)
    if nodes is None:
        return

    # AssemblyController is needed by TiltController to know when assembly is done.
    nodes.emio.addObject(AssemblyController(nodes.emio))

    effector_handles = setup_effector(
        nodes,
        nodes.emio,
        initial_target_pos=[0, -150, 0, 0, 0, 0, 1],
        program_file=PROGRAM_FILE if os.path.exists(PROGRAM_FILE) else None,
    )

    writer = ScoreWriter(
        rootnode,
        run_info=META.run_info,
        trial_state_path=META.trial_state_path,
        run_slot=META.run_slot,
    )

    assembly_controller = nodes.emio.getObject("AssemblyController")

    class TiltController(Sofa.Core.Controller):
        """Step through WAYPOINTS and score by the Y-spread of effector points."""

        def __init__(self, *args, **kwargs):
            Sofa.Core.Controller.__init__(self, *args, **kwargs)
            self.frame = 0
            self.waypoint_index = 0
            self.hold_frame = 0
            self.max_y_spreads = [0.0 for _ in WAYPOINTS]

        def onAnimateBeginEvent(self, event):
            if not assembly_controller.done:
                return

            if self.waypoint_index >= len(WAYPOINTS):
                if not writer.finished:
                    total_penalty = sum(self.max_y_spreads)
                    score = 40.0 - total_penalty
                    writer.write_score_and_stop(
                        score,
                        f"tilt sequence complete — score={score:.3f} (40 - {self.max_y_spreads[0]:.3f} - {self.max_y_spreads[1]:.3f})",
                    )
                return

            pos, hold_frames = WAYPOINTS[self.waypoint_index]
            effector_handles.target_mo.position.value = [pos]

            points = effector_handles.effector_mo.position.value
            diff_02 = abs(points[0][1] - points[2][1])
            diff_13 = abs(points[1][1] - points[3][1])
            y_spread = max(diff_02, diff_13)

            if y_spread > self.max_y_spreads[self.waypoint_index]:
                self.max_y_spreads[self.waypoint_index] = y_spread

            print(
                f"[Tilt] frame={self.frame} waypoint={self.waypoint_index} "
                f"y_spread={y_spread:.3f}mm  diff_02={diff_02:.3f}  diff_13={diff_13:.3f}"
            )

            writer.write_status(
                {
                    "state": "running",
                    "frame": self.frame,
                    "waypoint_index": self.waypoint_index,
                    "y_spread": y_spread,
                    "max_y_spreads": self.max_y_spreads,
                }
            )

            self.hold_frame += 1
            if self.hold_frame >= hold_frames:
                self.hold_frame = 0
                self.waypoint_index += 1
                if self.waypoint_index < len(WAYPOINTS):
                    next_pos, _ = WAYPOINTS[self.waypoint_index]
                    print(
                        f"[Tilt] moving to waypoint {self.waypoint_index}: {next_pos}"
                    )
                else:
                    print("[Tilt] sequence complete")

            self.frame += 1

    nodes.simulation.addObject(TiltController(name="TiltController"))

    return rootnode
