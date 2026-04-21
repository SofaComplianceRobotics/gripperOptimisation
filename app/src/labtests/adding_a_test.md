# Adding a New ShapeOPT Test

The test registry auto-discovers any subfolder of `labtests/` that contains
`scene.py`, `scoring.py`, and `test.json`. You only need to create those
three files.

---

## Step 1 — Create the folder
 
```
app/src/labtests/
└── my_new_test/
    ├── __init__.py     (optional, can be empty)
    ├── test.json
    ├── scene.py
    └── scoring.py
```

---

## Step 2 — Write test.json

```json
{
  "label": "My New Test",
  "description": "One-line description shown in the test picker",
  "default_selected": false,
  "run_count": 1
}
```

| Field              | Meaning                                              |
|--------------------|------------------------------------------------------|
| `label`            | Short display name in the Tk picker                  |
| `description`      | Subtitle shown next to the label                     |
| `default_selected` | Pre-selected when the picker opens                   |
| `run_count`        | How many runs the optimizer launches per trial       |

---

## Step 3 — Write scoring.py

This is just metadata used by the optimizer and analysis tools.

```python
SCORE_KEY         = "score"
SCORE_LABEL       = "My Metric"
SCORE_DESCRIPTION = "What the number means"
```

---

## Step 4 — Write scene.py

Pick the template that matches your mode.

### Direct mode (motor playback + cube)

```python
"""Scene: my_new_test — direct mode."""

import os, sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SRC_ROOT   = SCRIPT_DIR.parents[2]
APP_ROOT   = SCRIPT_DIR.parents[3]
LAB_ROOT   = SCRIPT_DIR.parents[4]
for c in (str(LAB_ROOT), str(APP_ROOT), str(SRC_ROOT)):
    if c not in sys.path:
        sys.path.insert(0, c)

# Read whatever env vars your test needs
MY_THRESHOLD = float(os.environ.get("MY_THRESHOLD", "10.0"))
SCORE_PATH   = os.environ.get("OPTUNA_SCORE_PATH", None)
STATUS_PATH  = os.environ.get("OPTUNA_STATUS_PATH", None)
OPTUNA_GEN   = int(os.environ.get("OPTUNA_GEN",   "0"))
OPTUNA_TRIAL = int(os.environ.get("OPTUNA_TRIAL", "0"))
OPTUNA_RUN   = int(os.environ.get("OPTUNA_RUN",   "0"))
DT           = 0.01


def createScene(rootnode):
    import Sofa.Core
    from labtests.core.base_scene import build_base_scene
    from labtests.core.modules.collision_stl import setup as setup_collision
    from labtests.core.modules.cube_floor    import setup as setup_cube_floor
    from labtests.core.modules.motor_playback import setup as setup_playback
    from labtests.core.scoring import ScoreWriter

    nodes = build_base_scene(rootnode, inverse=False)
    if nodes is None:
        return

    gripper_collision = setup_collision(
        nodes.emio,
        os.environ.get("OPTUNA_STL_PATH", "...")
    )
    cube_handles = setup_cube_floor(nodes.simulation, gripper_collision)
    playback     = setup_playback(
        nodes.emio,
        LAB_ROOT / "runtime" / "recordings" / "my_new_test" / "motor_recording.json",
    )
    writer = ScoreWriter(
        rootnode,
        score_path=SCORE_PATH,
        status_path=STATUS_PATH,
        run_info={"gen": OPTUNA_GEN, "trial": OPTUNA_TRIAL, "run": OPTUNA_RUN},
    )

    class MyController(Sofa.Core.Controller):
        def __init__(self, *args, **kwargs):
            Sofa.Core.Controller.__init__(self, *args, **kwargs)
            self.frame = 0

        def onAnimateBeginEvent(self, event):
            if writer.finished:
                return

            # --- your logic here ---
            # call writer.write_score_and_stop(score, reason) when done
            # call writer.write_pruned_and_stop(reason) for invalid runs

            # Replay motors
            if self.frame < len(playback.motor_positions):
                for i, c in enumerate(playback.joint_constraints):
                    c.value.value = playback.motor_positions[self.frame][i]
            self.frame += 1

    nodes.simulation.addObject(MyController(name="MyController"))
    return rootnode
```

### Inverse mode (effector target + ImGui)

```python
"""Scene: my_tilt_variant — inverse mode."""

import os, sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SRC_ROOT   = SCRIPT_DIR.parents[2]
APP_ROOT   = SCRIPT_DIR.parents[3]
LAB_ROOT   = SCRIPT_DIR.parents[4]
for c in (str(LAB_ROOT), str(APP_ROOT), str(SRC_ROOT)):
    if c not in sys.path:
        sys.path.insert(0, c)

SCORE_PATH  = os.environ.get("OPTUNA_SCORE_PATH",  None)
STATUS_PATH = os.environ.get("OPTUNA_STATUS_PATH", None)
OPTUNA_GEN   = int(os.environ.get("OPTUNA_GEN",   "0"))
OPTUNA_TRIAL = int(os.environ.get("OPTUNA_TRIAL", "0"))
OPTUNA_RUN   = int(os.environ.get("OPTUNA_RUN",   "0"))


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

    effector_handles = setup_effector(nodes, nodes.emio)
    writer = ScoreWriter(
        rootnode,
        score_path=SCORE_PATH,
        status_path=STATUS_PATH,
        run_info={"gen": OPTUNA_GEN, "trial": OPTUNA_TRIAL, "run": OPTUNA_RUN},
    )

    assembly_controller = nodes.emio.getObject("AssemblyController")

    class MyInverseController(Sofa.Core.Controller):
        def __init__(self, *args, **kwargs):
            Sofa.Core.Controller.__init__(self, *args, **kwargs)
            self.frame = 0

        def onAnimateBeginEvent(self, event):
            if not assembly_controller.done or writer.finished:
                return

            # move target: effector_handles.target_mo.position.value = [[x,y,z,qx,qy,qz,qw]]
            # read effector: effector_handles.effector_mo.position.value
            # score when done: writer.write_score_and_stop(score, reason)

            self.frame += 1

    nodes.simulation.addObject(MyInverseController(name="MyInverseController"))
    return rootnode
```

### Reuse an existing scene with different defaults

If your test is a variant of an existing one (like `random_cube_pick` is a
variant of `grasp_hold`), just set env vars and re-export:

```python
import os
os.environ.setdefault("MY_ENV_VAR", "my_value")

from labtests.grasp_hold.scene import createScene as createScene  # noqa: F401
```

---

## What each core piece does

| Import | What it gives you |
|---|---|
| `build_base_scene(rootnode, inverse=...)` | Configured rootnode + Emio. Returns `SceneNodes` or `None` on failure. |
| `setup_collision(emio, stl_path)` | Gripper collision mesh node. Pass to `setup_cube_floor`. |
| `setup_cube_floor(simulation, gripper_collision, **kwargs)` | Cube + floor + ContactListener. Returns `CubeFloorHandles`. |
| `setup_playback(emio, record_file)` | Loads recording, creates JointConstraints. Returns `PlaybackHandles`. |
| `setup_effector(nodes, emio, **kwargs)` | Effector MO + Target + ImGui. Returns `EffectorHandles`. |
| `ScoreWriter(rootnode, score_path, status_path, run_info)` | Writes score JSON + status. Call `.write_score_and_stop()` or `.write_pruned_and_stop()`. |

---

## Module compatibility

