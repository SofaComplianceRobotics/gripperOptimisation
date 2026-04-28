# Adding a New ShapeOPT Test — Step-by-Step Guide

This guide walks you through creating a brand new test from scratch.
No prior knowledge assumed.

---

## What is a "test"?

A test is one way to evaluate a gripper shape. The optimizer runs your scene
hundreds of times with different gripper geometries and collects a **score**
for each one. A higher score = a better shape.

You define:
- **What the robot does** (replay recorded motors, or move to a target)
- **How to score it** (how long it held a cube, how level it stayed, etc.)

---

## How tests are discovered

The system **auto-scans** every subfolder of `labtests/`. A folder becomes
a valid test when it contains exactly these three files:

```
labtests/
└── my_new_test/
    ├── test.json      ← display name, description, run count
    ├── scene.py       ← the SOFA simulation scene
    └── scoring.py     ← scoring constants (MAX_SCORE, labels)
```

No registration needed. Create the files and the test appears in the UI.

---

## Step 1 — Create the folder

```
app/src/labtests/my_new_test/
```

Optionally add an empty `__init__.py` so editors treat it as a package:

```
touch app/src/labtests/my_new_test/__init__.py
```

---

## Step 2 — Write `test.json`

This file controls how the test appears in the picker UI and how many
simulation runs the optimizer launches per trial.

```json
{
  "label": "My New Test",
  "description": "One sentence describing what this test measures",
  "default_selected": false,
  "run_count": 1
}
```

| Field              | What it does                                                    |
|--------------------|-----------------------------------------------------------------|
| `label`            | Short name shown in the test picker                             |
| `description`      | Subtitle shown next to the label                                |
| `default_selected` | If `true`, this test is pre-checked when the picker opens       |
| `run_count`        | How many parallel simulation runs the optimizer does per trial  |

> Set `run_count` > 1 when your test has randomness (e.g. random cube sizes)
> and you want to average across multiple runs.

---

## Step 3 — Write `scoring.py`

This file is pure metadata — no logic required. The optimizer and analysis
tools use it to label and normalize scores.

```python
SCORE_KEY         = "score"
TEST_NAME         = "my_new_test"
TEST_LABEL        = "My New Test"
TEST_DESCRIPTION  = "What the score number actually measures"
MAX_SCORE         = 20.0
```

| Constant           | What it does                                                    |
|--------------------|-----------------------------------------------------------------|
| `SCORE_KEY`        | Always `"score"` — key used in the output JSON                  |
| `TEST_NAME`        | Snake-case name, matches your folder name                       |
| `TEST_LABEL`       | Human-readable label for charts and logs                        |
| `TEST_DESCRIPTION` | One sentence for tooltips / reports                             |
| `MAX_SCORE`        | The theoretical best possible score (used for normalization)    |

---

## Step 4 — Write `scene.py`

This is the main file. It must define a single function:

```python
def createScene(rootnode):
    ...
    return rootnode
```

SOFA calls `createScene` once at startup. You build the simulation inside it.

There are **two modes** to choose from:

---

### Mode A — Direct mode (Collisions)

Use this when your test needs collisions, you will need to record the motor positions because it is not possible to set pointer positions. please refer to the documentation related to the recording scene.

**When to use:** grasp tasks, pick-and-hold, anything with collision.

