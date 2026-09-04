# labtests/random_cube_pick/

Variant of `grasp_hold`: identical motor recording, controller, scoring and
overload behaviour, but the cube size changes per run.

---

## How scoring works

Three runs per trial, one cube size per run, each lifted once at the standard
`grasp_hold` cube weight (`cube_mass_start`):

| Run index | Cube scale |
|---|---|
| 1 | 8 × 8 × 8 mm |
| 2 | 12 × 12 × 12 mm |
| 3 | 14 × 14 × 14 mm |

The size is keyed off `OPT_TEST_RUN_INDEX` (the 1-based per-test index), so
the sequence is always 8 → 12 → 14 regardless of where the test lands in the
global run order.

Each run is scored by hold time exactly like `grasp_hold`. The trial score is
the **sum** across the three sizes (`score_aggregation: "sum"` in
`test.json`). `MAX_SCORE` is derived in `scoring.py` from the recording
length plus overload time minus the pre-pickup gate, times three runs, so a
perfect hold across all three sizes normalizes to 1.0 no matter how the scene
timing is tuned.

---

## scene.py responsibilities

- Picks `cube_scale` for the current run from `CUBE_SIZES` via
  `_cube_scale_for_run()`.
- Everything else — cube mass, overload ramp, hold-time scoring — comes from
  core, identical to `grasp_hold`.
