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

### Just want to run it (no terminal, no git)

1. In EmioLabs: **Labs → Configure Labs**, paste `https://github.com/SofaComplianceRobotics/gripperOptimisation/archive/refs/heads/main.zip` into the path/URL field, click **Add**. This downloads, unzips and registers the lab for you.
2. Open the lab, click the **install dependencies** button once. It runs as the emio-labs bundled Python automatically (EmioLabs puts it first on PATH for any `#python-button`), installs sofaopt + the pinned geometry/dashboard stack, and falls back to a plain `pip install` from GitHub if git isn't on the machine.
3. Click the **launch dashboard** button.

Updating later means repeating step 1 (Configure Labs re-copies the zip over the existing folder — see the caveat under development install below) then step 2 again.

### Install for development (clone)

Requires [git](https://git-scm.com/download/win) (or `winget install --id Git.Git -e --source winget`). From `<emio-labs assets>\labs\` (on Windows, the live one EmioLabs actually reads is normally `%USERPROFILE%\emio-labs\<version>\assets\labs`, not the copy next to the installed exe):

```powershell
git clone https://github.com/SofaComplianceRobotics/gripperOptimisation.git lab_shapeOPT
powershell -ExecutionPolicy Bypass -File lab_shapeOPT\tools\install_dev.ps1
```

`install_dev.ps1` auto-detects the emio-labs bundled Python (pass `-SofaPy <path>` if it can't — e.g. a portable install run from somewhere other than the standard `Programs\emio-labs`), clones or updates `sofaopt` next to itself, installs both into that Python, and registers `lab_shapeOPT` in `labsConfig.json`. Safe to re-run any time, e.g. after a `git pull`. Once registered, the lab's own **install dependencies** button (inside EmioLabs) does the same sofaopt/deps step and reuses the same `sofaopt` clone, so either works for later updates.

Then launch from the EmioLabs platform button, or directly:

```powershell
& $SofaPy lab_shapeOPT\launcher\launch_web.py
```

<details>
<summary>What the script does, step by step (for doing it by hand, or debugging)</summary>

```powershell
$SofaPy = "$env:LOCALAPPDATA\Programs\emio-labs\resources\sofa\bin\python\python.exe"

git clone https://github.com/SofaComplianceRobotics/SofaOptimisation.git
& $SofaPy -m pip install -e ".\SofaOptimisation[dashboard,preview]"
& $SofaPy -m pip install -r ".\lab_shapeOPT\tools\requirements-bundle.txt"
```

Then add this to `assets\labs\labsConfig.json`'s `"labs"` array:
```json
{ "name": "lab_shapeOPT", "filename": "lab_shapeOPT.md", "title": "Shape Optimization", "description": "optimise the shape of a structure to meet a target performance" }
```
</details>

### Pre-built bundle

`tools/build_bundle.ps1` produces a self-contained bundle in `dist/` (source + all deps in
`modules/site-packages/`) that a user unzips and runs with no pip or venv step. `dist/` is
git-ignored and holds nothing by default — build a fresh zip (after adding `sofaopt` to
`tools/requirements-bundle.txt`) before handing it to anyone.

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
runSofa.exe -l SofaPython3 manual_scenes/lab_shapeOPT_inverse.py
```

Run the optimization loop:
```bash
python launcher/optimize.py
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
├── config/            # lab_config.jsonc (the hand-edited gripper) + the optimizer's search-space selection
├── cool_grippers/     # Curated saved gripper designs — reference configs and starting points
├── dashboard/         # The lab's own dashboard tabs (Generate, Scenes, Parameter Guide) layered onto sofaopt's
├── generation/        # Scripts to build a gripper mesh from the active config (standard and fine variants)
├── geometry/          # Parametric geometry engine — part definitions, assembly, mesh export, param schema
├── labtests/          # Auto-discovered simulation tests the optimizer runs to score grippers
├── launcher/          # Entry points: launch_web.py, optimize.py, install_deps.py + the env bootstrap
├── manual_scenes/     # Inverse-mode SOFA scenes: hand control, motor-trajectory recording (feeds the tests)
├── project/           # EmioLabs platform project files (platform-specific format, not Python)
├── runtime/           # Generated at runtime — Optuna DB, session config, trial results, mesh exports
├── sections/          # Markdown shown in the EmioLabs lab page (assembled by lab_shapeOPT.md)
├── tests/             # pytest unit tests for the pure-Python layers
├── tools/             # Dev install and bundle-build scripts
├── names.py           # Single source for cross-component part/file names
└── sofaopt_project.py # The sofaopt adapter: params, tests, SOFA runtime, prepare hook
```

---

## Features

- Parametric gripper geometry (~20 tunable parameters: ring shape, pincer spline, leg-attachment tilt, mesh resolution)
- Parametric leg geometry (4 tunable parameters: end-point position and spline handle lengths) — default reproduces the stock blueleg, motor clip fused on every export; one shape per trial, plugged into all four of the gripper's leg attachments, optimized in the same trial as the gripper (no separate scoring)
- Auto-discovered labtests — drop a folder in `labtests/` and it becomes a selectable test (grasp-hold, random cube pick, gripper tilt, reach zone)
- SOFA simulation integration — each candidate is physically evaluated in the scene
- The CMA-ES search, parallel runSofa scheduling, scoring pipeline, live dashboard and run archiving all come from **sofaopt**
- Lab-side dashboard tabs: generate a mesh, launch a scene, browse the parameter guide

---

## Tech Stack

- **Python** — core language
- **CadQuery / OCP** — parametric CAD geometry
- **gmsh** — mesh generation (STL/VTK export)
- **beziers / scipy** — leg centreline splines
- **SOFA Framework** — physics-based simulation (installed via EmioLabs)
- **sofaopt** — optimization framework (Optuna + CMA-ES, parallel runSofa scheduling, scoring, Dash dashboard, run archiving)
- **pyvista** — offscreen 3D preview rendering for trial thumbnails