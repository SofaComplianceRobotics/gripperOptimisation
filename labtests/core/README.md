# labtests/core/

Shared infrastructure for every ShapeOPT test. All scene files import from here — nothing test-specific lives in this package.

---

## Public modules

**`base_scene.py`** — `build_base_scene(rootnode, *, inverse, friction, multithreading)` → `SceneNodes | None`

The single call that every test's `createScene()` makes first. Configures the root node, builds the Emio robot, attaches legs, and returns a `SceneNodes` named-tuple with `(rootnode, settings, modelling, simulation, emio)`. Returns `None` if the robot mesh is invalid — callers must check and bail. Part names come from `names.py`. `multithreading` defaults off (optimization runs many SOFA processes in parallel); the manual scenes pass `True`.

**`scene_defaults.py`** — default physics and scoring values

Single source for the direct-mode scene constants (friction, cube spawn/mass, pickup thresholds, scoring penalties). Scenes run standalone on these values; no env vars required.

**`scene_config.py`** — config resolution objects

Two frozen dataclasses populated at scene startup:
- `OptunaMeta.from_env()` — the five values every test needs to write scores: `trial_state_path`, `run_slot`, `gen`, `trial`, `run`. All zero/None when launched outside the optimizer.
- `PlaybackConfig.from_env(lab_root)` — full config for direct-mode tests: mesh path, friction, cube physics, scoring thresholds, mass ramp. Values come from `scene_defaults.py`, individually overridable per-process via the matching env var (e.g. `CUBE_MASS_MAX`). Embeds an `OptunaMeta` as `.meta`.

**`scoring.py`** — `ScoreWriter`

Handles all JSON output for one simulation run. Writes to `trial_state.json` via a file-lock so parallel runs don't corrupt each other. Three methods:
- `write_status(payload)` — live progress update, best-effort (never kills the sim on error).
- `write_score_and_stop(score, reason)` — marks run `"done"`, stops simulation via `os.kill(pid, 9)`.
- `write_pruned_and_stop(reason)` — marks run `"pruned"`, same stop mechanism. Both are idempotent.

**`playback_controller.py`** — `make_playback_controller(Sofa.Core.Controller)` → class

Factory that returns `BasePlaybackController` bound to the live SOFA controller class (which only exists inside an active session). The returned class handles the full motor-playback loop: cube spawn, mass ramp, hold-time scoring, and run termination. Four override hooks for test variants:

| Hook | Default behaviour |
|---|---|
| `_initial_cube_mass()` | Returns `cfg.cube_mass_start` |
| `_update_overload_mass()` | Ramps mass from start → max during overload phase |
| `_on_horizon_complete(sim_time)` | Writes pruned result |
| `_finish_run(score, reason, pruned)` | Delegates to `write_score_and_stop` or `write_pruned_and_stop` |

**`plugins.py`** — `add_required_plugins(simulation_node)`

Registers the 16 SOFA component plugins required for direct-mode collision simulation. Called once in `createScene()` after `build_base_scene()`.

---

## Private modules

**`_loop_phases.py`** — per-frame logic extracted from `BasePlaybackController.onAnimateBeginEvent`

Stateless functions that take the controller instance explicitly, making the phase logic testable without subclassing. Key functions: `handle_cube_spawn`, `apply_scoring_rules`, `check_spawn_contact_window`, `ensure_drop_threshold_initialized`, `current_phase`, `timeline_frame_at`, `playback_index_at`.

**`_sim_query.py`** — low-level SOFA node reads and writes

Thin wrappers around SOFA mechanical state access: `get_cube_y`, `set_cube_mass`, `get_cube_collision_min_y`, `get_gripper_collision_min_y`, `spawn_overlap_detected`. All return `None` or a safe default on error so they never crash a running scene.

---

## modules/ subpackage

Optional scene components. Each exposes a single `setup()` function that takes SOFA nodes and returns handles:

| Module | Import alias | What it adds |
|---|---|---|
| `collision_stl.py` | `setup_collision` | Gripper collision mesh from STL |
| `cube_floor.py` | `setup_cube_floor` | Rigid cube + floor plane; returns `CubeFloorHandles` |
| `motor_playback.py` | `setup_playback` | Loads motor recording, wires `JointConstraints`; returns `PlaybackHandles` |
| `effector_target.py` | `setup_effector` | Effector target + ImGui drag handle; returns `EffectorHandles` |

Direct-mode tests use `collision_stl`, `cube_floor`, and `motor_playback`. Inverse-mode tests use `effector_target`.
