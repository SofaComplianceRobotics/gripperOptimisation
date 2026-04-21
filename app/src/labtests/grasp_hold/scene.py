"""
Scene: grasp_hold

Standard cube-grasp-and-lift benchmark.
Direct mode: replays a recorded motor trajectory, scores by hold time.

What this file owns:
  - Env-var config reading
  - PlaybackController (the test-specific logic)
  - createScene() wiring

Everything else comes from core.
"""

from __future__ import annotations

import os
import random
import sys
from pathlib import Path

def _ensure_scene_paths() -> tuple[Path, Path, Path, Path]:
    script_dir = Path(__file__).resolve().parent
    src_root = next(
        (candidate for candidate in (script_dir, *script_dir.parents) if (candidate / "labtests").is_dir()),
        script_dir.parents[1],
    )
    app_root = src_root.parent
    lab_root = app_root.parent
    for candidate in (str(lab_root), str(app_root), str(src_root)):
        if candidate not in sys.path:
            sys.path.insert(0, candidate)
    return script_dir, src_root, app_root, lab_root


# ── Path bootstrap (same pattern as before) ───────────────────────────────────
SCRIPT_DIR, SRC_ROOT, APP_ROOT, LAB_ROOT = _ensure_scene_paths()

# ── Config from environment ───────────────────────────────────────────────────
ASSETS_ROOT = LAB_ROOT.parent.parent
GRIPPER_MESH_PATH = os.environ.get(
    "OPTUNA_STL_PATH",
    str(ASSETS_ROOT / "data" / "meshes" / "centerparts" / "new_gripper_collision.stl"),
)
SCORE_PATH = os.environ.get("OPTUNA_SCORE_PATH", None)
STATUS_PATH = os.environ.get("OPTUNA_STATUS_PATH", None)
OPTUNA_GEN = int(os.environ.get("OPTUNA_GEN", "0"))
OPTUNA_TRIAL = int(os.environ.get("OPTUNA_TRIAL", "0"))
OPTUNA_RUN = int(os.environ.get("OPTUNA_RUN", "0"))

EARLY_STOP_SIM_TIME = float(os.environ.get("EARLY_STOP_SIM_TIME", "1.0"))
FLOOR_Y_THRESHOLD = float(os.environ.get("FLOOR_Y_THRESHOLD", "-235.0"))
FLOOR_Y_BUFFER = float(os.environ.get("FLOOR_Y_BUFFER", "5.0"))
PICKUP_Y_THRESHOLD = float(os.environ.get("PICKUP_Y_THRESHOLD", "-215.0"))
DROP_PENALTY = float(os.environ.get("DROP_PENALTY", "50.0"))
OVERLOAD_MAX_TIME = float(os.environ.get("OVERLOAD_MAX_TIME", "12.0"))
CUBE_MASS_START = float(os.environ.get("CUBE_MASS_START", "0.02"))
CUBE_MASS_MAX = float(os.environ.get("CUBE_MASS_MAX", "1.0"))
CUBE_MASS_RAMP_TIME = float(os.environ.get("CUBE_MASS_RAMP_TIME", "8.0"))
EARLY_CONTACT_STOP_TIME = float(os.environ.get("EARLY_CONTACT_STOP_TIME", "0.6"))
EARLY_CONTACT_PENALTY = float(os.environ.get("EARLY_CONTACT_PENALTY", "-1.0"))
NO_PICKUP_PENALTY = float(os.environ.get("NO_PICKUP_PENALTY", "0.0"))
UNDERCUBE_PENALTY = float(os.environ.get("UNDERCUBE_PENALTY", "-0.2"))
UNDERCUBE_MARGIN = float(os.environ.get("UNDERCUBE_MARGIN", "0.0"))
ENABLE_UNDERCUBE_CHECK = os.environ.get("ENABLE_UNDERCUBE_CHECK", "0") == "1"
SHAPEOPT_FRICTION_COEF = float(os.environ.get("SHAPEOPT_FRICTION_COEF", "0.6"))
SHOW_CUBE_Y_GRAPH = os.environ.get("SHOW_CUBE_Y_GRAPH", "0") == "1"
SHAPEOPT_TEST_MODE = os.environ.get("SHAPEOPT_TEST_MODE", "").strip().lower()
SHAPEOPT_FINISH_BONUS = float(os.environ.get("SHAPEOPT_FINISH_BONUS", "2.0"))
SHAPEOPT_CUBE_WEIGHT_MIN = float(os.environ.get("SHAPEOPT_CUBE_WEIGHT_MIN", "0.02"))
SHAPEOPT_CUBE_WEIGHT_MAX = float(os.environ.get("SHAPEOPT_CUBE_WEIGHT_MAX", "0.2"))
SHAPEOPT_FLOOR_CENTER_Y = float(os.environ.get("SHAPEOPT_FLOOR_CENTER_Y", "-230.0"))
SHAPEOPT_CUBE_SPAWN_CLEARANCE = float(
    os.environ.get("SHAPEOPT_CUBE_SPAWN_CLEARANCE", "10")
)
SHAPEOPT_DROP_BELOW_SPAWN_TOL = float(
    os.environ.get("SHAPEOPT_DROP_BELOW_SPAWN_TOL", "0.5")
)
SHAPEOPT_PICKUP_ABOVE_SPAWN_TOL = float(
    os.environ.get("SHAPEOPT_PICKUP_ABOVE_SPAWN_TOL", "1.0")
)
SHAPEOPT_CUBE_SPAWN_TIME = float(os.environ.get("SHAPEOPT_CUBE_SPAWN_TIME", "0.4"))
SHAPEOPT_CUBE_PRESPAWN_OFFSET = float(
    os.environ.get("SHAPEOPT_CUBE_PRESPAWN_OFFSET", "200.0")
)

