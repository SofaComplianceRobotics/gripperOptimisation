"""Per-frame logic phases for the playback controller.

Each function handles one conceptual phase of onAnimateBeginEvent and takes
the controller instance explicitly so the phases can be tested or reused
without inheriting from the controller.
"""

from __future__ import annotations

from geometry.timing_config import DT_DIRECT

from labtests.core._sim_query import (
    get_cube_collision_min_y,
    get_gripper_collision_min_y,
    set_gripper_collision_active,
    spawn_overlap_detected,
)


# ── Timeline helpers ──────────────────────────────────────────────────────────


def current_phase(sim_time: float, recorded_duration: float) -> str:
    """Return which phase the simulation is in.

    Args:
        sim_time: Current simulation time in seconds.
        recorded_duration: Duration of the recorded motor playback in seconds.

    Returns:
        ``'recorded'`` during motor playback, ``'overload'`` after it ends.
    """
    return "recorded" if sim_time < recorded_duration else "overload"


def timeline_frame_at(sim_time: float, total_frames: int) -> int:
    """Map a simulation time to its DT_DIRECT frame index.

    Args:
        sim_time: Current simulation time in seconds.
        total_frames: Total number of frames in the simulation.

    Returns:
        Frame index clamped to [0, total_frames].
    """
    if sim_time <= 0.0:
        return 0
    return min(total_frames, int(sim_time / DT_DIRECT))


def interpolated_motor_positions(
    sim_time: float,
    motor_positions: list[list[float]],
    recording_dt: float,
    time_scale: float = 1.0,
) -> list[float]:
    """Return motor positions for the current sim time, lerped between frames.

    The recording timeline is mapped to simulation time through its own capture
    interval, so a trajectory recorded at any dt replays at its true rate
    (divided by ``time_scale``). Linear interpolation between neighbouring
    frames keeps the commanded motor motion smooth at every physics step
    instead of jumping one full recorded frame at a time.

    Args:
        sim_time: Current simulation time in seconds.
        motor_positions: Recorded frames, each a list of motor angles.
        recording_dt: Seconds between recorded frames.
        time_scale: Replay speed factor (1.0 = recorded rate).

    Returns:
        Interpolated motor angles; the last frame once the recording ends.
    """
    n = len(motor_positions)
    if n == 0:
        return []
    frame_pos = max(0.0, sim_time) * time_scale / recording_dt
    index = int(frame_pos)
    if index >= n - 1:
        return list(motor_positions[-1])
    frac = frame_pos - index
    current, following = motor_positions[index], motor_positions[index + 1]
    return [a + (b - a) * frac for a, b in zip(current, following)]


# ── Spawn phase ───────────────────────────────────────────────────────────────


def ensure_drop_threshold_initialized(ctrl, cube_y: float) -> None:
    """Compute and store pick/drop thresholds from the cube's spawn position.

    Called once on the first frame after the cube appears. The thresholds are
    relative to spawn_y so they remain consistent regardless of table height.

    Args:
        ctrl: Playback controller instance.
        cube_y: Y position of the cube at spawn.
    """
    if ctrl.spawn_cube_y is not None:
        return
    ctrl.spawn_cube_y = float(cube_y)
    ctrl.drop_y_threshold = ctrl.spawn_cube_y - ctrl.cfg.drop_below_spawn_tol
    ctrl.pickup_y_threshold = ctrl.spawn_cube_y + ctrl.cfg.pickup_above_spawn_tol
    print(
        f"[Scoring] spawn_y={ctrl.spawn_cube_y:.2f} | "
        f"pickup>={ctrl.pickup_y_threshold:.2f} | "
        f"drop<{ctrl.drop_y_threshold:.2f}"
    )


def check_spawn_contact_window(ctrl, sim_time: float) -> None:
    """Penalise the run if the cube contacts the gripper immediately after spawn.

    Runs for a small number of frames post-spawn to catch grippers that were
    already inside the cube when it teleported in.

    Args:
        ctrl: Playback controller instance.
        sim_time: Current simulation time in seconds.
    """
    if ctrl.spawn_contact_check_frames <= 0 or ctrl.writer.finished:
        return
    if spawn_overlap_detected(ctrl.rootnode, ctrl.gripper_collision):
        ctrl.writer.write_score_and_stop(
            ctrl.cfg.early_contact_penalty,
            f"cube touched gripper at spawn window t={sim_time:.2f}s",
        )
        return
    ctrl.spawn_contact_check_frames -= 1


