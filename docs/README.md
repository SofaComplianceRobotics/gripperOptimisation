# Lab ShapeOPT - Gripper Optimization Lab

A parametric gripper design and optimization lab. It is meant to be launched through **EmioLabs** using the provided buttons and markdown guides, but the command-line steps below are available if you want to run the pieces manually.

---

## Overview

**Goal:** Generate and optimize grippers by varying geometric parameters and evaluating their performance in SOFA simulation.

**Two main processes:**
1. **Manual workflow:** edit a lab config, generate the gripper, and launch the SOFA scene.
2. **Optimization workflow:** run Optuna + CMA-ES to search for better grippers, analyze the results, then copy the best config back into the manual workflow.

`config/lab_config_working.jsonc` is only a baseline reference. Do not treat it as the active config for the scene. If you want a normal gripper for the SOFA scene, copy its values into `config/lab_config.jsonc`.

---

## Project Structure&

```
lab_shapeOPT/
├── app/
│   ├── requirements.txt        # Python dependencies
│   └── src/
│       ├── optimization/
│       │   ├── optimize.py                    # Main orchestrator (thin entry point)
│       │   ├── optimize_config.py             # Configuration & constants
│       │   ├── optimize_geometry.py           # STL generation & preview rendering
│       │   ├── optimize_sofa.py               # SOFA process management & launching
│       │   ├── optimize_scoring.py            # Score reading & reporting
│       │   └── optimize_utils.py              # Directory & file utilities
│       ├── generation/
│       │   └── generate_gripper.py
│       ├── analysis/
│       │   ├── analyze_results.py             # Main entry point (orchestrator)
│       │   ├── analyze_config.py              # Config & constants for analysis
│       │   ├── analyze_io.py                  # Data loading (trials & summaries)
│       │   ├── analyze_plotting.py            # Matplotlib visualization
│       │   ├── analyze_leaderboard.py         # Ranking & statistics
│       │   └── progress_monitor.py
│       ├── core/
│       │   ├── export_pipeline.py
│       │   ├── assembly.py
│       │   ├── gripper_parts.py
│       │   ├── geometry_helpers.py
│       │   ├── io_utils.py
│       │   └── params.py
│       └── launch/
│           ├── launch_optimize.py
│           ├── launch_optimize_custom_sofa.py
│           └── launch_scene_custom_sofa.py
├── lab_shapeOPT.py             # SOFA simulation scene
├── lab_shapeOPT_recording.py   # Trajectory recording scene
├── config/
│   ├── lab_config.jsonc        # Active gripper parameters
│   └── lab_config_working.jsonc
├── runtime/
│   ├── trials/                 # Optimization output directory
│   │   ├── gen_0001/           # Generation 1: one folder per trial, plus summary.json
│   │   │   ├──trial_01/        # Trial config, preview, and score files for one candidate
│   │   │   ├──trial_02/
│   │   │   └──summary.json     # Best/avg/worst score for that generation
│   │   ├── gen_0002/           # Generation 2, same structure
│   │   ├── ...
│   │   └── previews/           # Flat preview gallery across all generations
│   ├── exports/                # Exported meshes
│   └── motor_recording.json    # Recorded inverse trajectory
├── sections/                   # Documentation sections
│   ├── 1_introduction.md
│   ├── 2_parameters.md
│   ├── 3_generation.md
│   ├── 4_optimisation.md
│   └── 5_export.md
└── docs/
    └── README.md
```

---

## Planned Modular Test System (Upcoming Refactor)

We are refactoring the project to support a modular, composable test system for SOFA simulations. The goals are:

- **Core scene logic**: Shared setup for all tests (plugins, gripper loading, simulation root, etc.).
- **Feature modules**: Optional plug-ins for features like collisions, cube, floor, movement mode (direct/inverse), etc., that can be enabled/disabled per test.
- **Test-specific hooks**: Each test folder provides custom logic (e.g., scoring, movement, data collection).

### Example Structure

```
lab_shapeOPT/
├── app/
│   └── src/
│       ├── labtests/
│       │   ├── grasp_hold/
│       │   │   ├── scene.py
│       │   │   ├── scoring.py
│       │   │   └── test.json
│       │   ├── gripper_tilt/
│       │   │   ├── scene.py
│       │   │   ├── scoring.py
│       │   │   └── test.json
│       │   └── ... (other tests)
│       ├── core/
│       │   ├── scene_core.py      # Shared scene setup
│       │   └── modules/
│       │       ├── collision.py
│       │       ├── cube.py
│       │       ├── floor.py
│       │       └── movement.py
```

