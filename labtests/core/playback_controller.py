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
    _on_horizon_complete(t)         end-of-frames action   (default: write_pruned_and_stop)
"""

from __future__ import annotations

from geometry.timing_config import DT_CONTACT, DT_DIRECT

from labtests.core._loop_phases import (
    apply_scoring_rules,
    check_spawn_contact_window,
    current_phase,
    ensure_drop_threshold_initialized,
    handle_cube_spawn,
    playback_index_at,
    timeline_frame_at,
)
from labtests.core._sim_query import get_cube_y, set_cube_mass


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
            self.recorded_duration = self.recorded_frames * DT_DIRECT
            self.overload_frames = max(0, int(cfg.overload_max_time / DT_DIRECT))
            self.total_frames = self.recorded_frames + self.overload_frames
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
            set_cube_mass(rootnode, self._initial_cube_mass())
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
            """Ramp cube mass from start to max during the overload phase."""
            loop_sim_time = getattr(self, "_loop_sim_time", self.sim_time)
            if loop_sim_time < self.recorded_duration:
                set_cube_mass(self.rootnode, self.cfg.cube_mass_start)
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
            """Handle end-of-frames; default writes a pruned result.

            Args:
                sim_time: Simulation time when the horizon was reached.
            """
            self._finish_run(None, f"horizon complete t={sim_time:.2f}s", pruned=True)

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
                self.writer.write_pruned_and_stop(reason)
                return
            self.writer.write_score_and_stop(score, reason)

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
                }
            )

            if self.cube_has_spawned and cube_y is not None:
                if apply_scoring_rules(self, sim_time, cube_y, step_dt):
                    return

            if sim_time >= self.total_duration:
                self._on_horizon_complete(sim_time)
                return

            # Replay recorded motor positions; hold the last frame during overload
            positions = (
                self.playback.motor_positions[playback_index_at(sim_time, self.recorded_frames)]
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

    return BasePlaybackController
