# labtests/core/

Shared infrastructure for every ShapeOPT test. All scene files import from
here; nothing test-specific lives in this package.

---

## Public modules

**`base_scene.py`** — `build_base_scene(rootnode, *, inverse, friction=0.6, multithreading=False)` → `SceneNodes | None`

The first call every test's `createScene()` makes. Configures the root node,
picks the inverse or direct SOFA header, builds the Emio robot, and attaches
the legs (this trial's generated leg via `OPT_LEG_NAME`, else the stock
blueleg). Returns a `SceneNodes` named-tuple `(rootnode, settings, modelling,
simulation, emio)`, or `None` if the robot mesh is invalid — callers must
check and bail. `multithreading` is off for optimization runs (many parallel
SOFA processes) and on for the interactive manual scenes.

**`scene_defaults.py`** — default physics and scoring constants for direct
mode (friction, cube spawn/mass, pickup thresholds, scoring penalties, mass
ramp). Scenes run standalone on these; env vars override individually.

**`scene_config.py`** — `PlaybackConfig`, a frozen dataclass built by
`PlaybackConfig.from_env(lab_root)` at scene startup. Holds the two finger
mesh paths, all direct-mode physics and scoring values (each from
`scene_defaults.py` unless its env var is set), and `.trial` — the
`sofaopt.scene.Trial` handle from `open_trial()`.

**`scoring.py`** — `max_hold_score(recording_file, run_count=1)`. The only
thing left here now that sofaopt owns score writing: the lab-specific score
ceiling, derived from a motor recording's length plus overload time minus the
pre-pickup gate, so a 100% hold always normalizes to 1.0.

**`playback_controller.py`** — `make_playback_controller(Sofa.Core.Controller)` → class

Factory returning `BasePlaybackController` bound to the live SOFA controller
class (which only exists inside an active session). The class runs the full
motor-playback loop: cube spawn, mass ramp, hold-time scoring, run
termination. Override hooks for variants:

| Hook | Default |
|---|---|
| `_initial_cube_mass()` | `cfg.cube_mass_start` |
| `_update_overload_mass()` | ramp mass start → max during overload |
| `_on_horizon_complete(sim_time)` | score by hold time (no-pickup penalty if never lifted) |
| `_finish_run(score, reason, pruned)` | `writer.write_score` or `writer.prune` |

**`plugins.py`** — `add_required_plugins(simulation_node)`. Registers the 16
SOFA component plugins for direct-mode collision. Called once in
`createScene()` after `build_base_scene()`.

**`playback_controller` companions** — `_loop_phases.py` and `_sim_query.py`
below.

---

## Private modules

**`_loop_phases.py`** — per-frame logic pulled out of
`BasePlaybackController.onAnimateBeginEvent` as stateless functions that take
the controller explicitly, so the phase logic is testable without
subclassing. Functions: `current_phase`, `timeline_frame_at`,
`interpolated_motor_positions`, `ensure_drop_threshold_initialized`,
`check_spawn_contact_window`, `handle_cube_spawn`, `apply_scoring_rules`.

**`_sim_query.py`** — thin wrappers around SOFA mechanical-state access:
`get_cube_y`, `set_cube_mass`, `get_cube_collision_min_y`,
`get_gripper_collision_min_y`, `collision_aabb`,
`get_cube_gripper_contact_count`, `spawn_overlap_detected`,
`set_gripper_collision_active`. All return `None` or a safe default on error
so they never crash a running scene.

---

## modules/ subpackage

Optional scene components. Each exposes one `setup()` that takes SOFA nodes
and returns handles:

| Module | Import alias | Adds |
|---|---|---|
| `collision_stl.py` | `setup_collision` | Two per-finger collision meshes (own SOFA group each → fingers can collide with each other) |
| `cube_floor.py` | `setup_cube_floor` | Rigid cube + floor plane; returns `CubeFloorHandles` |
| `motor_playback.py` | `setup_playback` | Loads a motor recording, wires `JointConstraints`; returns `PlaybackHandles` |
| `effector_target.py` | `setup_effector` | Effector target + ImGui drag handle; returns `EffectorHandles` |
| `motor_recorder.py` | — | `RecordingController`: captures motor positions per frame, used by the recording scenes |

Direct-mode tests use `collision_stl`, `cube_floor`, `motor_playback`.
Inverse-mode tests use `effector_target`.