### How It Works

- Each test’s `test.json` specifies which modules/features to enable.
- The core scene builder reads this config, assembles the scene, and calls any test-specific hooks.
- Adding a new test = create a folder with only the unique logic/config for that test.

---

## Key Scripts & Their Roles

### 1. **app/src/optimization/optimize.py** — Optimization Orchestrator

**Purpose:** Main entry point for the optimization loop. Thin orchestrator that delegates to specialized modules.

**Imports from (modular structure):**
- `optimize_config.py` — All configuration, constants, and CMA-ES/SOFA settings
- `optimize_geometry.py` — Gripper geometry generation and preview rendering
- `optimize_sofa.py` — SOFA process management and subprocess handling
- `optimize_scoring.py` — Score reading, aggregation, and progress reporting
- `optimize_utils.py` — Directory management and cleanup utilities

**Key Functions:**
- `main()` — Entry point: initializes Optuna study and generation loop
- `run_generation()` — Executes one complete CMA-ES generation
- `generation_progress_writer()` — Background thread for live progress updates

**Workflow per generation:**
1. Pre-creates trial/run status files for the monitor
2. For each trial (serial): geometry generation → preview render → SOFA launch
3. Waits for all SOFA instances to finish (parallel)
4. Collects scores and applies consistency penalties
5. Writes generation summary and progress updates
6. Cleans up collision STL files

**Config Options (in optimize_config.py):**
- `N_PARALLEL = 10` — Parallel trials per generation and CMA-ES population size
- `N_GENERATIONS = 400` — Total CMA-ES generations
- `CMAES_SIGMA0 = 0.5` — Initial step size for exploration
- `GEOMETRY_EXPORT_TIMEOUT = 20` — Seconds before generate_gripper.py is considered stuck
- `MAX_ACTIVE_SOFA_PROCS = 12` — Throttle to avoid resource exhaustion

---

### 1a. **optimize_config.py** — Centralized Configuration

**Purpose:** Consolidate all hardcoded defaults, paths, tuning parameters, and CMA-ES settings in one place.

**Contents:**
- SOFA paths and runtime detection (RUNSOFA_EXE, SOFA_ROOT, etc.)
- Fixed model parameters not being optimized (MESH_FIXED, RING_FIXED)
- CMA-ES optimizer settings (N_PARALLEL, N_GENERATIONS, SIGMA0, startup trials)
- Simulation scoring thresholds (early stop time, floor/pickup Y thresholds, mass ramp settings)
- Environment builder: `build_env()` function to inject parameters into SOFA process environment

**Key Function:**
- `build_env()` — Builds subprocess environment with SOFA paths and scoring parameters

---

### 1b. **optimize_geometry.py** — Geometry Generation & Rendering

**Purpose:** Manage the full pipeline from trial parameters to STL and preview images.

**Key Functions:**
- `params_from_trial(trial)` — Sample one set of gripper parameters from Optuna trial using suggest_float ranges
- `generate_stl_for_trial(trial_dir, config)` — Write config to lab_config.jsonc, call generate_gripper.py, rename collision STL, return paths
- `render_stl_preview(visual_stl, trial_dir, gen_index, trial_index)` — Render offscreen PNG using pyvista, save to trial dir and flat gallery
- `resolve_failed_preview_image(candidates)` — Find placeholder image for failed trials

**Error Types:**
- `GeometryExportTimeoutError` — generate_gripper.py exceeded timeout
- `GeometryExportFailureError` — generate_gripper.py exited with error

---

### 1c. **optimize_sofa.py** — SOFA Process Management

**Purpose:** Launch SOFA simulations and manage Windows process groups for clean shutdown.

**Key Functions:**
- `launch_sofa(collision_stl, score_path, status_path, gen_index, trial_index, run_index, env)` — Spawn one SOFA subprocess with environment and STL path
- `wait_for_geometry_slot(processes, limit, gen_index, trial_index)` — Throttle geometry generation to prevent starving SOFA
- `active_sofa_process_count(processes)` — Count running SOFA instances
- `ensure_windows_sofa_job()` — Create Windows job object for graceful cleanup
- `attach_process_to_sofa_job(proc)` — Attach child process to job for cascading termination

