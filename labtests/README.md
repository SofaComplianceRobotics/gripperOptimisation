# labtests/

Each subfolder is one simulation test. The optimizer runs the selected tests
against every gripper candidate and collects a score per test. Higher score =
better gripper.

---

## How discovery works

`registry.py` auto-scans the subfolders of `labtests/`. A folder becomes a
valid test when it contains all three of:

```
labtests/
└── my_test/
    ├── test.json      ← label, description, run count, aggregation
    ├── scene.py       ← SOFA scene, must define createScene(rootnode)
    └── scoring.py     ← metadata constants (MAX_SCORE, labels)
```

No registration call needed. Create the files and the test shows up in the
dashboard's Run and Scenes tabs.

### `TestSpec` fields

| Field | Source | Meaning |
|---|---|---|
| `name` | folder name | Unique identifier (this is the real name; `TEST_NAME` in `scoring.py` is informational) |
| `label` | `test.json` | Short name in the picker |
| `description` | `test.json` | Subtitle next to the label |
| `default_selected` | `test.json` | Pre-checked in the picker when `true` |
| `run_count` | `test.json` | Simulation runs per trial |
| `score_aggregation` | `test.json` | How multi-run scores combine (`"mean"` or `"sum"`) |
| `max_score` | `scoring.py` `MAX_SCORE` | Realistic best score, used to normalize across tests |

Use `run_count` > 1 when a test has variance to average out (random cube
sizes, random spawn) or when it deliberately sweeps a set of conditions
(`random_cube_pick` runs three cube sizes and sums them).

---

## The scene contract

Score and status writing is **sofaopt's** job. A scene gets a trial handle,
attaches it to the root node, and writes through it:

```python
from sofaopt.scene import open_trial

TRIAL = open_trial()          # or cfg.trial, via PlaybackConfig.from_env()

def createScene(rootnode):
    ...
    writer = TRIAL.attach(rootnode)
    ...
    writer.write_status({...})            # optional live progress, best-effort
    writer.write_score(score, reason)     # exactly once, ends the run
    writer.prune(reason)                  # or: give up on this trial
```

`open_trial()` reads the optimizer's environment. Launched standalone (the
Scenes "watch" button, a manual `runSofa`), it returns a no-trial handle:
`TRIAL.is_optimizing` is `False`, `write_score` is a no-op, and the scene
just runs interactively.

### Path bootstrap

Every `scene.py` starts with the same block so imports resolve no matter how
SOFA or the platform launched it:

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

## Two kinds of scene

### Direct mode (collision-based)

For anything with physical contact: grasp, pick-and-hold, cubes. Motors
replay a **pre-recorded** trajectory (the inverse solver can't run with
collisions). `grasp_hold` and `random_cube_pick` are the examples.

```python
from geometry.timing_config import DT_DIRECT as DT
from labtests.core.scene_config import PlaybackConfig

RECORD_FILE = os.environ.get("OPT_MOTOR_RECORDING") or str(
    LAB_ROOT / "runtime" / "recordings" / "my_test" / "motor_recording.json"
)

def createScene(rootnode):
    import Sofa.Core
    from labtests.core.base_scene import build_base_scene
    from labtests.core.modules.collision_stl import setup as setup_collision
    from labtests.core.modules.cube_floor import setup as setup_cube_floor
    from labtests.core.modules.motor_playback import setup as setup_playback
    from labtests.core.playback_controller import make_playback_controller
    from labtests.core.plugins import add_required_plugins

    cfg = PlaybackConfig.from_env(LAB_ROOT)

    nodes = build_base_scene(rootnode, inverse=False, friction=cfg.friction_coef)
    if nodes is None:
        return
    add_required_plugins(nodes.simulation)
    rootnode.dt = DT

    gripper_collision = setup_collision(
        nodes.emio, cfg.gripper_finger1_mesh_path, cfg.gripper_finger2_mesh_path
    )
    cube_handles = setup_cube_floor(
        nodes.simulation, gripper_collision,
        cube_scale=[8, 8, 8],           # mm
        cube_mass=cfg.cube_mass_start,
        floor_center_y=cfg.floor_center_y,
        cube_spawn_clearance=cfg.cube_spawn_clearance,
    )
    playback = setup_playback(nodes.emio, RECORD_FILE)
    writer = cfg.trial.attach(rootnode)

    Base = make_playback_controller(Sofa.Core.Controller)
    nodes.simulation.addObject(Base(
        name="PlaybackController", rootnode=rootnode, playback=playback,
        cube_handles=cube_handles, gripper_collision=gripper_collision,
        writer=writer, cfg=cfg,
    ))
    return rootnode
```

`BasePlaybackController` scores by hold time — seconds the cube stays lifted
after the recording ends. Subclass it and override only what differs:

| Hook | Default |
|---|---|
| `_initial_cube_mass()` | `cfg.cube_mass_start` |
| `_update_overload_mass()` | ramp mass to `cfg.cube_mass_max` |
| `_on_horizon_complete(sim_time)` | score by hold time |
| `_finish_run(score, reason, pruned)` | `writer.write_score` / `writer.prune` |

### Inverse mode (effector-target control)

For tests that don't need collisions: alignment, tilt, reach. You declare
target positions and the inverse solver drives the motors. `gripper_tilt` and
`reach_zone` are the examples.

