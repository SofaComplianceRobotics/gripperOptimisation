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

Four override hooks:
    _initial_cube_mass()            starting mass          (default: cfg.cube_mass_start)
    _update_overload_mass()         per-frame mass update  (default: ramp to cfg.cube_mass_max)
    _finish_run(score, reason)      stop logic             (default: write score or pruned)
    _on_horizon_complete(t)         end-of-frames action   (default: score by hold time)
"""

from __future__ import annotations

import os

from geometry.timing_config import DT_CONTACT, DT_DIRECT

from labtests.core import scene_defaults
from labtests.core._loop_phases import (
    apply_scoring_rules,
    check_spawn_contact_window,
    current_phase,
    ensure_drop_threshold_initialized,
    handle_cube_spawn,
    interpolated_motor_positions,
    timeline_frame_at,
)
from labtests.core._sim_query import (
    get_cube_y,
    set_cube_mass,
    set_gripper_collision_active,
)


def make_playback_controller(SofaController):
    """Return BasePlaybackController bound to a live Sofa.Core.Controller class.

    ``Sofa.Core.Controller`` only exists inside an active SOFA session, so the
    class is created here at call time rather than at module import time.

    Args:
        SofaController: ``Sofa.Core.Controller`` class from the active session.

    Returns:
        BasePlaybackController class ready to be instantiated in createScene().
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
            self.physics_step = 0
            self.sim_time = 0.0
            self.recorded_frames = len(playback.motor_positions)
            self.time_scale = max(1e-6, cfg.playback_time_scale)
            # Trajectory duration follows the recording's own capture rate,
            # compressed by the configured time scale.
            self.recorded_duration = (
                self.recorded_frames * playback.recording_dt / self.time_scale
            )
            recorded_physics_frames = max(1, int(round(self.recorded_duration / DT_DIRECT)))
            self.overload_frames = max(0, int(cfg.overload_max_time / DT_DIRECT))
            self.total_frames = recorded_physics_frames + self.overload_frames
            self.total_duration = self.recorded_duration + cfg.overload_max_time
            # Start at contact timestep so the gripper settles before the cube appears;
            # switched back to DT_DIRECT after the post-spawn slow frames elapse
            rootnode.dt.value = DT_CONTACT
            self.peak_y = float("-inf")
            self.was_picked_up = False
            self.dropped = False
            self.hold_time = 0.0
            self.last_positions = (
                list(playback.motor_positions[-1])
                if playback.motor_positions
                else [0.0] * playback.num_motors
            )
            # spawn_cube_y, pickup_y_threshold, drop_y_threshold are set on the
            # first frame after the cube teleports in
            self.spawn_cube_y = None
            self.drop_y_threshold = None
            self.pickup_y_threshold = None
            self.cube_has_spawned = False
            self.spawn_contact_check_frames = 0
            self._post_spawn_slow_frames = 0
            # Gripper↔cube contact instrumentation (off unless SHAPEOPT_DEBUG_CONTACTS=1).
            self._debug_contacts = os.environ.get(
                "SHAPEOPT_DEBUG_CONTACTS", ""
            ).strip().lower() in ("1", "true", "yes", "on")
            # The gripper spawns overlapping the floor and cannot reach its start
            # pose while fighting floor contact. Disable its collision until the
            # cube teleports in (handle_cube_spawn re-enables it); the cube is
            # parked far above the workspace until then, so nothing else is near.
            set_gripper_collision_active(gripper_collision, False)
            # Mass + box inertia are already set by cube_floor at build time.
            # Do NOT re-set the mass here (totalMass would reset the inertia).
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
                f"[Playback] {self.recorded_frames} recorded frames over "
                f"{self.recorded_duration:.2f}s (time_scale={self.time_scale:g}) "
                f"+ {self.overload_frames} overload frames\n"
                f"[Scoring] hold-time after {cfg.early_stop_sim_time:.2f}s, "
                f"pickup threshold: {cfg.pickup_y_threshold}"
            )

        # ── Override hooks ────────────────────────────────────────────────────

        def _initial_cube_mass(self) -> float:
            """Return the cube mass to use on the first simulation frame.

            Returns:
                Starting cube mass from config.
            """
            return self.cfg.cube_mass_start

        def _update_overload_mass(self) -> None:
            """Ramp cube mass from start to max during the overload phase.

            During the recorded phase the mass stays at its build-time value, so
            we deliberately do NOT call set_cube_mass (which would reset the box
            inertia to identity every frame). It is only set once the overload
            ramp actually changes the mass.
            """
            loop_sim_time = getattr(self, "_loop_sim_time", self.sim_time)
            if loop_sim_time < self.recorded_duration:
                return
            overload_t = max(0.0, loop_sim_time - self.recorded_duration)
            alpha = (
                1.0
                if self.cfg.cube_mass_ramp_time <= 0
                else max(0.0, min(1.0, overload_t / self.cfg.cube_mass_ramp_time))
            )
            set_cube_mass(
                self.rootnode,
                self.cfg.cube_mass_start
                + (self.cfg.cube_mass_max - self.cfg.cube_mass_start) * alpha,
            )

        def _on_horizon_complete(self, sim_time: float) -> None:
            """Handle end-of-frames; score by hold time if the cube was held.

            Reaching the horizon with the cube still up is a successful hold, so
            it is scored by hold time. If the cube was never picked up, the
            no-pickup penalty applies.

            Args:
                sim_time: Simulation time when the horizon was reached.
            """
            if self.was_picked_up:
                score, reason = self._compute_score()
                self._finish_run(
                    score, f"horizon complete t={sim_time:.2f}s held — {reason}"
                )
            else:
                self._finish_run(
                    self.cfg.no_pickup_penalty,
                    f"horizon complete t={sim_time:.2f}s — never picked up",
                )

        def _finish_run(
            self, score: float | None, reason: str, *, pruned: bool = False
        ) -> None:
            """Finalize the run by writing either a score or a pruned marker.

            Args:
                score: Final score, or None to force a pruned result.
                reason: Human-readable stop reason written to trial_state.json.
                pruned: If True, write pruned state regardless of score.
            """
            if pruned or score is None:
                self.writer.prune(reason)
                return
            self.writer.write_score(score, reason)

        # ─────────────────────────────────────────────────────────────────────

        def _compute_score(self) -> tuple[float, str]:
            """Return the final (score, reason) for this run.

            Returns:
                Tuple of (hold_time, reason_string).
            """
            return self.hold_time, f"hold_time={self.hold_time:.2f}s"

        def onAnimateBeginEvent(self, event):
            """Run scoring logic and motor replay at the start of each simulation step."""
            if self.writer.finished:
                return

            sim_time = self.sim_time
            step_dt = float(self.rootnode.dt.value)
            self._loop_sim_time = sim_time
            self.frame = timeline_frame_at(sim_time, self.total_frames)
            self._update_overload_mass()

            cube_y = handle_cube_spawn(self, sim_time)
            if self.cube_has_spawned and cube_y is None:
                cube_y = get_cube_y(self.rootnode)
                ensure_drop_threshold_initialized(self, cube_y)

            self.writer.write_status(
                {
                    "state": "running",
                    "current_frame": self.frame,
                    "total_frames": self.total_frames,
                    "sim_time": sim_time,
                    "cube_y": cube_y,
                    "phase": current_phase(sim_time, self.recorded_duration),
                    "hold_time": self.hold_time,
                },
                min_interval=scene_defaults.STATUS_WRITE_INTERVAL,
            )

            if self.cube_has_spawned and cube_y is not None:
                if apply_scoring_rules(self, sim_time, cube_y, step_dt):
                    return

            if sim_time >= self.total_duration:
                self._on_horizon_complete(sim_time)
                return

            # Replay recorded motor positions; hold the last frame during overload
            positions = (
                interpolated_motor_positions(
                    sim_time,
                    self.playback.motor_positions,
                    self.playback.recording_dt,
                    self.time_scale,
                )
                if sim_time < self.recorded_duration
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
                    f"  phase={current_phase(sim_time, self.recorded_duration)}"
                    f"  peak={self.peak_y:.2f}"
                    f"  hold={self.hold_time:.2f}s"
                    f"  picked={self.was_picked_up}",
                    flush=True,
                )

            if self._post_spawn_slow_frames > 0:
                self._post_spawn_slow_frames -= 1
                if self._post_spawn_slow_frames == 0:
                    self.rootnode.dt.value = DT_DIRECT

            self.physics_step += 1
            self.sim_time += step_dt

        def onAnimateEndEvent(self, event):
            """Run the spawn-contact check at the end of each simulation step."""
            if self.writer.finished:
                return
            check_spawn_contact_window(self, self.sim_time)
            if self._debug_contacts and self.cube_has_spawned:
                self._log_contact_normals()

        def _log_contact_normals(self) -> None:
            """Print live cube motion and the real gripper↔cube contact geometry.

            Aggregates the point↔triangle and line↔line listeners that
            MinProximityIntersection actually populates, split by finger (sign
            of the contact-point X), logged every 5 steps:
              nC      — total real contact count across all channels.
              normalY — mean Y of contact push directions. Positive = cube is
                        being pushed up (the climb signature).
              +X/-X   — per-finger contact count and mean contact height (Y).
                        Unequal heights = the two fingers grip off-balance.
              Vy      — cube vertical velocity. Positive = climbing.
              w       — cube angular velocity. Large = tumbling.
            """
            if self.physics_step % 5 != 0:
                return

            normals_y: list[float] = []
            # Per side: [contact count, summed contact height].
            side_stats = {"+X": [0, 0.0], "-X": [0, 0.0]}
            for suffix in ("gPcT", "gTcP", "gLcL"):
                try:
                    listener = self.rootnode.Simulation.getObject(
                        f"cubeGripperContactDbg_{suffix}"
                    )
                    contacts = listener.getContactPoints() or []
                except Exception:
                    continue
                for _m1, p1, _m2, p2 in contacts:
                    dx, dy, dz = p2[0] - p1[0], p2[1] - p1[1], p2[2] - p1[2]
                    length = (dx * dx + dy * dy + dz * dz) ** 0.5
                    if length <= 1e-9:
                        continue
                    normals_y.append(dy / length)
                    side = "+X" if (p1[0] + p2[0]) >= 0 else "-X"
                    side_stats[side][0] += 1
                    side_stats[side][1] += (p1[1] + p2[1]) / 2.0

            cube_mo = self.cube_handles.cube.getMechanicalState()
            vel = cube_mo.velocity.value[0]
            cube_y = cube_mo.position.value[0][1]
            normal_y = (
                f"{sum(normals_y) / len(normals_y):+.3f}" if normals_y else "n/a"
            )

            # The gripper is the only actor that can inject the ejection energy.
            # Track its finger-tip height (lowest collision vertex) and the
            # vertical velocity of that tip by finite difference across the log
            # interval, so we can see whether the gripper itself is sweeping up
            # when the cube launches.
            grip_pos = self.gripper_collision.getMechanicalState().position.value
            grip_tip_y = min(p[1] for p in grip_pos)
            prev_y = getattr(self, "_prev_grip_tip_y", None)
            prev_t = getattr(self, "_prev_grip_tip_t", None)
            if prev_y is not None and self.sim_time > prev_t:
                grip_tip_vy = (grip_tip_y - prev_y) / (self.sim_time - prev_t)
            else:
                grip_tip_vy = 0.0
            self._prev_grip_tip_y = grip_tip_y
            self._prev_grip_tip_t = self.sim_time

            def _side_text(label: str) -> str:
                count, height_sum = side_stats[label]
                height = f"{height_sum / count:7.2f}" if count else "    n/a"
                return f"{label}:n={count:2d} h={height}"

            print(
                f"[contactdbg] t={self.sim_time:5.2f} nC={len(normals_y):2d} "
                f"normalY={normal_y:>6} cubeY={cube_y:7.2f} Vy={vel[1]:+8.1f} "
                f"w=({vel[3]:+.2f},{vel[4]:+.2f},{vel[5]:+.2f}) "
                f"gripTipY={grip_tip_y:7.2f} gripVy={grip_tip_vy:+8.1f} "
                f"| {_side_text('+X')} {_side_text('-X')}",
                flush=True,
            )

    return BasePlaybackController
