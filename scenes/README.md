# scenes/

SOFA scenes for manual use and for the optimizer's per-trial motor recording.
Launch the manual ones with `runSofa.exe` or from the dashboard Scenes tab.

---

## Files

**`_manual_scene.py`** — shared assembly for the two interactive scenes.
`build_manual_scene()` owns the common part (robot, tray, effector chain,
draggable target, ImGui accessories); each scene file only adds what makes it
unique.

**`lab_shapeOPT_inverse.py`** — manual inverse-mode control. Loads the
gripper in the inverse solver with the full ImGui interface: drag-to-target
effector, opening slider, program window, I/O stream. Use it to drive the
gripper by hand or eyeball a config before optimizing.

```bash
runSofa.exe -l SofaPython3 scenes/lab_shapeOPT_inverse.py
```

**`lab_shapeOPT_recording.py`** — the inverse scene plus a
`RecordingController`. Captures motor positions every frame and autosaves them
to `runtime/recordings/<test>/motor_recording.json` once a second. On startup
it reads `runtime/session_config.json` (written by the dashboard Scenes tab)
to know which test to target.

```bash
runSofa.exe -l SofaPython3 scenes/lab_shapeOPT_recording.py
```

**`lab_shapeOPT_trial_recorder.py`** — headless, **optimizer-only**. Called by
`sofaopt_project.py`'s `prepare_trial` hook once per trial: drives this
trial's gripper + leg through the inverse solver and writes the trajectory
the direct-mode tests then replay. Reads/writes paths from `OPT_*` env vars.
Not for manual use.

**`lab_shapeOPT_inverse.crproj` / `lab_shapeOPT_recording.crproj`** — EmioLabs
platform project files pairing with the two interactive scenes. Not Python —
opened by the EmioLabs desktop app.

---

## When to use each

| Situation | Scene |
|---|---|
| Inspect or validate a gripper mesh | `lab_shapeOPT_inverse.py` |
| Record a new reference trajectory for a test | `lab_shapeOPT_recording.py`, via the dashboard |
| Run one optimization test with a window open | dashboard Scenes → "watch a test" |
| Per-trial trajectory during a run | `lab_shapeOPT_trial_recorder.py` (automatic) |