```python
from sofaopt.scene import open_trial
TRIAL = open_trial()

WAYPOINTS = [
    ([0,  -150, 40, 0, 0, 0, 1], 10),   # [x,y,z, quat], hold_frames
    ([40, -150,  0, 0, 0, 0, 1], 10),   # rotation is ignored — Emio can't control orientation yet
]

def createScene(rootnode):
    import Sofa.Core
    from labtests.core.base_scene import build_base_scene
    from labtests.core.modules.effector_target import setup as setup_effector
    from parts.controllers.assemblycontroller import AssemblyController

    nodes = build_base_scene(rootnode, inverse=True)
    if nodes is None:
        return
    nodes.emio.addObject(AssemblyController(nodes.emio))
    effector = setup_effector(nodes, nodes.emio, initial_target_pos=[0, -150, 0, 0, 0, 0, 1])
    writer = TRIAL.attach(rootnode)
    assembly = nodes.emio.getObject("AssemblyController")

    class MyController(Sofa.Core.Controller):
        def __init__(self, *a, **k):
            Sofa.Core.Controller.__init__(self, *a, **k)
            self.i, self.hold = 0, 0

        def onAnimateBeginEvent(self, event):
            if not assembly.done:
                return
            if self.i >= len(WAYPOINTS):
                if not writer.finished:
                    writer.write_score(40.0, "done")
                return
            pos, hold_frames = WAYPOINTS[self.i]
            effector.target_mo.position.value = [pos]
            # ... measure effector.effector_mo.position.value ...
            self.hold += 1
            if self.hold >= hold_frames:
                self.hold, self.i = 0, self.i + 1

    nodes.simulation.addObject(MyController(name="MyController"))
    return rootnode
```

### Variant of an existing test

If your test is a small tweak, set env overrides and re-export `createScene`:

```python
import os
os.environ.setdefault("CUBE_MASS_START", "0.05")
os.environ.setdefault("CUBE_MASS_MAX", "0.05")
from labtests.grasp_hold.scene import createScene  # noqa: F401
```

---

## Core imports

| Import | Gives you |
|---|---|
| `build_base_scene(rootnode, *, inverse, friction=0.6, multithreading=False)` | Root config + Emio robot + legs. Returns `SceneNodes` or `None` (bail on `None`). |
| `add_required_plugins(simulation)` | The 16 SOFA plugins for direct-mode collision. |
| `PlaybackConfig.from_env(lab_root)` | Direct-mode config: mesh paths, friction, cube physics, scoring thresholds, and `.trial`. Defaults from `core/scene_defaults.py`, each overridable by env var. |
| `open_trial()` | sofaopt trial handle; `.attach(rootnode)` → score writer. |
| `setup_collision(emio, finger1_stl, finger2_stl)` | Two per-finger collision meshes (separate groups → finger-vs-finger contact works). |
| `setup_cube_floor(simulation, gripper_collision, **kwargs)` | Cube + floor. Returns `CubeFloorHandles`. |
| `setup_playback(emio, record_file)` | Loads a motor recording, wires `JointConstraints`. |
| `setup_effector(nodes, emio, *, initial_target_pos=None, ...)` | Effector target + ImGui drag handle. Returns `EffectorHandles`. |
| `make_playback_controller(Sofa.Core.Controller)` | `BasePlaybackController` class bound to the live controller base. |

`SceneNodes` fields: `rootnode`, `settings`, `modelling`, `simulation`
(controllers + rigid bodies go here), `emio` (the robot).

---

## Environment variables

Set by the optimizer per run; none are required for a standalone launch.

| Variable | Meaning |
|---|---|
| `OPT_MOTOR_RECORDING` | Path to this trial's freshly recorded trajectory (direct mode) |
| `OPT_MOTOR_RECORDING_OUT` | Where the trial recorder writes the trajectory |
| `OPT_MESH_FINGER1` / `OPT_MESH_FINGER2` | Per-finger collision STL paths |
| `OPT_LEG_NAME` | Name of this trial's generated leg (else the stock blueleg) |
| `OPT_TEST_RUN_INDEX` / `OPT_RUN_SLOT` | 1-based run index within the test / global slot |

Trial identity (gen, trial, run, slot, params, score path) comes through
`open_trial()`, not individual env vars. Physics/scoring values
(`CUBE_MASS_MAX`, `SHAPEOPT_FRICTION_COEF`, `OVERLOAD_MAX_TIME`, …) can be set
per-process to override one default for a one-off experiment — see
`core/scene_defaults.py` for the full list.

---

## Checklist for a new test

- [ ] Folder under `labtests/`
- [ ] `test.json` — `label`, `description`, `default_selected`, `run_count`
- [ ] `scoring.py` — `SCORE_KEY`, `TEST_NAME`, `TEST_LABEL`, `TEST_DESCRIPTION`, `MAX_SCORE`
- [ ] `scene.py` — bootstrap block, `createScene(rootnode)` returning `rootnode`
- [ ] `writer.write_score(score, reason)` called exactly once per run
- [ ] `MAX_SCORE` set to the highest realistic score the test produces
- [ ] Direct mode: a `motor_recording.json` under `runtime/recordings/<name>/`