**Features:**
- Windows-specific: sets process priority to BELOW_NORMAL and creates job objects
- Unix-compatible: silently skips Windows-only features on other platforms
- Full detachment from parent console to prevent ghost processes

---

### 1d. **optimize_scoring.py** — Score Collection & Progress

**Purpose:** Read simulation results, apply consistency penalties, and track progress.

**Key Functions:**
- `read_score(score_path)` — Parse cube_z_final from JSON, return -inf if missing
- `aggregate_trial_scores(valid_scores)` — Apply mean/median aggregation and consistency penalty
- `write_run_status(path, data)` — Atomic write of per-run status for the monitor window
- `write_gen_summary(gen_dir, gen_index, scores)` — Compute and write generation summary.json
- `write_progress(gen_index, trials_done_in_gen, all_scores)` — Write progress.json for UI progress bar
- `cleanup_generation_status_files(gen_dir)` — Delete status files with Windows lock retry logic

---

### 1e. **optimize_utils.py** — Utilities

**Purpose:** Miscellaneous helper functions for directories and cleanup.

**Key Functions:**
- `reset_trials_dir()` — Wipe and recreate trials/ directory
- `cleanup_collision_stls(collision_stls_by_trial)` — Delete all collision STL files for a generation
- `delete_after_delay(path, delay)` — Background daemon thread to delete file after delay

---

### 2. **app/src/generation/generate_gripper.py** — Config-to-Gripper Generator
**Purpose:** Read `config/lab_config.jsonc` and generate the corresponding gripper meshes.

**Called By:** `optimize.py` and the manual workflow.

**Input:** Parameter dictionary from Optuna trial

**Output:** STL file path to collision mesh

**Key Functions:**
- `main()` — Parse config and run export pipeline

**Dependencies:** Calls `app/src/core/export_pipeline.py` to assemble and export the geometry.

---

### 3. **app/src/core/export_pipeline.py** — Mesh Export Pipeline
**Purpose:** Assemble the gripper and export STL/VTK/JSON files.

**Called By:** `generate_gripper.py`

**Workflow:**
1. Validates parameters via `params.py`
2. Assembles full gripper model via `assembly.py`
3. Runs invariant checks (no overlaps, etc.)
4. Meshes the model using gmsh
5. Exports to STL (fine detail + coarse collision version)
6. Optionally exports VTK for visualization and JSON for metadata

**Key Functions:**
- `run_export()` — Main entry point, returns STL path
- `validate_params()` — Check parameter validity
- `model_to_stl()` — Mesh and export to STL
- `export_leg_attachment_json()` — Export attachment points

---

### 4. **app/src/core/assembly.py** — Gripper Assembly
**Purpose:** Build the complete gripper from the individual parametric parts.

**Called By:** `export_pipeline.py`

**Workflow:**
1. Builds body cylinder (mount ring)
2. Builds left and right pincer fingers
3. Builds 4 legs with attachment points
4. Positions all parts in world space

**Key Function:**
- `assemble_model()` — Returns complete gripper Workplane

---

### 5. **app/src/core/gripper_parts.py** — Part Builders
**Purpose:** Build the gripper subcomponents used by the assembly step.

**Called By:** `assembly.py`

**Key Functions:**
- `build_pincer()` — Parametric gripper finger with profile
- `build_leg()` — Individual attachment leg
- `build_pincers_only()` — Export just the pincers (collision mesh)

---

### 6. **lab_shapeOPT.py** — SOFA Simulation Scene
**Purpose:** Define the SOFA scene that loads the gripper and evaluates the grasp.

**Called By:** `app/src/optimization/optimize.py` via subprocess: `runSofa.exe lab_shapeOPT.py`

**Input:** Environment variables (gripper STL path, simulation thresholds, etc.)

**Output:** JSON file containing score and failure reason

**Simulation Loop:**
1. Loads gripper STL
2. Adds a deformable cube to grasp
3. Runs gripper closure and lift
4. Monitors cube position and success criteria
5. Writes final score to JSON

**Score Logic:**
- **Success:** Cube lifted above FLOOR_Y_THRESHOLD → score = (height gained)
- **Failure:** Cube on floor or early stop → score = -300.0

---

### 7. **app/src/core/params.py** — Parameter Schema
**Purpose:** Define the gripper parameter dataclass, default values, search ranges, and validation.

**Used By:** Everyone (generate_gripper, export_pipeline, assembly, etc.)