```python
"""Scene: my_new_test — direct mode."""

import os
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Path bootstrap — copy these three lines verbatim into every scene.py.
# ---------------------------------------------------------------------------
sys.path.insert(0, str(next(c for c in Path(__file__).parents if (c / "labtests").is_dir())))
from labtests.core.scene_paths import ensure_scene_paths

SCRIPT_DIR, SRC_ROOT, APP_ROOT, LAB_ROOT = ensure_scene_paths(__file__)


# ---------------------------------------------------------------------------
# Load all env-var config at module level (before createScene runs).
# PlaybackConfig reads 30+ SHAPEOPT_* and OPTUNA_* environment variables.
# ---------------------------------------------------------------------------
from labtests.core.scene_config import PlaybackConfig

cfg = PlaybackConfig.from_env(LAB_ROOT)

# Path to the motor recording file for this test
RECORD_FILE = str(
    LAB_ROOT / "runtime" / "recordings" / "my_new_test" / "motor_recording.json"
)

DT = 0.01  # simulation timestep in seconds


# ---------------------------------------------------------------------------
# createScene — SOFA calls this once at startup
# ---------------------------------------------------------------------------
def createScene(rootnode):
    import Sofa.Core
    from labtests.core.base_scene import build_base_scene
    from labtests.core.modules.collision_stl import setup as setup_collision
    from labtests.core.modules.cube_floor import setup as setup_cube_floor
    from labtests.core.modules.motor_playback import setup as setup_playback
    from labtests.core.playback_controller import make_playback_controller
    from labtests.core.plugins import add_required_plugins
    from labtests.core.scoring import ScoreWriter

    # 1. Build the base scene (robot + solvers + gravity).
    #    Returns a SceneNodes named-tuple or None on failure.
    nodes = build_base_scene(rootnode, inverse=False, friction=cfg.friction_coef)
    if nodes is None:
        return

    # 2. Register the SOFA plugins needed for collision and contact.
    add_required_plugins(nodes.simulation)
    rootnode.dt = DT

    # 3. Add the gripper collision mesh (reads path from env via cfg).
    gripper_collision = setup_collision(nodes.emio, cfg.gripper_mesh_path)

    # 4. Add the cube and floor rigid bodies.
    cube_handles = setup_cube_floor(
        nodes.simulation,
        gripper_collision,
        cube_scale=[8, 8, 8],           # cube size in mm — tweak as needed, generaly somewhere between 5 and 20 works
        cube_mass=cfg.cube_mass_start,
        floor_center_y=cfg.floor_center_y,
        cube_spawn_clearance=cfg.cube_spawn_clearance,
    )

    # 5. Load the motor recording and attach JointConstraints.
    playback = setup_playback(nodes.emio, RECORD_FILE)

    # 6. Create the score writer (handles JSON output + stopping the sim).
    writer = ScoreWriter(
        rootnode,
        run_info=cfg.meta.run_info,
        trial_state_path=cfg.meta.trial_state_path,
        run_slot=cfg.meta.run_slot,
    )

    # 7. Attach the base controller — it handles the full simulation loop:
    #    cube spawn, motor replay, pickup/drop detection, and scoring.
    Base = make_playback_controller(Sofa.Core.Controller)
    nodes.simulation.addObject(
        Base(
            name="PlaybackController",
            rootnode=rootnode,
            playback=playback,
            cube_handles=cube_handles,
            gripper_collision=gripper_collision,
            writer=writer,
            cfg=cfg,
        )
    )
    return rootnode
```

The default `BasePlaybackController` scores by **hold time** — how many
seconds the cube stays lifted above the spawn height after the recording ends.
That's often all you need.

---

### Mode A (variant) — Custom scoring or cube logic

If you need different scoring or cube behavior, subclass the base controller
and override only the hooks you care about:

```python
def createScene(rootnode):
    import Sofa.Core
    from labtests.core.base_scene import build_base_scene
    from labtests.core.modules.collision_stl import setup as setup_collision
    from labtests.core.modules.cube_floor import setup as setup_cube_floor
    from labtests.core.modules.motor_playback import setup as setup_playback
    from labtests.core.playback_controller import make_playback_controller
    from labtests.core.plugins import add_required_plugins
    from labtests.core.scoring import ScoreWriter

    nodes = build_base_scene(rootnode, inverse=False, friction=cfg.friction_coef)
    if nodes is None:
        return

    add_required_plugins(nodes.simulation)
    rootnode.dt = DT

    gripper_collision = setup_collision(nodes.emio, cfg.gripper_mesh_path)
    cube_handles = setup_cube_floor(nodes.simulation, gripper_collision)
    playback = setup_playback(nodes.emio, RECORD_FILE)
    writer = ScoreWriter(
        rootnode,
        run_info=cfg.meta.run_info,
        trial_state_path=cfg.meta.trial_state_path,
        run_slot=cfg.meta.run_slot,
    )

    Base = make_playback_controller(Sofa.Core.Controller)

    # -----------------------------------------------------------------------
    # Subclass and override only what you need to change.
    # -----------------------------------------------------------------------
    class MyController(Base):

        def _initial_cube_mass(self) -> float:
            """Return the cube mass at spawn time."""
            return 0.05  # 50 g fixed

        def _update_overload_mass(self) -> None:
            """Called every frame — use this to ramp or keep mass fixed."""
            self._set_cube_mass(0.05)  # keep mass constant (no ramp)

        def _on_horizon_complete(self, sim_time: float) -> None:
            """Called when the motor recording finishes."""
            score = self.hold_time + 2.0  # add a finish bonus
            self.writer.write_score_and_stop(
                score, f"horizon done at t={sim_time:.2f}s"
            )

    nodes.simulation.addObject(
        MyController(
            name="PlaybackController",
            rootnode=rootnode,
            playback=playback,
            cube_handles=cube_handles,
            gripper_collision=gripper_collision,
            writer=writer,
            cfg=cfg,
        )
    )
    return rootnode
```