DT = 0.01
IS_RANDOM_CUBE_MODE = SHAPEOPT_TEST_MODE == "random_cube_pick"


def _resolve_record_file() -> str:
    target = os.environ.get("LAB_SHAPEOPT_RECORDING_TARGET", "").strip()
    if not target:
        target = os.environ.get("OPTUNA_TEST_NAME", "").strip()

    if target:
        target_path = (
            LAB_ROOT / "runtime" / "recordings" / target / "motor_recording.json"
        )
        legacy = LAB_ROOT / "runtime" / "motor_recording.json"
        if target == "grasp_hold" and not target_path.exists() and legacy.exists():
            return str(legacy)
        return str(target_path)

    legacy = LAB_ROOT / "runtime" / "motor_recording.json"
    if legacy.exists():
        return str(legacy)
    return str(
        LAB_ROOT / "runtime" / "recordings" / "grasp_hold" / "motor_recording.json"
    )


def _resolve_random_cube_case() -> tuple[list[float], float] | None:
    if SHAPEOPT_TEST_MODE != "random_cube_pick":
        return None

    size_cycle = ([5, 5, 5], [8, 8, 8], [20, 20, 20])
    test_run_index = int(os.environ.get("LAB_SHAPEOPT_TEST_RUN_INDEX", str(OPTUNA_RUN)))
    cycle_index = max(0, (test_run_index - 1) % 3)
    cube_scale = list(size_cycle[cycle_index])

    lo = min(SHAPEOPT_CUBE_WEIGHT_MIN, SHAPEOPT_CUBE_WEIGHT_MAX)
    hi = max(SHAPEOPT_CUBE_WEIGHT_MIN, SHAPEOPT_CUBE_WEIGHT_MAX)
    rng = random.Random(OPTUNA_GEN)
    cube_mass = rng.uniform(lo, hi)
    return cube_scale, cube_mass


# ── createScene ───────────────────────────────────────────────────────────────


