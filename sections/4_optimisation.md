:::: collapse Shape Optimisation

### Shape Optimisation

The optimiser generates hundreds of gripper variants, simulates each one in parallel with SOFA, and uses CMA-ES to converge on the best-scoring shape.

---

#### How it works

1. **CMA-ES** proposes `N_PARALLEL = 10` parameter sets (one generation).
2. Each set is exported to an STL by `generate_gripper.py`.
3. All 10 SOFA instances run in parallel — one per parameter set.
4. Scores are collected and fed back to CMA-ES, which updates its search distribution.
5. This repeats for `N_GENERATIONS = 400` generations — 4 000 trials total.

---

#### What gets optimised

The table below lists all parameters the optimiser is allowed to vary. Everything else stays fixed at its `lab_config.jsonc` value.

| Parameter | Range | What it controls |
|---|---|---|
| `pincer_profile_width` | 2 – 8 mm | Cross-section width |
| `pincer_profile_height` | 6 – 16 mm | Cross-section height |
| `p0_hout_dist` | 0 – 80 mm | Length of the first Bézier handle |
| `p0_hout_angle_deg` | −90 – 90° | Direction of the first Bézier handle |
| `p1_dist` | 80 – 110 mm | Distance of the tip anchor |
| `p1_angle_deg` | −90 – 45° | Angle of the tip anchor |
| `p1_hin_dist` | 0 – 80 mm | Length of the last Bézier handle |
| `p1_hin_angle_deg` | −10 – 260° | Direction of the last Bézier handle |
| `leg_attachement_tilt_angle` | −30 – 30° | Leg lean angle |

To change which parameters are active or adjust their ranges, edit `ModelParams` in `app/src/core/params.py` — add or update the `metadata={"opt": {...}}` on any field.

---

#### Tests

A **test** is one simulation scenario used to score a gripper. Multiple tests can be active at once — their scores are combined with normalised weighted averages.

| Test | Runs | Score | Description |
|---|---|---|---|
| `grasp_hold` | 1 | Hold time (s) | Standard cube grasp; scores by how long the cube stays held |
| `random_cube_pick` | 3 | Sum of hold times | Three cube sizes, seeded random mass; tests adaptability |
| `gripper_tilt` | 1 | 40 − Y-spread | Inverse-mode tilt sequence; lower spread = better score |

`random_cube_pick` uses 3 runs per trial because each run tests a different cube size (5 mm, 8 mm, 20 mm). Scores are **summed** across the three runs so the total reflects all three sizes, not an average.

#icon("info-circle") The test selection and weights are chosen in the UI before launching the optimiser. Adding a new test requires creating a folder under `app/src/labtests/` — see `adding_a_test.md` for the step-by-step guide.

---

#### Launching

Launch the optimiser (opens a test selector first):

#python-button("assets/labs/lab_shapeOPT/app/src/launch/launch_optimize_custom_sofa.py")

Monitor progress during a run:

#python-button("assets/labs/lab_shapeOPT/app/src/analysis/progress_monitor.py")

Inspect where each parameter sits within its bounds (latest gripper):

#python-button("assets/labs/lab_shapeOPT/app/src/analysis/param_bounds_viewer.py")

Analyse results after a run:

#python-button("assets/labs/lab_shapeOPT/app/src/analysis/analyze_results.py")

---

#### Output structure

Results are written to `runtime/trials/`. Each generation has its own subfolder, and each trial within it contains:

| File | Description |
|---|---|
| `trial_state.json` | Per-run scores, state, and timing |
| `preview.png` | Rendered preview of the gripper shape |
| `lab_config.jsonc` | Exact parameter values used |

A flat `runtime/trials/previews/` folder collects one PNG per trial, making it easy to scroll through results.

::::
