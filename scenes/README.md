# scenes/

SOFA scene scripts for manual use — not run by the optimizer. Launch with `runSofa.exe` or from the dashboard Scenes tab.

---

## Files

**`lab_shapeOPT_inverse.py`** — manual inverse-mode control

Loads the gripper in inverse solver mode with the full SOFA ImGui interface: drag-to-target effector control, gripper opening slider, program window, and I/O stream. Use this to manually drive the gripper, inspect the current mesh geometry, or validate a config before optimizing.

```bash
runSofa.exe -l SofaPython3 scenes/lab_shapeOPT_inverse.py
```

**`lab_shapeOPT_recording.py`** — motor trajectory recorder

Same inverse scene but with a `RecordingController` attached. Captures motor positions at every simulation frame and autosaves them to `runtime/recordings/<test>/motor_recording.json` every second. On startup it reads `runtime/session_config.json` to know which test to target — the dashboard Scenes tab writes that file before launching.

```bash
runSofa.exe -l SofaPython3 scenes/lab_shapeOPT_recording.py
```

**`lab_shapeOPT_inverse.crproj`** — EmioLabs platform project file associated with the inverse scene. Not a Python script — opened by the EmioLabs desktop app.

---

## When to use each

| Situation | Scene |
|---|---|
| Inspect or validate a gripper mesh | `lab_shapeOPT_inverse.py` |
| Record a new motor trajectory for a test | `lab_shapeOPT_recording.py` via the dashboard |
| Run an optimization test manually | Use the dashboard Scenes → Watch tab instead |