def handle_cube_spawn(ctrl, sim_time: float) -> float | None:
    """Teleport the cube to spawn or hold it at the pre-spawn offset.

    The cube is held above the workspace until ``cube_spawn_time`` so the
    gripper can settle before the cube appears. On the spawn frame it is
    teleported with zeroed velocity for a fully reproducible starting state.

    Args:
        ctrl: Playback controller instance.
        sim_time: Current simulation time in seconds.

    Returns:
        cube_y on the spawn frame, None on all other frames.
    """
    cube_mo = ctrl.rootnode.Simulation.Cube.getMechanicalState()
    if not ctrl.cube_has_spawned and sim_time >= ctrl.cfg.cube_spawn_time:
        cube_mo.position.value = [
            [0.0, ctrl.cube_handles.cube_spawn_y, 0.0, 0.0, 0.0, 0.0, 1.0]
        ]
        cube_mo.velocity.value = [[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]]
        ctrl.cube_has_spawned = True
        # Gripper has reached its start pose clear of the floor; restore its
        # collision so it can land on the floor and grasp the cube.
        set_gripper_collision_active(ctrl.gripper_collision, True)
        ctrl.spawn_contact_check_frames = 2
        ctrl._post_spawn_slow_frames = 2
        cube_y = float(ctrl.cube_handles.cube_spawn_y)
        ensure_drop_threshold_initialized(ctrl, cube_y)
        print(f"[Spawn] cube spawned at t={sim_time:.2f}s")
        check_spawn_contact_window(ctrl, sim_time)
        return cube_y
    elif not ctrl.cube_has_spawned:
        # Keep the cube out of the workspace while the gripper is settling
        cube_mo.position.value = [
            [
                0.0,
                ctrl.cube_handles.cube_spawn_y + ctrl.cfg.cube_prespawn_offset,
                0.0,
                0.0,
                0.0,
                0.0,
                1.0,
            ]
        ]
        cube_mo.velocity.value = [[0.0, 0.0, 0.0, 0.0, 0.0, 0.0]]
    return None


# ── Scoring phase ─────────────────────────────────────────────────────────────


def apply_scoring_rules(ctrl, sim_time: float, cube_y: float, step_dt: float) -> bool:
    """Evaluate all scoring rules for the current frame.

    Rules are checked in priority order; the first one that fires stops the run
    immediately and returns True so the caller can skip the rest of the frame.

    Args:
        ctrl: Playback controller instance.
        sim_time: Current simulation time in seconds.
        cube_y: Current cube Y position.
        step_dt: Physics timestep for this frame in seconds.

    Returns:
        True if the run was terminated this frame, False otherwise.
    """
    if cube_y > ctrl.peak_y:
        ctrl.peak_y = cube_y

    if ctrl.cfg.enable_undercube_check:
        cube_min_y = get_cube_collision_min_y(ctrl.rootnode)
        gripper_min_y = get_gripper_collision_min_y(ctrl.gripper_collision)
        if cube_min_y is not None and gripper_min_y is not None:
            if gripper_min_y < (cube_min_y - ctrl.cfg.undercube_margin):
                ctrl._finish_run(
                    ctrl.cfg.undercube_penalty,
                    f"undercube geometry t={sim_time:.2f}s "
                    f"gripper_min_y={gripper_min_y:.2f} < cube_min_y={cube_min_y:.2f}",
                )
                return True

    if cube_y > float(ctrl.pickup_y_threshold):
        ctrl.was_picked_up = True

    if ctrl.was_picked_up and cube_y < float(ctrl.drop_y_threshold):
        ctrl.dropped = True

    if sim_time >= ctrl.cfg.early_stop_sim_time and cube_y > float(ctrl.pickup_y_threshold):
        ctrl.hold_time += step_dt

    # Rule 1: cube through floor — physics glitch if it was already picked up,
    # otherwise a clean no-pickup failure
    if cube_y < ctrl.cfg.floor_y_threshold:
        if ctrl.was_picked_up:
            ctrl._finish_run(
                None,
                f"cube glitched through floor after pickup t={sim_time:.2f}s",
                pruned=True,
            )
        else:
            ctrl._finish_run(
                ctrl.cfg.no_pickup_penalty,
                f"cube through floor t={sim_time:.2f}s — "
                f"no_pickup_penalty={ctrl.cfg.no_pickup_penalty:.2f} "
                f"hold_time={ctrl.hold_time:.2f}s",
            )
        return True

    # Rule 2: gripper never picked the cube up before the early-stop gate
    if sim_time >= ctrl.cfg.early_stop_sim_time and not ctrl.was_picked_up:
        ctrl._finish_run(
            ctrl.cfg.no_pickup_penalty,
            f"pickup gate failed t={sim_time:.2f}s — "
            f"no_pickup_penalty={ctrl.cfg.no_pickup_penalty:.2f} "
            f"hold_time={ctrl.hold_time:.2f}s",
        )
        return True

    # Rule 3: cube was picked up and then dropped — successful probe, record hold time
    if ctrl.was_picked_up and cube_y < float(ctrl.drop_y_threshold):
        score, reason = ctrl._compute_score()
        ctrl._finish_run(
            score,
            f"probe_success: dropped t={sim_time:.2f}s "
            f"phase={current_phase(sim_time, ctrl.recorded_duration)} "
            f"cube_y={cube_y:.2f} < drop_y={float(ctrl.drop_y_threshold):.2f} — {reason}",
        )
        return True

    return False
