"""
Scene: gripper_tilt

Inverse-mode tilt test.
Moves the gripper through a sequence of target positions and measures
the Y-spread of the effector points as a proxy for achievable tilt.

What this file owns:
  - TiltController (waypoints + Y-spread measurement + scoring)
  - createScene() wiring

Everything else comes from core.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _ensure_scene_paths() -> tuple[Path, Path, Path, Path]:
    script_dir = Path(__file__).resolve().parent
    src_root = next(
        (
            candidate
            for candidate in (script_dir, *script_dir.parents)
            if (candidate / "labtests").is_dir()
        ),
        script_dir.parents[1],
    )
    app_root = src_root.parent
    lab_root = app_root.parent
    for candidate in (str(lab_root), str(app_root), str(src_root)):
        if candidate not in sys.path:
            sys.path.insert(0, candidate)
    return script_dir, src_root, app_root, lab_root


# ── Path bootstrap ─────────────────────────────────────────────────────────────
SCRIPT_DIR, SRC_ROOT, APP_ROOT, LAB_ROOT = _ensure_scene_paths()

# ── Config from environment ────────────────────────────────────────────────────
TRIAL_STATE_PATH = os.environ.get("OPTUNA_TRIAL_STATE_PATH", None)
OPTUNA_RUN_SLOT = int(os.environ.get("OPTUNA_RUN_SLOT", "0"))
OPTUNA_GEN = int(os.environ.get("OPTUNA_GEN", "0"))
OPTUNA_TRIAL = int(os.environ.get("OPTUNA_TRIAL", "0"))
OPTUNA_RUN = int(os.environ.get("OPTUNA_RUN", "0"))

# Waypoints: list of [[x,y,z, qx,qy,qz,qw], hold_frames]
# Can be overridden via env var as a JSON string if needed, otherwise uses defaults.
import json as _json

_WAYPOINTS_ENV = os.environ.get("SHAPEOPT_TILT_WAYPOINTS", "")
DEFAULT_WAYPOINTS = [
    ([0, -150, 40, 0, 0, 0, 1], 10),  # straight forward
    ([40, -150, 0, 0, 0, 0, 1], 10),  # left
]
WAYPOINTS = _json.loads(_WAYPOINTS_ENV) if _WAYPOINTS_ENV else DEFAULT_WAYPOINTS

PROGRAM_FILE = str(SCRIPT_DIR / "mypickandplace.crprog")


# ── createScene ───────────────────────────────────────────────────────────────


def createScene(rootnode):
    _ensure_scene_paths()
    import Sofa.Core  # type: ignore

    from labtests.core.base_scene import build_base_scene
    from labtests.core.modules.effector_target import setup as setup_effector
    from labtests.core.scoring import ScoreWriter
    from parts.controllers.assemblycontroller import AssemblyController  # type: ignore

    # ── Base scene ────────────────────────────────────────────────────────────
    nodes = build_base_scene(rootnode, inverse=True)
    if nodes is None:
        return

    # AssemblyController is needed by TiltController to know when assembly is done
    nodes.emio.addObject(AssemblyController(nodes.emio))

    # ── Effector + ImGui module ────────────────────────────────────────────────
    effector_handles = setup_effector(
        nodes,
        nodes.emio,
        initial_target_pos=[0, -150, 0, 0, 0, 0, 1],
        program_file=PROGRAM_FILE if os.path.exists(PROGRAM_FILE) else None,
    )

    # ── ScoreWriter ────────────────────────────────────────────────────────────
    writer = ScoreWriter(
        rootnode,
        run_info={"gen": OPTUNA_GEN, "trial": OPTUNA_TRIAL, "run": OPTUNA_RUN},
        trial_state_path=TRIAL_STATE_PATH,
        run_slot=OPTUNA_RUN_SLOT,
    )

    # ── TiltController ─────────────────────────────────────────────────────────

    assembly_controller = nodes.emio.getObject("AssemblyController")

    class TiltController(Sofa.Core.Controller):
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
                # Sequence complete — compute score and write
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

            # Measure Y-spread of effector points at this pose
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

            # Advance waypoint after hold
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
