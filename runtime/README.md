# runtime/

Everything generated at runtime. Nothing here is source code — it's all produced by the optimization loop, generation scripts, or SOFA scenes.

Run and session logs are **not** here — they live in the top-level `logs/` directory, a deliberate sibling of `runtime/` so archiving (which moves `runtime/` wholesale) never has to deal with an open log handle.

---

## Directory map

```
runtime/
├── exports/            ← Gripper mesh files from the last generation run
├── previews/           ← Output of generation/preview.py (quick gripper/leg render)
├── recordings/         ← Motor trajectory recordings per test (committed, NOT auto-generated)
├── trials/             ← Per-trial output from the optimization loop
│   ├── gen_XXXX/
│   │   └── trial_XX/
│   │       ├── params.json        ← params used for this trial
│   │       ├── trial_state.json   ← run results and scores
│   │       └── preview.png        ← offscreen render of the gripper
│   ├── previews/                  ← flat copy of all previews (gen_XXXX_trial_XX.png)
│   └── progress.json              ← overall progress, read by the dashboard
├── study.db                       ← Optuna SQLite database (the CMA-ES state)
├── session_config.json            ← written by the web UI before launching a recording scene
└── watch_recording.json           ← motor trace captured by the recording scene's watch mode
```

---

## Key files

**`study.db`** — Optuna's SQLite database. Stores all trial params, scores, and the CMA-ES sampler state. The optimizer resumes from this on restart. Delete it to start a fresh optimization run.

**`trials/progress.json`** — Written after every trial. Contains overall progress (generation, trial counts, best/avg score, test weights). Read by the dashboard and the UI progress bar.

**`trials/gen_XXXX/trial_XX/trial_state.json`** — Per-trial score breakdown. Has one entry per simulation run, including score, reason string, sim time, and test-specific fields (hold time, cube Y, etc.).

**`exports/`** — Output of `generate_gripper.py`. Contains the STL/VTK/JSON for the current gripper config:
- `new_gripper.stl` / `.vtk` — simulation mesh
- `new_gripper_collision.stl` — coarser mesh, both fingers merged (unused by the scene; kept for reference/preview)
- `new_gripper_collision_finger1.stl` / `_finger2.stl` — same coarse mesh, but split one file per finger. SOFA loads these two (not the merged one above) so it can detect the fingers colliding with each other, not just with the cube/floor.
- `new_gripper_print.stl` / `.3mf` — fine mesh for 3D printing (only from `generate_gripper_fine.py`)
- `new_gripper.json` — leg attachment poses for SOFA

**`recordings/<test_name>/motor_recording.json`** — Motor position trajectory recorded in inverse mode. Required by any direct-mode labtest. These are committed and should not be deleted — re-recording takes manual effort.
