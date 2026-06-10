# labtests/

Each subfolder is one simulation test. The optimizer runs selected tests against every gripper candidate and collects a score. Higher score = better gripper.

---

## How discovery works

`registry.py` auto-scans all subfolders of `labtests/`. A folder becomes a valid test when it contains exactly:

```
labtests/
└── my_test/
    ├── test.json      ← display name, run count, aggregation
    ├── scene.py       ← SOFA scene (must define createScene)
    └── scoring.py     ← score constants (MAX_SCORE, labels)
```

No registration needed. Create the files and the test appears in the UI.

### `TestSpec` fields

| Field | Source | What it does |
|---|---|---|
| `name` | folder name | Unique identifier |
| `label` | `test.json` | Short name shown in the picker |
| `description` | `test.json` | Subtitle next to the label |
| `default_selected` | `test.json` | Pre-checked in the picker if `true` |
| `run_count` | `test.json` | Parallel simulation runs per trial |
| `score_aggregation` | `test.json` | How to combine multi-run scores (`"mean"`) |
| `max_score` | `scoring.py` `MAX_SCORE` | Theoretical best score (used for normalization) |

Set `run_count` > 1 when your test has randomness (random cube sizes, random spawn positions) and you want to average out variance across runs.

---

## Adding a new test

### Step 1 — Create the folder

```
labtests/my_new_test/
```

### Step 2 — Write `test.json`

```json
{
  "label": "My New Test",
  "description": "One sentence describing what this test measures",
  "default_selected": false,
  "run_count": 1
}
```

### Step 3 — Write `scoring.py`

Pure metadata — no logic. Used by the optimizer and analysis dashboard.

```python
SCORE_KEY         = "score"
TEST_NAME         = "my_new_test"
TEST_LABEL        = "My New Test"
TEST_DESCRIPTION  = "What the score number actually measures"
MAX_SCORE         = 20.0
```

`MAX_SCORE` should match the highest realistic score your test can produce. Used for normalization across tests.

### Step 4 — Write `scene.py`

Must define `createScene(rootnode)` and return `rootnode`. SOFA calls it once at startup.

Always start with the path bootstrap (copy verbatim):

```python
import sys
from pathlib import Path

sys.path.insert(
    0, str(next(c for c in Path(__file__).parents if (c / "labtests").is_dir()))
)
from launcher.bootstrap import bootstrap_lab

SCRIPT_DIR, SRC_ROOT, APP_ROOT, LAB_ROOT = bootstrap_lab(__file__)
```

---

## Scene modes

### Mode A — Direct (collision-based)