**Key Class:**
- `ModelParams` — Dataclass with all ~25 gripper parameters
  - Pincer geometry (width, profile, tilt, angle, distance)
  - Leg geometry (length, width, height, angle)
  - Mesh settings (resolution, VTK export flag)

**Validation:** Checks parameter bounds and consistency

---

### 2. **app/src/analysis/analyze_results.py** — Result Analysis Orchestrator

**Purpose:** Main entry point for analyzing optimization results. Thin orchestrator that delegates to specialized analysis modules.

**Imports from (modular structure):**
- `analyze_config.py` — Configuration constants for analysis (directories, aggregation settings)
- `analyze_io.py` — Data loading from trials directory with fallback logic
- `analyze_leaderboard.py` — Ranking and statistics display
- `analyze_plotting.py` — Matplotlib visualization

**Key Function:**
- `main()` — Load trial data, print leaderboard ranking, display interactive plot

**How to Use:**
```bash
cd app/src/analysis
python analyze_results.py
```

**Outputs:**
1. Terminal leaderboard showing top 10 trials with scores and generation index
2. Failure summary (total failed trials and per-generation breakdown)
3. Interactive matplotlib window showing:
   - Scatter plot of all trials by generation vs score (blue = success, red X = failure)
   - Green dashed line: rolling average score per generation
   - Red solid line: best-so-far score trend
   - Vertical gray lines: generation breaks
4. Full results available in `runtime/trials/` (gen_*/summary.json files)

**Useful For:**
- Ranking gripper designs by performance
- Identifying convergence behavior
- Finding optimal parameter ranges
- Copying best trial config back into manual workflow

---

### 2a. **analyze_config.py** — Analysis Configuration

**Purpose:** Centralize analysis constants and settings.

**Contents:**
- `TRIALS_DIR` — Base directory for all trial data
- `TOP_X = 10` — Number of top trials to display in leaderboard
- `CENTERED_AVG_HALF_WINDOW = 10` — Rolling average window size
- `CONSISTENCY_PENALTY_COEF` — Loaded from environment for consistency penalty
- `SCORE_AGGREGATION` — Loaded from environment (mean or median selection)

---

### 2b. **analyze_io.py** — Trial Data Loading

**Purpose:** Comprehensive data aggregation from trials directory with fallback logic.

**Key Function:**
- `load_all_trials()` — Walks all gen_*/trial_* folders and aggregates results
  - Handles both modern format (trial_stats.json) and legacy format (separate JSON files)
  - Applies consistency penalty if applicable
  - Returns list of trial dicts with: gen_index, trial_index, score, final_score, failed, run_scores
  
- `load_gen_summaries()` — Read pre-computed generation summary files if available

**Handles:**
- Missing score files (treated as failure)
- Runs with multiple scores per trial (applies aggregation)
- Legacy single-score format compatibility

---

### 2c. **analyze_leaderboard.py** — Ranking & Statistics

**Purpose:** Display optimization results in ranked format with statistics.

**Key Function:**
- `print_leaderboard()` — Ranks all valid trials by final score and prints formatted table
  - Displays trial index, generation, score
  - Marks best trial with ★ symbol
  - Shows total failure count
  - Breaks down failures by generation

---

### 2d. **analyze_plotting.py** — Visualization

**Purpose:** Create interactive multi-series plot of optimization history.

**Key Function:**
- `plot_combined()` — Generates matplotlib figure with multiple overlays:
  - Trial scatter plots (generation vs score)
  - Rolling average trend line (green dashed)
  - Best-so-far cumulative line (red solid)
  - Generation break markers (gray dashed vertical lines)
  - Legend and formatted axis labels

**Dependencies:** Matplotlib with interactive window support (mpl_connect for user interaction)

---

### 3. **app/src/generation/generate_gripper.py** — Config-to-Gripper Generator
**Purpose:** Read `config/lab_config.jsonc` and generate the corresponding gripper meshes.

**Called By:** `optimize.py` and the manual workflow.

**Input:** Parameter dictionary from Optuna trial

**Output:** STL file path to collision mesh

**Key Functions:**
- `main()` — Parse config and run export pipeline

**Dependencies:** Calls `app/src/core/export_pipeline.py` to assemble and export the geometry.

---

### 4. **app/src/core/export_pipeline.py** — Mesh Export Pipeline
**Purpose:** Assemble the gripper and export STL/VTK/JSON files.

**Called By:** `generate_gripper.py`

