# Lab ShapeOPT

Parametric gripper design and shape optimization lab, built for the EmioLabs platform.

---

## Description

Lab ShapeOPT lets you generate soft robotic gripper geometries from a parameter config and evaluate how well they grasp objects in a SOFA physics simulation. The optimization itself (Optuna + CMA-ES, parallel runSofa scheduling, scoring, live dashboard) is provided by the [sofaopt](https://github.com/SofaComplianceRobotics/SofaOptimisation) framework; this lab is a sofaopt *consumer* — it supplies the gripper parameters, the geometry generator, the test scenes and the scoring (see `sofaopt_project.py`).

---

## Installation

**Prerequisites:** EmioLabs installed (provides SOFA and runSofa.exe).

Everything installs into the **emio-labs bundled Python** (SOFA's `SofaPython3`, currently 3.10) so the dashboard, the optimizer and the runSofa scenes all share one interpreter and one SOFA build. On Windows that interpreter is:

```
%LOCALAPPDATA%\Programs\emio-labs\resources\sofa\bin\python\python.exe
```

### Install for development (clone)

From `<emio-labs>\v25.12.00\assets\labs\`:

```powershell
$SofaPy = "$env:LOCALAPPDATA\Programs\emio-labs\resources\sofa\bin\python\python.exe"

# 1. The lab itself, as assets\labs\lab_shapeOPT
git clone https://github.com/SofaComplianceRobotics/gripperOptimisation.git lab_shapeOPT

# 2. The optimization framework, cloned anywhere, installed editable
git clone https://github.com/SofaComplianceRobotics/SofaOptimisation.git
& $SofaPy -m pip install -e ".\SofaOptimisation[dashboard,preview]"

# 3. The geometry / generation / dashboard dependencies (pinned, verified for 3.10)
& $SofaPy -m pip install -r ".\lab_shapeOPT\tools\requirements-bundle.txt"

# 4. Register the lab: add this block to assets\labs\labsConfig.json -> "labs":
#      { "name": "lab_shapeOPT", "filename": "lab_shapeOPT.md",
#        "title": "Shape Optimization",
#        "description": "optimise the shape of a structure to meet a target performance" }
```

Then launch from the EmioLabs platform button, or directly:

```powershell
& $SofaPy lab_shapeOPT\launcher\launch_web.py
```

### Pre-built bundle

`dist/lab_shapeOPT_bundle_windows.zip` is a self-contained bundle (source + all deps in
`runtime/modules/site-packages/`) built by `tools/build_bundle.ps1`. **The checked-in zip is
stale** — it predates the split into `sofaopt` and does not contain the framework. Rebuild it
with `tools/build_bundle.ps1` (after adding `sofaopt` to `tools/requirements-bundle.txt`)
before handing it to anyone.

---

## Usage

**Run through EmioLabs** (recommended) — use the provided button in optimisation part of the platform.

**Or manually from the terminal:**

Generate a gripper mesh from the active config:
```bash
python generation/generate_gripper.py
```

Launch a SOFA simulation scene:
```bash
runSofa.exe -l SofaPython3 scenes/lab_shapeOPT_inverse.py
```

Run the optimization loop:
```bash
python optimize.py
```

Open the dashboard:
```bash
python launcher/launch_web.py
```

Run the unit tests:
```bash
python -m pytest
```

---

## Project Structure

```
lab_shapeOPT/
├── config/            # Active gripper config files (JSONC) read by generation and optimization
├── cool_grippers/     # Curated saved gripper configs with preview images — reference designs
├── dashboard/         # The lab's own dashboard tabs (Generate, Scenes) layered onto sofaopt's dashboard
├── generation/        # Scripts to build a gripper mesh from the active config (standard and fine variants)
├── geometry/          # Parametric geometry engine — part definitions, assembly, mesh export, param schema
├── labtests/          # Registry of composable simulation tests used by the optimizer to score grippers
├── launcher/          # Entry-point scripts — bootstraps the environment and starts the web interface
├── project/           # EmioLabs platform project files (platform-specific format, not Python)
├── runtime/           # Generated at runtime — Optuna DB, session config, trial results
├── scenes/            # SOFA scene scripts passed directly to runSofa.exe
├── tests/             # pytest unit tests for the pure-Python layers
├── names.py           # Single source for cross-component part/file names
├── sofaopt_project.py # The sofaopt adapter: params, tests, SOFA runtime, prepare hook
└── optimize.py        # Headless optimization entry point (dashboard Run button + CLI)
```

---

## Features

- Parametric gripper geometry (~25 parameters: pincer shape, leg attachment dimensions, tilt angles, etc.)
- Parametric leg geometry (3 params: length, middle curvature via one control point) — default reproduces the stock blueleg, motor clip fused on every export; one shape per trial, plugged into all four of the gripper's leg attachments, optimized in the same trial as the gripper (no separate scoring)
- CMA-ES evolutionary optimization via Optuna — automatic search across generations (provided by sofaopt)
- SOFA simulation integration — each candidate is physically evaluated for grasp success
- Parallel trial execution with process throttling and subprocess cleanup
- Live progress tracking via `runtime/trials/progress.json`
- Results analysis: ranked leaderboard, score history plot, rolling average and best-so-far trends
- Modular labtest system — composable test scenes (grasp-hold, random cube pick, gripper tilt)

---

## Tech Stack

- **Python** — core language
- **CadQuery** — parametric CAD geometry
- **gmsh** — mesh generation (STL/VTK export)
- **SOFA Framework** — physics-based simulation (installed via EmioLabs)
- **sofaopt** — optimization framework (Optuna + CMA-ES, parallel runSofa, live dashboard)
- **pyvista** — offscreen 3D preview rendering
- **Dash / matplotlib** — results visualization and dashboard