Use when the test needs physical contact: grasp, pick-and-hold, anything with a cube.
Motor positions must be pre-recorded (inverse mode can't run with collisions).

```python
from labtests.core.scene_config import PlaybackConfig
cfg = PlaybackConfig.from_env(LAB_ROOT)

RECORD_FILE = str(LAB_ROOT / "runtime" / "recordings" / "my_new_test" / "motor_recording.json")
DT = 0.01

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
    cube_handles = setup_cube_floor(
        nodes.simulation,
        gripper_collision,
        cube_scale=[8, 8, 8],       # mm — typically 5–20 works
        cube_mass=cfg.cube_mass_start,
        floor_center_y=cfg.floor_center_y,
        cube_spawn_clearance=cfg.cube_spawn_clearance,
    )
    playback = setup_playback(nodes.emio, RECORD_FILE)
    writer = ScoreWriter(
        rootnode,
        run_info=cfg.meta.run_info,
        trial_state_path=cfg.meta.trial_state_path,
        run_slot=cfg.meta.run_slot,
    )

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

The default `BasePlaybackController` scores by hold time — how many seconds the cube stays lifted after the recording ends. Override hooks if you need different behavior:

| Hook | When it's called | Default |
|---|---|---|
| `_initial_cube_mass()` | Once at init | Returns `cfg.cube_mass_start` |
| `_update_overload_mass()` | Every frame during overload | Ramps mass from start to max |
| `_on_horizon_complete(sim_time)` | When recording finishes | Calls `write_pruned_and_stop` |

Inside a subclass you also have: `self.hold_time`, `self.writer`, `self.cfg`, `self._set_cube_mass(value)`.

### Mode B — Inverse (effector target control)

Use when the test doesn't need collisions: alignment, tilt, pose-accuracy. You declare target positions instead of replaying recorded motors.

```python
import json, os, sys
from pathlib import Path

sys.path.insert(
    0, str(next(c for c in Path(__file__).parents if (c / "labtests").is_dir()))
)
from launcher.bootstrap import bootstrap_lab
SCRIPT_DIR, SRC_ROOT, APP_ROOT, LAB_ROOT = bootstrap_lab(__file__)

from labtests.core.scene_config import OptunaMeta
META = OptunaMeta.from_env()

# Waypoints: ([x, y, z, qx, qy, qz, qw], hold_frames)
# Rotations have no effect — Emio cannot yet control orientation.
WAYPOINTS = [
    ([0,  -150, 40, 0, 0, 0, 1], 10),
    ([40, -150,  0, 0, 0, 0, 1], 10),
]

def createScene(rootnode):
    import Sofa.Core
    from labtests.core.base_scene import build_base_scene
    from labtests.core.modules.effector_target import setup as setup_effector
    from labtests.core.scoring import ScoreWriter
    from parts.controllers.assemblycontroller import AssemblyController

    nodes = build_base_scene(rootnode, inverse=True)
    if nodes is None:
        return

    nodes.emio.addObject(AssemblyController(nodes.emio))
    effector_handles = setup_effector(nodes, nodes.emio, initial_target_pos=[0, -150, 0, 0, 0, 0, 1])
    writer = ScoreWriter(rootnode, run_info=META.run_info,
                         trial_state_path=META.trial_state_path, run_slot=META.run_slot)
    assembly_controller = nodes.emio.getObject("AssemblyController")

    class MyController(Sofa.Core.Controller):
        def __init__(self, *args, **kwargs):
            Sofa.Core.Controller.__init__(self, *args, **kwargs)
            self.waypoint_index = 0
            self.hold_frame = 0
            self.penalties = [0.0] * len(WAYPOINTS)

        def onAnimateBeginEvent(self, event):
            if not assembly_controller.done:
                return
            if self.waypoint_index >= len(WAYPOINTS):
                if not writer.finished:
                    writer.write_score_and_stop(40.0 - sum(self.penalties), "done")
                return
            pos, hold_frames = WAYPOINTS[self.waypoint_index]
            effector_handles.target_mo.position.value = [pos]
            points = effector_handles.effector_mo.position.value
            # measure something — example: Y-axis spread
            spread = abs(points[0][1] - points[2][1])
            if spread > self.penalties[self.waypoint_index]:
                self.penalties[self.waypoint_index] = spread
            self.hold_frame += 1
            if self.hold_frame >= hold_frames:
                self.hold_frame = 0
                self.waypoint_index += 1

    nodes.simulation.addObject(MyController(name="MyController"))
    return rootnode
```

### Mode C — Variant of an existing test

If your test is a small tweak of an existing one, override env vars and re-export `createScene`:

```python
import os
os.environ.setdefault("SHAPEOPT_CUBE_WEIGHT_MIN", "0.05")
os.environ.setdefault("SHAPEOPT_CUBE_WEIGHT_MAX", "0.05")

from labtests.grasp_hold.scene import createScene as createScene  # noqa: F401
```

---

## Quick reference

### Core imports

| Import | What it gives you |
|---|---|
| `build_base_scene(rootnode, inverse, friction)` | Robot + solvers. Returns `SceneNodes` or `None`. |
| `add_required_plugins(simulation)` | 13 SOFA plugins for collision and contact. |
| `PlaybackConfig.from_env(lab_root)` | Scene physics/scoring config: defaults from `core/scene_defaults.py`, env vars override individually. |
| `OptunaMeta.from_env()` | Optuna metadata only (gen, trial, run, slot). |
| `setup_collision(emio, stl_path)` | Adds gripper collision mesh. Returns node. |
| `setup_cube_floor(simulation, gripper_collision, **kwargs)` | Adds cube + floor. Returns `CubeFloorHandles`. |
| `setup_playback(emio, record_file)` | Loads motor recording + wires `JointConstraints`. |
| `setup_effector(nodes, emio, **kwargs)` | Adds effector target + ImGui controls. Returns `EffectorHandles`. |
| `make_playback_controller(Sofa.Core.Controller)` | Returns `BasePlaybackController`. |
| `ScoreWriter(rootnode, run_info, trial_state_path, run_slot)` | `.write_score_and_stop(score, reason)` or `.write_pruned_and_stop(reason)`. |

### `SceneNodes` fields

| Field | What it is |
|---|---|
| `rootnode` | SOFA root node |
| `simulation` | Node where controllers and rigid bodies go |
| `emio` | Robot node — pass to collision, playback, effector setups |
| `modelling` | Modelling node |
| `settings` | Plugin/header settings node |

### Environment variables (set by the optimizer automatically)

| Variable | What it is |
|---|---|
| `OPTUNA_TRIAL_STATE_PATH` | Path to the JSON file where scores are written |
| `OPTUNA_RUN_SLOT` | Run slot index (0-indexed, for multi-run tests) |
| `OPTUNA_GEN` | Current optimizer generation |
| `OPTUNA_TRIAL` | Current trial number |
| `OPTUNA_RUN` | Current run number |
| `OPTUNA_STL_PATH` | Path to the gripper collision STL |

None of these are required: launched standalone (dashboard "watch" button, manual runSofa), scenes fall back to `core/scene_defaults.py` values and a no-trial `OptunaMeta`. Physics/scoring values (`CUBE_MASS_MAX`, `SHAPEOPT_FRICTION_COEF`, ...) can also be set per-process to override a default for one-off experiments.

---

## Checklist

- [ ] Folder created under `labtests/`
- [ ] `test.json` — `label`, `description`, `default_selected`, `run_count`
- [ ] `scoring.py` — `SCORE_KEY`, `TEST_NAME`, `TEST_LABEL`, `TEST_DESCRIPTION`, `MAX_SCORE`
- [ ] `scene.py` — defines `createScene(rootnode)`, returns `rootnode`
- [ ] Path bootstrap (`bootstrap_lab` block) at top of `scene.py`
- [ ] `writer.write_score_and_stop(score, reason)` called exactly once per run
- [ ] `MAX_SCORE` matches the highest realistic score the test can produce
