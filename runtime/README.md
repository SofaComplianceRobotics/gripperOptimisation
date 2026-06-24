# runtime/

Everything generated at runtime. Nothing here is source code — it's all produced by the optimization loop, generation scripts, or SOFA scenes.

---

## Directory map

```
runtime/
├── exports/            ← Gripper mesh files from the last generation run
├── logs/               ← generate.log and optimize.log
├── modules/            ← Python packages installed by the lab (CadQuery, etc.)
├── recordings/         ← Motor trajectory recordings per test (NOT auto-generated)
├── trials/             ← Per-trial output from the optimization loop
│   ├── gen_XXXX/
│   │   └── trial_XX/
│   │       ├── lab_config.jsonc   ← params used for this trial
│   │       ├── trial_state.json   ← run results and scores
│   │       └── preview.png        ← offscreen render of the gripper
│   └── previews/                  ← flat copy of all previews (gen_XXXX_trial_XX.png)
├── gripper_opt.db                     ← Optuna SQLite database (the CMA-ES state)
└── session_config.json                ← written by the web UI before launching a recording scene
```

---

## Key files

**`gripper_opt.db`** — Optuna's SQLite database. Stores all trial params, scores, and the CMA-ES sampler state. The optimizer resumes from this on restart. Delete it to start a fresh optimization run.

**`trials/progress.json`** — Written after every trial. Contains overall progress (generation, trial counts, best/avg score, test weights). Read by the dashboard and the UI progress bar.

**`trials/gen_XXXX/trial_XX/trial_state.json`** — Per-trial score breakdown. Has one entry per simulation run, including score, reason string, sim time, and test-specific fields (hold time, cube Y, etc.).

**`exports/`** — Output of `generate_gripper.py`. Contains the STL/VTK/JSON for the current gripper config:
- `new_gripper.stl` / `.vtk` — simulation mesh
- `new_gripper_collision.stl` — coarser mesh used for SOFA contact detection
- `new_gripper_print.stl` / `.3mf` — fine mesh for 3D printing (only from `generate_gripper_fine.py`)
- `new_gripper.json` — leg attachment poses for SOFA

**`recordings/<test_name>/motor_recording.json`** — Motor position trajectory recorded in inverse mode. Required by any direct-mode labtest. These are committed and should not be deleted — re-recording takes manual effort.

**`modules/`** — Lab-local Python packages (CadQuery and friends) used when they aren't available in the active environment. Install into it manually with `pip install --target runtime/modules/site-packages <package>`.
