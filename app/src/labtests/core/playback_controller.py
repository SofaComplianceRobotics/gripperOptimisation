"""Base SOFA controller for direct-mode (motor-playback) cube-pick tests.

Usage inside createScene():

    import Sofa.Core
    from labtests.core.playback_controller import make_playback_controller

    Base = make_playback_controller(Sofa.Core.Controller)

    # grasp_hold — use directly with default behaviour
    simulation.addObject(Base(name="PlaybackController", rootnode=..., cfg=...))

    # other tests — subclass and override only what differs
    class MyController(Base):
        def _on_horizon_complete(self, sim_time):
            ...

Three override hooks:
    _initial_cube_mass()         starting mass         (default: cfg.cube_mass_start)
    _update_overload_mass()      per-frame mass update (default: ramp to cfg.cube_mass_max)
    _on_horizon_complete(t)      end-of-frames action  (default: write_pruned_and_stop)
"""
from __future__ import annotations

import os

DT = 0.01


def make_playback_controller(SofaController):
    """Return BasePlaybackController bound to a live Sofa.Core.Controller class.

    Call once inside createScene() after `import Sofa.Core`, passing
    Sofa.Core.Controller as the argument.
    """

    class BasePlaybackController(SofaController):
        def __init__(
            self,
            *args,
            rootnode,
            playback,
            cube_handles,
            gripper_collision,
            writer,
            cfg,
            **kwargs,
        ):
            SofaController.__init__(self, *args, **kwargs)
            self.rootnode = rootnode
            self.playback = playback
            self.cube_handles = cube_handles
            self.gripper_collision = gripper_collision
            self.writer = writer
            self.cfg = cfg

            self.finished = False
            self.frame = 0
            # recorded_frames is the sim-frame count for the recording phase,
            # accounting for any DT mismatch between the recording and the sim.
            rec_dt = playback.recording_dt
            self.recorded_frames = round(len(playback.motor_positions) * rec_dt / DT)
            self.overload_frames = max(0, int(cfg.overload_max_time / DT))
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
            self._set_cube_mass(self._initial_cube_mass())
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
                f"[Scoring] hold-time after {cfg.early_stop_sim_time:.2f}s, pickup threshold: {cfg.pickup_y_threshold}"
            )

        # ── Override hooks ────────────────────────────────────────────────────

        def _initial_cube_mass(self) -> float:
            """Return the cube mass for the first frame of the simulation."""
            return self.cfg.cube_mass_start

        def _update_overload_mass(self) -> None:
            """Ramp cube mass from start to max during the overload phase."""
            if self.frame < self.recorded_frames:
                self._set_cube_mass(self.cfg.cube_mass_start)
                return
            overload_t = (self.frame - self.recorded_frames) * DT
            alpha = (
                1.0
                if self.cfg.cube_mass_ramp_time <= 0
                else max(0.0, min(1.0, overload_t / self.cfg.cube_mass_ramp_time))
            )
            self._set_cube_mass(
                self.cfg.cube_mass_start
                + (self.cfg.cube_mass_max - self.cfg.cube_mass_start) * alpha
            )

        def _on_horizon_complete(self, sim_time: float) -> None:
            """Handle end-of-frames; default marks the run as pruned."""
            self.writer.write_pruned_and_stop(f"horizon complete t={sim_time:.2f}s")

        # ── Internal helpers ──────────────────────────────────────────────────

        def _get_cube_y(self):
            """Return the current Y position of the cube centre of mass."""
            return float(
                self.rootnode.Simulation.Cube.getMechanicalState().position.value[0][1]
            )

        def _set_cube_mass(self, value: float) -> None:
            """Set the cube's total mass, clamped to a minimum to avoid physics instability."""
            mass = max(0.0001, float(value))
            try:
                self.rootnode.Simulation.Cube.cube_mass.totalMass.value = mass
            except Exception:
                pass

        def _get_cube_collision_min_y(self) -> float | None:
            """Return the minimum Y of all cube collision mesh points, or None on error."""
            try:
                points = (
                    self.rootnode.Simulation.Cube.collision.getMechanicalState().position.value
                )
                ys = [float(p[1]) for p in points if len(p) >= 2]
                return min(ys) if ys else None
            except Exception:
                return None

        def _get_gripper_collision_min_y(self) -> float | None:
            """Return the minimum Y of all gripper collision mesh points, or None on error."""
            try:
                points = self.gripper_collision.getMechanicalState().position.value
                ys = [float(p[1]) for p in points if len(p) >= 2]
                return min(ys) if ys else None
            except Exception:
                return None

        def _current_phase(self) -> str:
            """Return 'recorded' during motor playback or 'overload' after it ends."""
            return "recorded" if self.frame < self.recorded_frames else "overload"

        def _get_cube_gripper_contact_count(self) -> int:
            """Return the number of active contact points between cube and gripper."""
            if self.cube_gripper_contact_listener is None:
                try:
                    self.cube_gripper_contact_listener = (
                        self.rootnode.Simulation.getObject(
                            "cubeGripperContactListener"
                        )
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
            """Return True if any contact exists between the cube and gripper."""
            return self._get_cube_gripper_contact_count() > 0

        def _collision_aabb(self, collision_node):
            """Return the axis-aligned bounding box of a collision node as (xmin, xmax, ymin, ymax, zmin, zmax)."""
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
            """Return True if the cube overlaps the gripper at spawn time."""
            if self._get_cube_gripper_contact_count() > 0:
                return True
            cube_aabb = self._collision_aabb(self.rootnode.Simulation.Cube.collision)
            gripper_aabb = self._collision_aabb(self.gripper_collision)
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
            """Set spawn_y and derived pick/drop thresholds on the first spawn frame."""
            if self.spawn_cube_y is not None:
                return
            self.spawn_cube_y = float(cube_y)
            self.drop_y_threshold = self.spawn_cube_y - self.cfg.drop_below_spawn_tol
            self.pickup_y_threshold = (
                self.spawn_cube_y + self.cfg.pickup_above_spawn_tol
            )
            print(
                f"[Scoring] spawn_y={self.spawn_cube_y:.2f} | "
                f"pickup>={self.pickup_y_threshold:.2f} | "
                f"drop<{self.drop_y_threshold:.2f}"
            )

        def _check_spawn_contact_window(self, sim_time: float) -> None:
            """Penalise a run if the cube contacts the gripper within the spawn window."""
            if self.spawn_contact_check_frames <= 0 or self.writer.finished:
                return
            if self._spawn_overlap_detected():
                self.writer.write_score_and_stop(
                    self.cfg.early_contact_penalty,
                    f"cube touched gripper at spawn window t={sim_time:.2f}s",
                )
                return
            self.spawn_contact_check_frames -= 1

        def _compute_score(self) -> tuple[float, str]:
            """Return (score, reason_string) for writing to trial_state.json."""
            return self.hold_time, f"hold_time={self.hold_time:.2f}s"

        def _save_cube_y_graph(self, score: float, reason: str) -> None:
            """Plot and save cube Y vs time if show_cube_y_graph is enabled."""
            if not self.cfg.show_cube_y_graph or not self.cube_y_log:
                return
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(12, 6))
            ax.plot(self.time_log, self.cube_y_log, linewidth=0.8)
            ax.axhline(
                y=self.cfg.pickup_y_threshold,
                color="green",
                linestyle="--",
                linewidth=0.8,
                label=f"pickup ({self.cfg.pickup_y_threshold})",
            )
            ax.axhline(
                y=self.cfg.floor_y_threshold,
                color="red",
                linestyle="--",
                linewidth=0.8,
                label=f"floor ({self.cfg.floor_y_threshold})",
            )
            ax.set_xlim(0, len(self.playback.motor_positions) * DT)
            ax.set_ylim(-320, -10)
            ax.set_xlabel("Simulation time (s)")
            ax.set_ylabel("Cube Y position")
            ax.set_title(f"Cube Y — {reason} | score: {score:.2f}")
            ax.legend()
            out = os.path.join(os.getcwd(), f"cube_y_{os.getpid()}.png")
            fig.savefig(out, dpi=150)
            print(f"[Graph] Saved to {out}")
            plt.show()

        # ── Main loop ─────────────────────────────────────────────────────────

        def onAnimateBeginEvent(self, event):
            """Run scoring logic and motor replay at the start of each simulation step."""
            if self.writer.finished:
                return

            sim_time = self.frame * DT
            self._update_overload_mass()

            # ── Cube spawn teleport ────────────────────────────────────────────
            cube_y = None
            if not self.cube_has_spawned and sim_time >= self.cfg.cube_spawn_time:
                cube_mo = self.rootnode.Simulation.Cube.getMechanicalState()
                cube_mo.position.value = [
                    [0.0, self.cube_handles.cube_spawn_y, 0.0, 0.0, 0.0, 0.0, 1.0]
                ]
                cube_mo.velocity.value = [[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]]
                self.cube_has_spawned = True
                self.spawn_contact_check_frames = 2
                cube_y = float(self.cube_handles.cube_spawn_y)
                self._ensure_drop_threshold_initialized(cube_y)
                print(f"[Spawn] cube spawned at t={sim_time:.2f}s")
                self._check_spawn_contact_window(sim_time)
            elif not self.cube_has_spawned:
                cube_mo = self.rootnode.Simulation.Cube.getMechanicalState()
                cube_mo.position.value = [
                    [
                        0.0,
                        self.cube_handles.cube_spawn_y + self.cfg.cube_prespawn_offset,
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

            self.writer.write_status(
                {
                    "state": "running",
                    "current_frame": self.frame,
                    "total_frames": self.total_frames,
                    "sim_time": sim_time,
                    "cube_y": cube_y,
                    "phase": self._current_phase(),
                    "hold_time": self.hold_time,
                }
            )

            # ── Scoring logic (only once cube has spawned) ─────────────────────
            if self.cube_has_spawned and cube_y is not None:
                if self.cfg.show_cube_y_graph:
                    self.cube_y_log.append(cube_y)
                    self.time_log.append(sim_time)

                if cube_y > self.peak_y:
                    self.peak_y = cube_y

                if self.cfg.enable_undercube_check:
                    cube_min_y = self._get_cube_collision_min_y()
                    gripper_min_y = self._get_gripper_collision_min_y()
                    if cube_min_y is not None and gripper_min_y is not None:
                        if gripper_min_y < (cube_min_y - self.cfg.undercube_margin):
                            self.writer.write_score_and_stop(
                                self.cfg.undercube_penalty,
                                f"undercube geometry t={sim_time:.2f}s "
                                f"gripper_min_y={gripper_min_y:.2f} < cube_min_y={cube_min_y:.2f}",
                            )
                            return

                if cube_y > float(self.pickup_y_threshold):
                    self.was_picked_up = True

                if self.was_picked_up and cube_y < float(self.drop_y_threshold):
                    self.dropped = True

                if sim_time >= self.cfg.early_stop_sim_time and cube_y > float(
                    self.pickup_y_threshold
                ):
                    self.hold_time += DT

                # Rule 1: cube through floor
                if cube_y < self.cfg.floor_y_threshold:
                    if self.was_picked_up:
                        self.writer.write_pruned_and_stop(
                            f"cube glitched through floor after pickup t={sim_time:.2f}s"
                        )
                    else:
                        score, reason = self._compute_score()
                        self._save_cube_y_graph(score, reason)
                        self.writer.write_score_and_stop(
                            score,
                            f"cube through floor t={sim_time:.2f}s — {reason}",
                        )
                    return

                # Rule 2: pickup gate failed
                if sim_time >= self.cfg.early_stop_sim_time and not self.was_picked_up:
                    score = self.cfg.no_pickup_penalty
                    reason = f"no_pickup_penalty={self.cfg.no_pickup_penalty:.2f} hold_time={self.hold_time:.2f}s"
                    self._save_cube_y_graph(score, reason)
                    self.writer.write_score_and_stop(
                        score,
                        f"pickup gate failed t={sim_time:.2f}s — {reason}",
                    )
                    return

                # Rule 3: dropped after pickup
                if self.was_picked_up and cube_y < float(self.drop_y_threshold):
                    score, reason = self._compute_score()
                    self._save_cube_y_graph(score, reason)
                    self.writer.write_score_and_stop(
                        score,
                        f"dropped t={sim_time:.2f}s phase={self._current_phase()} "
                        f"cube_y={cube_y:.2f} < drop_y={float(self.drop_y_threshold):.2f} — {reason}",
                    )
                    return

            # ── End of frames ──────────────────────────────────────────────────
            if self.frame >= self.total_frames:
                self._on_horizon_complete(sim_time)
                return

            # ── Motor replay ───────────────────────────────────────────────────
            rec_frame = int(sim_time / self.playback.recording_dt)
            positions = (
                self.playback.motor_positions[rec_frame]
                if rec_frame < len(self.playback.motor_positions)
                else self.last_positions
            )
            for i, constraint in enumerate(self.playback.joint_constraints):
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
            """Run the spawn-contact check at the end of each simulation step."""
            if self.writer.finished:
                return
            sim_time = max(0.0, (self.frame - 1) * DT)
            self._check_spawn_contact_window(sim_time)

    return BasePlaybackController