**Workflow:**
1. Validates parameters via `params.py`
2. Assembles full gripper model via `assembly.py`
3. Runs invariant checks (no overlaps, etc.)
4. Meshes the model using gmsh
5. Exports to STL (fine detail + coarse collision version)
6. Optionally exports VTK for visualization and JSON for metadata

**Key Functions:**
- `run_export()` — Main entry point, returns STL path
- `validate_params()` — Check parameter validity
- `model_to_stl()` — Mesh and export to STL
- `export_leg_attachment_json()` — Export attachment points

---

### 5. **app/src/core/assembly.py** — Gripper Assembly
**Purpose:** Build the complete gripper from the individual parametric parts.

**Called By:** `export_pipeline.py`

**Workflow:**
1. Builds body cylinder (mount ring)
2. Builds left and right pincer fingers
3. Builds 4 legs with attachment points
4. Positions all parts in world space

**Key Function:**
- `assemble_model()` — Returns complete gripper Workplane

---

### 6. **app/src/core/gripper_parts.py** — Part Builders
**Purpose:** Build the gripper subcomponents used by the assembly step.

**Called By:** `assembly.py`

**Key Functions:**
- `build_pincer()` — Parametric gripper finger with profile
- `build_leg()` — Individual attachment leg
- `build_pincers_only()` — Export just the pincers (collision mesh)

---

### 7. **lab_shapeOPT.py** — SOFA Simulation Scene
**Purpose:** Define the SOFA scene that loads the gripper and evaluates the grasp.

**Called By:** `app/src/optimization/optimize.py` via subprocess: `runSofa.exe lab_shapeOPT.py`

**Input:** Environment variables (gripper STL path, simulation thresholds, etc.)

**Output:** JSON file containing score and failure reason

**Simulation Loop:**
1. Loads gripper STL
2. Adds a deformable cube to grasp
3. Runs gripper closure and lift
4. Monitors cube position and success criteria
5. Writes final score to JSON

**Score Logic:**
- **Success:** Cube lifted above FLOOR_Y_THRESHOLD → score = (height gained)
- **Failure:** Cube on floor or early stop → score = -300.0

---

### 8. **app/src/core/params.py** — Parameter Schema
**Purpose:** Define the gripper parameter dataclass, default values, search ranges, and validation.

**Used By:** Everyone (generate_gripper, export_pipeline, assembly, etc.)