def createScene(rootnode):
    _ensure_scene_paths()
    import Sofa.Core  # type: ignore

    from labtests.core.base_scene import build_base_scene
    from labtests.core.modules.collision_stl import setup as setup_collision
    from labtests.core.modules.cube_floor import setup as setup_cube_floor
    from labtests.core.modules.motor_playback import setup as setup_playback
    from labtests.core.scoring import ScoreWriter

    # ── Cube config (normal or random) ────────────────────────────────────────
    random_cube_case = _resolve_random_cube_case()
    if random_cube_case is not None:
        cube_scale, cube_mass_start = random_cube_case
        cube_mass_max = cube_mass_start  # fixed mass for random-cube mode
        print(
            f"[cube] random_cube_pick run={os.environ.get('LAB_SHAPEOPT_TEST_RUN_INDEX', str(OPTUNA_RUN))} "
            f"gen={OPTUNA_GEN} scale={cube_scale} mass={cube_mass_start:.5f}kg"
        )
    else:
        cube_scale = [5.0, 5.0, 5.0]
        cube_mass_start = CUBE_MASS_START
        cube_mass_max = CUBE_MASS_MAX

    # ── Base scene (rootnode + Emio) ──────────────────────────────────────────
    nodes = build_base_scene(rootnode, inverse=False, friction=SHAPEOPT_FRICTION_COEF)
    if nodes is None:
        return
    print(f"[contact] friction configured with mu={SHAPEOPT_FRICTION_COEF:.6f}")

    # Required plugins (unchanged from original)
    _add_required_plugins(nodes.simulation)

    rootnode.dt = DT  # base_scene sets dt=0.01 for direct, but be explicit

    # ── Modules ───────────────────────────────────────────────────────────────
    gripper_collision = setup_collision(nodes.emio, GRIPPER_MESH_PATH)

    cube_handles = setup_cube_floor(
        nodes.simulation,
        gripper_collision,
        cube_scale=cube_scale,
        cube_mass=cube_mass_start,
        floor_center_y=SHAPEOPT_FLOOR_CENTER_Y,
        cube_spawn_clearance=SHAPEOPT_CUBE_SPAWN_CLEARANCE,
    )

    playback = setup_playback(nodes.emio, _resolve_record_file())

    # ── ScoreWriter ───────────────────────────────────────────────────────────
    writer = ScoreWriter(
        rootnode,
        score_path=SCORE_PATH,
        status_path=STATUS_PATH,
        run_info={"gen": OPTUNA_GEN, "trial": OPTUNA_TRIAL, "run": OPTUNA_RUN},
    )

    # ── PlaybackController ────────────────────────────────────────────────────

    class PlaybackController(Sofa.Core.Controller):
        def __init__(self, *args, **kwargs):
            Sofa.Core.Controller.__init__(self, *args, **kwargs)
            self.finished = False
            self.frame = 0
            self.recorded_frames = len(playback.motor_positions)
            self.overload_frames = max(0, int(OVERLOAD_MAX_TIME / DT))
            self.total_frames = self.recorded_frames + self.overload_frames
            self.peak_y = float("-inf")
            self.was_picked_up = False
            self.dropped = False
            self.hold_time = 0.0
            self.last_positions = (
                list(playback.motor_positions[-1])
                if playback.motor_positions
                else [0.0] * playback.num_motors
            )
            self.cube_y_log = []
            self.time_log = []
            self.cube_gripper_contact_listener = None
            self.spawn_cube_y = None
            self.drop_y_threshold = None
            self.pickup_y_threshold = None
            self.cube_has_spawned = False
            self.spawn_contact_check_frames = 0
            self._set_cube_mass(cube_mass_start)
            writer.write_status(
                {
                    "state": "running",
                    "current_frame": 0,
                    "total_frames": self.total_frames,
                    "sim_time": 0.0,
                    "cube_y": None,
                }
            )
            print(
                f"[Playback] {self.recorded_frames} recorded + {self.overload_frames} overload frames\n"
                f"[Scoring] hold-time after {EARLY_STOP_SIM_TIME:.2f}s, pickup threshold: {PICKUP_Y_THRESHOLD}"
            )

        # ── Helpers ───────────────────────────────────────────────────────────

        def _get_cube_y(self):
            return float(
                rootnode.Simulation.Cube.getMechanicalState().position.value[0][1]
            )

        def _set_cube_mass(self, value: float) -> None:
            mass = max(0.0001, float(value))
            try:
                rootnode.Simulation.Cube.cube_mass.totalMass.value = mass
            except Exception:
                pass

        def _get_cube_collision_min_y(self) -> float | None:
            try:
                points = (
                    rootnode.Simulation.Cube.collision.getMechanicalState().position.value
                )
                ys = [float(p[1]) for p in points if len(p) >= 2]
                return min(ys) if ys else None
            except Exception:
                return None

        def _get_gripper_collision_min_y(self) -> float | None:
            try:
                points = gripper_collision.getMechanicalState().position.value
                ys = [float(p[1]) for p in points if len(p) >= 2]
                return min(ys) if ys else None
            except Exception:
                return None

        def _current_phase(self) -> str:
            return "recorded" if self.frame < self.recorded_frames else "overload"

        def _update_overload_mass(self) -> None:
            if self.frame < self.recorded_frames:
                self._set_cube_mass(cube_mass_start)
                return
            overload_t = (self.frame - self.recorded_frames) * DT
            alpha = (
                1.0
                if CUBE_MASS_RAMP_TIME <= 0
                else max(0.0, min(1.0, overload_t / CUBE_MASS_RAMP_TIME))
            )
            self._set_cube_mass(
                cube_mass_start + (cube_mass_max - cube_mass_start) * alpha
            )

        def _get_cube_gripper_contact_count(self) -> int:
            if self.cube_gripper_contact_listener is None:
                try:
                    self.cube_gripper_contact_listener = rootnode.Simulation.getObject(
                        "cubeGripperContactListener"
                    )
                except Exception:
                    pass
            if self.cube_gripper_contact_listener is None:
                return 0
            try:
                return int(self.cube_gripper_contact_listener.getNumberOfContacts())
            except Exception:
                return 0

        def _has_cube_gripper_contact(self) -> bool:
            return self._get_cube_gripper_contact_count() > 0

        def _collision_aabb(self, collision_node):
            try:
                points = collision_node.getMechanicalState().position.value
            except Exception:
                return None
            if not len(points):
                return None
            xs = [float(p[0]) for p in points if len(p) >= 3]
            ys = [float(p[1]) for p in points if len(p) >= 3]
            zs = [float(p[2]) for p in points if len(p) >= 3]
            if not xs:
                return None
            return min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)

        def _spawn_overlap_detected(self) -> bool:
            if self._get_cube_gripper_contact_count() > 0:
                return True
            cube_aabb = self._collision_aabb(rootnode.Simulation.Cube.collision)
            gripper_aabb = self._collision_aabb(gripper_collision)
            if cube_aabb is None or gripper_aabb is None:
                return False
            cx0, cx1, cy0, cy1, cz0, cz1 = cube_aabb
            gx0, gx1, gy0, gy1, gz0, gz1 = gripper_aabb
            return (
                cx0 <= gx1
                and cx1 >= gx0
                and cy0 <= gy1
                and cy1 >= gy0
                and cz0 <= gz1
                and cz1 >= gz0
            )

        def _ensure_drop_threshold_initialized(self, cube_y: float) -> None:
            if self.spawn_cube_y is not None:
                return
            self.spawn_cube_y = float(cube_y)
            self.drop_y_threshold = self.spawn_cube_y - SHAPEOPT_DROP_BELOW_SPAWN_TOL
            self.pickup_y_threshold = (
                self.spawn_cube_y + SHAPEOPT_PICKUP_ABOVE_SPAWN_TOL
            )
            print(
                f"[Scoring] spawn_y={self.spawn_cube_y:.2f} | "
                f"pickup>={self.pickup_y_threshold:.2f} | "
                f"drop<{self.drop_y_threshold:.2f}"
            )

        def _check_spawn_contact_window(self, sim_time: float) -> None:
            if self.spawn_contact_check_frames <= 0 or writer.finished:
                return
            if self._spawn_overlap_detected():
                writer.write_score_and_stop(
                    EARLY_CONTACT_PENALTY,
                    f"cube touched gripper at spawn window t={sim_time:.2f}s",
                )
                return
            self.spawn_contact_check_frames -= 1

        def _compute_score(self) -> tuple[float, str]:
            return self.hold_time, f"hold_time={self.hold_time:.2f}s"

        def _save_cube_y_graph(self, score: float, reason: str) -> None:
            if not SHOW_CUBE_Y_GRAPH or not self.cube_y_log:
                return
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(12, 6))
            ax.plot(self.time_log, self.cube_y_log, linewidth=0.8)
            ax.axhline(
                y=PICKUP_Y_THRESHOLD,
                color="green",
                linestyle="--",
                linewidth=0.8,
                label=f"pickup ({PICKUP_Y_THRESHOLD})",
            )
            ax.axhline(
                y=FLOOR_Y_THRESHOLD,
                color="red",
                linestyle="--",
                linewidth=0.8,
                label=f"floor ({FLOOR_Y_THRESHOLD})",
            )
            ax.set_xlim(0, len(playback.motor_positions) * DT)
            ax.set_ylim(-320, -10)
            ax.set_xlabel("Simulation time (s)")
            ax.set_ylabel("Cube Y position")
            ax.set_title(f"Cube Y — {reason} | score: {score:.2f}")
            ax.legend()
            out = os.path.join(os.path.dirname(__file__), f"cube_y_{os.getpid()}.png")
            fig.savefig(out, dpi=150)
            print(f"[Graph] Saved to {out}")
            plt.show()

        # ── Main loop ─────────────────────────────────────────────────────────

        def onAnimateBeginEvent(self, event):
            if writer.finished:
                return

            sim_time = self.frame * DT
            self._update_overload_mass()

            # ── Cube spawn teleport ────────────────────────────────────────────
            cube_y = None
            if not self.cube_has_spawned and sim_time >= SHAPEOPT_CUBE_SPAWN_TIME:
                cube_mo = rootnode.Simulation.Cube.getMechanicalState()
                cube_mo.position.value = [
                    [0.0, cube_handles.cube_spawn_y, 0.0, 0.0, 0.0, 0.0, 1.0]
                ]
                cube_mo.velocity.value = [[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]]
                self.cube_has_spawned = True
                self.spawn_contact_check_frames = 2
                cube_y = float(cube_handles.cube_spawn_y)
                self._ensure_drop_threshold_initialized(cube_y)
                print(f"[Spawn] cube spawned at t={sim_time:.2f}s")
                self._check_spawn_contact_window(sim_time)
            elif not self.cube_has_spawned:
                cube_mo = rootnode.Simulation.Cube.getMechanicalState()
                cube_mo.position.value = [
                    [
                        0.0,
                        cube_handles.cube_spawn_y + SHAPEOPT_CUBE_PRESPAWN_OFFSET,
                        0.0,
                        0.0,
                        0.0,
                        0.0,
                        1.0,
                    ]
                ]
                cube_mo.velocity.value = [[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]]

            if self.cube_has_spawned and cube_y is None:
                cube_y = self._get_cube_y()
                self._ensure_drop_threshold_initialized(cube_y)

            writer.write_status(
                {
                    "state": "running",
                    "current_frame": self.frame,
                    "total_frames": self.total_frames,
                    "sim_time": sim_time,
                    "cube_y": cube_y,
                    "phase": self._current_phase(),
                }
            )

            # ── Scoring logic (only once cube has spawned) ─────────────────────
            if self.cube_has_spawned and cube_y is not None:
                if SHOW_CUBE_Y_GRAPH:
                    self.cube_y_log.append(cube_y)
                    self.time_log.append(sim_time)

                if cube_y > self.peak_y:
                    self.peak_y = cube_y

                if ENABLE_UNDERCUBE_CHECK:
                    cube_min_y = self._get_cube_collision_min_y()
                    gripper_min_y = self._get_gripper_collision_min_y()
                    if cube_min_y is not None and gripper_min_y is not None:
                        if gripper_min_y < (cube_min_y - UNDERCUBE_MARGIN):
                            writer.write_score_and_stop(
                                UNDERCUBE_PENALTY,
                                f"undercube geometry t={sim_time:.2f}s "
                                f"gripper_min_y={gripper_min_y:.2f} < cube_min_y={cube_min_y:.2f}",
                            )
                            return

                if cube_y > float(self.pickup_y_threshold):
                    self.was_picked_up = True

                if self.was_picked_up and cube_y < float(self.drop_y_threshold):
                    self.dropped = True

                if sim_time >= EARLY_STOP_SIM_TIME and cube_y > float(
                    self.pickup_y_threshold
                ):
                    self.hold_time += DT

                # Rule 1: cube through floor
                if cube_y < FLOOR_Y_THRESHOLD:
                    if self.was_picked_up:
                        writer.write_pruned_and_stop(
                            f"cube glitched through floor after pickup t={sim_time:.2f}s"
                        )
                    else:
                        score, reason = self._compute_score()
                        self._save_cube_y_graph(score, reason)
                        writer.write_score_and_stop(
                            score, f"cube through floor t={sim_time:.2f}s — {reason}"
                        )
                    return

                # Rule 2: pickup gate failed
                if sim_time >= EARLY_STOP_SIM_TIME and not self.was_picked_up:
                    score = NO_PICKUP_PENALTY
                    reason = f"no_pickup_penalty={NO_PICKUP_PENALTY:.2f} hold_time={self.hold_time:.2f}s"
                    self._save_cube_y_graph(score, reason)
                    writer.write_score_and_stop(
                        score, f"pickup gate failed t={sim_time:.2f}s — {reason}"
                    )
                    return

                # Rule 3: dropped after pickup
                if self.was_picked_up and cube_y < float(self.drop_y_threshold):
                    score, reason = self._compute_score()
                    self._save_cube_y_graph(score, reason)
                    writer.write_score_and_stop(
                        score,
                        f"dropped t={sim_time:.2f}s phase={self._current_phase()} "
                        f"cube_y={cube_y:.2f} < drop_y={float(self.drop_y_threshold):.2f} — {reason}",
                    )
                    return

            # ── End of frames ──────────────────────────────────────────────────
            if self.frame >= self.total_frames:
                if IS_RANDOM_CUBE_MODE:
                    score = self.hold_time + SHAPEOPT_FINISH_BONUS
                    writer.write_score_and_stop(
                        score,
                        f"horizon complete t={sim_time:.2f}s hold_time={self.hold_time:.2f}s "
                        f"finish_bonus={SHAPEOPT_FINISH_BONUS:.2f}",
                    )
                else:
                    writer.write_pruned_and_stop(f"horizon complete t={sim_time:.2f}s")
                return

            # ── Motor replay ───────────────────────────────────────────────────
            positions = (
                playback.motor_positions[self.frame]
                if self.frame < self.recorded_frames
                else self.last_positions
            )
            for i, constraint in enumerate(playback.joint_constraints):
                if i < len(positions):
                    constraint.value.value = positions[i]

            if self.frame % 200 == 0:
                cube_y_text = f"{cube_y:.2f}" if cube_y is not None else "n/a"
                print(
                    f"[Playback] frame {self.frame}/{self.total_frames - 1}"
                    f"  t={sim_time:.2f}s  cube_Y={cube_y_text}"
                    f"  phase={self._current_phase()}"
                    f"  peak={self.peak_y:.2f}"
                    f"  hold={self.hold_time:.2f}s"
                    f"  picked={self.was_picked_up}",
                    flush=True,
                )

            self.frame += 1

        def onAnimateEndEvent(self, event):
            if writer.finished:
                return
            sim_time = max(0.0, (self.frame - 1) * DT)
            self._check_spawn_contact_window(sim_time)

    nodes.simulation.addObject(PlaybackController(name="PlaybackController"))
    return rootnode


# ── Required plugins helper ───────────────────────────────────────────────────


def _add_required_plugins(simulation_node) -> None:
    plugins = [
        "Sofa.Component.AnimationLoop",
        "Sofa.Component.Collision.Detection.Algorithm",
        "Sofa.Component.Collision.Detection.Intersection",
        "Sofa.Component.Collision.Geometry",
        "Sofa.Component.Collision.Response.Contact",
        "Sofa.Component.Constraint.Lagrangian.Correction",
        "Sofa.Component.Constraint.Lagrangian.Solver",
        "Sofa.Component.IO.Mesh",
        "Sofa.Component.LinearSolver.Iterative",
        "Sofa.Component.Mapping.NonLinear",
        "Sofa.Component.Mass",
        "Sofa.Component.ODESolver.Backward",
        "Sofa.Component.StateContainer",
        "Sofa.Component.Topology.Container.Constant",
        "Sofa.Component.Visual",
        "Sofa.GL.Component.Rendering3D",
    ]
    config = simulation_node.addChild("Config")
    for name in plugins:
        config.addObject("RequiredPlugin", name=name, printLog=False)