---

### Mode B — Inverse mode (effector target control)

Use this when you dont use collisions. this will ensure a easier movement since you can declare the points you want
instead of recording motor positions.

**When to use:** alignment tests, tilt tests, pose-accuracy tests.

```python
"""Scene: my_new_test — inverse mode."""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(next(c for c in Path(__file__).parents if (c / "labtests").is_dir())))
from labtests.core.scene_paths import ensure_scene_paths

SCRIPT_DIR, SRC_ROOT, APP_ROOT, LAB_ROOT = ensure_scene_paths(__file__)


from labtests.core.scene_config import OptunaMeta

META = OptunaMeta.from_env()

# Waypoints: each entry is ([x, y, z, qx, qy, qz, qw], hold_frames)
# it is pointless to change the rotations, emio is not capable of that (at least not yet)
# The gripper will move to each position and hold for that many frames.
_WAYPOINTS_ENV = os.environ.get("SHAPEOPT_TILT_WAYPOINTS", "")
WAYPOINTS = json.loads(_WAYPOINTS_ENV) if _WAYPOINTS_ENV else [
    ([0,  -150, 40, 0, 0, 0, 1], 10),
    ([40, -150,  0, 0, 0, 0, 1], 10),
]


def createScene(rootnode):
    import Sofa.Core
    from labtests.core.base_scene import build_base_scene
    from labtests.core.modules.effector_target import setup as setup_effector
    from labtests.core.scoring import ScoreWriter
    from parts.controllers.assemblycontroller import AssemblyController

    # Inverse mode: pass inverse=True. No collision mesh or cube needed.
    nodes = build_base_scene(rootnode, inverse=True)
    if nodes is None:
        return

    # AssemblyController waits for the robot to finish assembling before
    # your controller logic starts. Always add it in inverse mode.
    nodes.emio.addObject(AssemblyController(nodes.emio))

    # Add the effector target and ImGui controls.
    # initial_target_pos = [x, y, z, qx, qy, qz, qw]
    effector_handles = setup_effector(
        nodes,
        nodes.emio,
        initial_target_pos=[0, -150, 0, 0, 0, 0, 1],
    )

    writer = ScoreWriter(
        rootnode,
        run_info=META.run_info,
        trial_state_path=META.trial_state_path,
        run_slot=META.run_slot,
    )

    assembly_controller = nodes.emio.getObject("AssemblyController")

    class MyInverseController(Sofa.Core.Controller):
        def __init__(self, *args, **kwargs):
            Sofa.Core.Controller.__init__(self, *args, **kwargs)
            self.frame = 0
            self.waypoint_index = 0
            self.hold_frame = 0
            self.penalties = [0.0] * len(WAYPOINTS)

        def onAnimateBeginEvent(self, event):
            # Wait for the robot to finish assembling.
            if not assembly_controller.done:
                return

            # All waypoints done — write the final score and stop.
            if self.waypoint_index >= len(WAYPOINTS):
                if not writer.finished:
                    score = 40.0 - sum(self.penalties)
                    writer.write_score_and_stop(score, "sequence complete")
                return

            pos, hold_frames = WAYPOINTS[self.waypoint_index]

            # Move the target to the current waypoint position.
            effector_handles.target_mo.position.value = [pos]

            # Read where the effector points actually are.
            points = effector_handles.effector_mo.position.value

            # --- measure something here ---
            # Example: Y-axis spread between opposite effector points
            y_spread = abs(points[0][1] - points[2][1])
            if y_spread > self.penalties[self.waypoint_index]:
                self.penalties[self.waypoint_index] = y_spread

            # Advance to the next waypoint after hold_frames frames.
            self.hold_frame += 1
            if self.hold_frame >= hold_frames:
                self.hold_frame = 0
                self.waypoint_index += 1

            self.frame += 1

    nodes.simulation.addObject(MyInverseController(name="MyController"))
    return rootnode
```

---

