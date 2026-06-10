# optimization/

CMA-ES optimization loop. Drives the search for the best gripper shape by running hundreds of SOFA simulations across generations and feeding scores back into Optuna.

Entry point: `python optimization/orchestrator.py`

---

## How it works

Each generation:
1. CMA-ES proposes N trial parameter sets
2. For each trial (serially): generate geometry → copy visual STL → render preview → launch SOFA
3. SOFA instances run in parallel (launched as soon as their geometry is ready)
4. Wait for all SOFA processes to finish, read scores from `runtime/trials/`
5. Write `summary.json` (avg/best/worst for the generation) and `progress.json` (overall UI progress bar)
6. Report scores to Optuna → CMA-ES updates its distribution
7. Repeat for N generations

---

## Modules

**`orchestrator.py`** — Main loop. Sequences geometry generation, SOFA launches, score collection, and Optuna reporting. Delegates each generation to `generation/runner.py`.

**`algorithm.py`** — Optuna study setup and CMA-ES sampler configuration. Creates the study (SQLite-backed), defines the search space from `ModelParams` field metadata, and computes the weighted composite score from multi-test results.

**`config.py`** — Optimizer tuning constants in one place: parallelism limits, generation counts, paths, CMA-ES hyperparameters (`SIGMA0`, `STARTUP_TRIALS`), score weights, runtime limits. Scene physics and scoring defaults are NOT here — they live in `labtests/core/scene_defaults.py` and scenes read them directly.

**`geom_pipeline.py`** — Trial parameter → STL pipeline. Calls `generation/generate_gripper.py` in a subprocess, handles timeouts, renders an offscreen preview image via pyvista, and copies the visual mesh.

**`sofa_runner.py`** — SOFA subprocess management. Launches `runSofa.exe` with the correct env vars, attaches a Windows Job Object for clean process-tree cleanup, and monitors for hangs.

**`scoring.py`** — Score math and progress reporting. Normalizes and aggregates multi-test scores, writes `summary.json` per generation and `progress.json` for the UI. File I/O primitives live in `_scoring_io.py`; trial-state CRUD (read/write `trial_state.json`) lives in `_trial_state.py`.

**`state.py`** — Per-trial state tracking across runs. Collects individual run results and computes the final trial score once all runs are done.

**`utils.py`** — Directory setup, file utilities, cleanup logging.

**`generation/`** — One generation, end to end:
- `plan.py` — builds the per-generation trial/run plan
- `launch.py` — starts geometry exports and SOFA processes as resources free up
- `progress.py` — periodic progress writes while runs execute
- `finalize.py` — waits for completion, enforces `SOFA_REALTIME_TIMEOUT`, collects scores
- `runner.py` — ties the four phases together; called once per generation by the orchestrator

---

## Key constants (in `config.py`)

| Constant | What it controls |
|---|---|
| `N_GENERATIONS` | Total number of CMA-ES generations |
| `N_PARALLEL` | Trials per generation (CMA-ES population size) |
| `MAX_ACTIVE_SOFA_PROCS` | Max concurrent SOFA processes |
| `CMAES_SIGMA0` | Initial CMA-ES step size |
| `CMAES_STARTUP_TRIALS` | Random trials before CMA-ES kicks in |
| `HARD_FAIL_SCORE` | Score assigned to trials where geometry generation fails |
| `SELECTED_TEST_NAMES` | Which labtests to run |
| `SELECTED_TEST_WEIGHTS` | Weight per test in the composite score |

---

## Data flow

```
Optuna (CMA-ES)
    └── proposes params
            └── geom_pipeline.py   generates STL + preview
            └── sofa_runner.py     launches runSofa.exe
                    └── scene.py       runs simulation, writes score JSON
            └── scoring.py         reads scores, aggregates
    └── receives score → updates distribution
```

State is persisted in `runtime/gripper_opt.db` (Optuna SQLite). Delete it to start fresh.