**Key Class:**
- `ModelParams` — Dataclass with all ~25 gripper parameters
  - Pincer geometry (width, profile, tilt angle, position, etc.)
  - Leg geometry (all 4 legs' dimensions and angles)
  - Mesh settings (resolution, export options)

**Validation:** Checks parameter bounds and consistency

---

### 9. **app/src/core/geometry_helpers.py** — Geometry Utilities
**Purpose:** Helper functions for geometric operations and coordinate transformations.

**Used By:** `gripper_parts.py`, `assembly.py`

**Key Functions:**
- Polygon creation and profiling utilities
- Coordinate transformations and rotations
- Profile calculations for gripper geometry

---

### 10. **app/src/core/io_utils.py** — I/O Utilities
**Purpose:** Handle STL and VTK file operations.

**Used By:** `export_pipeline.py`

**Key Functions:**
- `write_stl()` — Export CadQuery Workplane to STL file
- `write_vtk()` — Optional VTK export for 3D visualization

---

## Configuration Files

### **config/lab_config.jsonc**
Active gripper parameters for the manual workflow.

**Contents:**
- Pincer geometry (width, profile, tilt angle, position, etc.)
- Leg geometry (all 4 legs' dimensions and angles)
- Mesh settings (resolution, export options)

### **config/lab_config_working.jsonc**
Baseline-only gripper parameters.

Use this as a reference if you want the plain starting gripper.
If you want to run the SOFA scene with that baseline, copy its values into `config/lab_config.jsonc` first.

---

## Process A — Test One Gripper From Config

Use this when you already have a config and want to run one gripper in SOFA.

1. Edit `config/lab_config.jsonc`
2. Run `python app/src/generation/generate_gripper.py`
3. This writes the gripper meshes and copies the collision STL to `assets/data/meshes/centerparts/new_gripper_collision.stl`
4. Launch `lab_shapeOPT.py` in SOFA to simulate that gripper

---

## Process B — Optimize Gripper Then Re-Test Best Candidates

Use this when you want automatic search for high-performing geometries.

1. Run `python app/src/launch/launch_optimize.py`
2. For each generation, it creates a folder under `runtime/trials/gen_xxxx/`
3. Each trial folder contains the trial config, preview image, and score files
4. After the run, open `app/src/analysis/analyze_results.py` to rank the results and plot the score history
5. Copy the best trial parameters into `config/lab_config.jsonc`
6. Re-run Process A to inspect the selected gripper in the scene

---

## Running the Lab

### **1. Launching Through EmioLabs**

This lab is designed to be launched through EmioLabs. The markdown guides and buttons in the project are the intended entry points.

If you want to run things from the console instead, use the steps below.

### **2. Process A: Build and Simulate One Gripper**
```bash
python app/src/generation/generate_gripper.py
```
- Reads `config/lab_config.jsonc`
- Exports STL/VTK/JSON
- Copies collision STL into `data/meshes/centerparts/`

Then launch the SOFA scene with your usual lab workflow (or from the command line):
```bash
"C:\Users\Cesar\AppData\Local\Programs\emio-labs\resources\sofa\bin\runSofa.exe" -l SofaPython3 lab_shapeOPT.py
```

### **3. Process B: Run Optimization**
```bash
python app/src/launch/launch_optimize.py
```
- Installs/refreshes dependencies in `runtime/modules/site-packages`
- Runs optimization with current defaults from `app/src/optimization/optimize.py`
- Saves results to `runtime/trials/gen_NNNN/`

### **4. Watch Progress**
The UI progress bar polls `runtime/trials/progress.json` (updated after each trial).

### **5. Analyze Results (After Optimization)**
```bash
python app/src/analysis/analyze_results.py
```
- Displays top 10 trials
- Shows interactive matplotlib visualization

### **6. Apply Best Trial to Manual Scene**
1. Copy selected trial params into `config/lab_config.jsonc`
2. Run `python app/src/generation/generate_gripper.py`
3. Launch `lab_shapeOPT.py` to test visually and physically

---

## Environment Setup

**Dependencies:** See `app/requirements.txt`
- Optuna (optimization framework)
- CadQuery (CAD geometry)
- gmsh (meshing)
- numpy, matplotlib (analysis)
- SOFA (simulation, installed separately in emio-labs)

**To Install:**
```bash
pip install -r app/requirements.txt
```

---

## Optimization Settings (in optimize.py)

| Variable | Default | Meaning |
|----------|---------|---------|
| `N_PARALLEL` | 10 | Trials per generation (must be at least 4) |
| `N_GENERATIONS` | 400 | Total CMA-ES generations |
| `N_REPEATS` | 2 | Simulation runs per trial (averaged) |
| `FLOOR_Y_THRESHOLD` | -235.0 | Y position below = gripper failed |
| `EARLY_STOP_SIM_TIME` | 1.0 | Early floor-check time (seconds) |

---

## Troubleshooting

### **"invalid bounds" AssertionError**
- CMA-ES received parameters outside declared bounds
- **Fix:** Check `x0` initial point matches parameter ranges in `params_from_trial()`

### **"divide by zero" RuntimeWarning**
- CMA-ES needs at least 4 parallel candidates
- **Fix:** Keep `N_PARALLEL >= 4` in `app/src/optimization/optimize.py`

### **All trials score -300 (FAIL)**
- Gripper never picks up the cube
- **Causes:** Geometry overlaps, pincer too weak, collision mesh wrong
- **Debug:** Check STL file in `trials/gen_NNNN/` and SOFA logs
- Most of the first generations are actually fails, check for th preview images to have a feel as too if it should be capable or not, if you have a doubt consider generating the pincer yourself and looking at the simulation

### **SOFA subprocess crashes**
- Check RUNSOFA_EXE path and lab_shapeOPT.py exists
- Verify SOFA installation in emio-labs

---

## Next Steps for Development

1. **Add convergence criteria** — Early stop if score plateaus
2. **Parallel SOFA speedup** — Use SOFA batch mode for faster runs
3. **Multi-objective optimization** — Add gripper mass as secondary objective
4. **Export best designs** — Auto-generate CAD files from top trials
5. **Parameter sensitivity** — Analyze which parameters matter most

---

## References

- **Optuna:** https://optuna.readthedocs.io/
- **CAdQuery:** https://cadquery.readthedocs.io/
- **SOFA:** https://www.sofa-framework.org/
- **CMA-ES:** https://en.wikipedia.org/wiki/CMA-ES

---

*Lab created for gripper morphological optimization in emio-labs v25.12.00*