### Mode C — Reuse an existing scene with different defaults

If your test is a small variant of an existing one, just override env vars
and re-export `createScene`:

```python
import os

os.environ.setdefault("SHAPEOPT_CUBE_WEIGHT_MIN", "0.05")
os.environ.setdefault("SHAPEOPT_CUBE_WEIGHT_MAX", "0.05")

from labtests.grasp_hold.scene import createScene as createScene  # noqa: F401
```

---

## Reference — What each core piece does

| Import | What it gives you |
|---|---|
| `build_base_scene(rootnode, inverse, friction)` | Builds the robot and solvers. Returns `SceneNodes` (or `None` on failure). |
| `add_required_plugins(simulation)` | Registers the 13 SOFA plugins needed for collision and contact. |
| `PlaybackConfig.from_env(lab_root)` | Reads all `SHAPEOPT_*` and `OPTUNA_*` env vars into one config object. |
| `OptunaMeta.from_env()` | Reads only the Optuna metadata vars (gen, trial, run, slot). |
| `setup_collision(emio, stl_path)` | Adds a gripper collision mesh. Returns a node you pass to `setup_cube_floor`. |
| `setup_cube_floor(simulation, gripper_collision, **kwargs)` | Adds the cube and floor. Returns `CubeFloorHandles`. |
| `setup_playback(emio, record_file)` | Loads a motor recording and wires up `JointConstraints`. Returns `PlaybackHandles`. |
| `setup_effector(nodes, emio, **kwargs)` | Adds the effector target + ImGui controls. Returns `EffectorHandles`. |
| `make_playback_controller(Sofa.Core.Controller)` | Returns `BasePlaybackController` (handles spawn, replay, pickup/drop, hold-time scoring). |
| `ScoreWriter(rootnode, run_info, trial_state_path, run_slot)` | Call `.write_score_and_stop(score, reason)` to finish or `.write_pruned_and_stop(reason)` to mark invalid. |

---

## Reference — `SceneNodes` fields

`build_base_scene` returns a `SceneNodes` named-tuple:

| Field | What it is |
|---|---|
| `rootnode` | The SOFA root node |
| `settings` | Plugin/header settings node |
| `modelling` | Modelling node |
| `simulation` | The node where you attach controllers and rigid bodies |
| `emio` | The robot node — pass to collision, playback, effector setups |

---

## Reference — Override hooks in `BasePlaybackController`

If you subclass the base controller, these are the hooks you can override:

| Method | When it's called | Default behavior |
|---|---|---|
| `_initial_cube_mass()` | Once at init, to set starting mass | Returns `cfg.cube_mass_start` |
| `_update_overload_mass()` | Every frame during overload phase | Ramps mass from start to max |
| `_on_horizon_complete(sim_time)` | When all recorded frames finish | Calls `write_pruned_and_stop` |

Inside your subclass you also have access to:
- `self.hold_time` — seconds the cube has been held above pickup threshold
- `self.writer` — the `ScoreWriter` instance
- `self.cfg` — the full `PlaybackConfig`
- `self._set_cube_mass(value)` — change the cube mass mid-simulation

---

## Reference — Environment variables

These are set automatically by the optimizer. You don't need to set them manually
during development unless you're running a scene directly.

| Variable | What it is |
|---|---|
| `OPTUNA_TRIAL_STATE_PATH` | Path to the JSON file where scores are written |
| `OPTUNA_RUN_SLOT` | Which slot this run occupies (0-indexed, for multi-run tests) |
| `OPTUNA_GEN` | Current optimizer generation |
| `OPTUNA_TRIAL` | Current trial number |
| `OPTUNA_RUN` | Current run number |
| `OPTUNA_STL_PATH` | Path to the gripper collision STL file |

---

## Checklist before submitting

- [ ] Folder created under `labtests/`
- [ ] `test.json` has `label`, `description`, `default_selected`, `run_count`
- [ ] `scoring.py` has `SCORE_KEY`, `TEST_NAME`, `TEST_LABEL`, `TEST_DESCRIPTION`, `MAX_SCORE`
- [ ] `scene.py` defines `createScene(rootnode)` and returns `rootnode`
- [ ] Path bootstrap (3-line `ensure_scene_paths` block) is at the top of `scene.py`
- [ ] `writer.write_score_and_stop(score, reason)` is called exactly once per run
- [ ] `MAX_SCORE` in `scoring.py` matches the highest realistic score your test can produce
