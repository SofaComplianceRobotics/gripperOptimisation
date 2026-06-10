# Lab ShapeOPT

Parametric gripper design and shape optimization lab, built for the EmioLabs platform.

---

## Description

Lab ShapeOPT lets you generate soft robotic gripper geometries from a parameter config and evaluate how well they grasp objects in a SOFA physics simulation. An optimization loop (Optuna + CMA-ES) searches the parameter space automatically, scoring hundreds of gripper candidates across generations and surfacing the best-performing designs.

---

## Installation

**Prerequisites:** EmioLabs installed (provides SOFA and runSofa.exe). Python 3.10+.

Dependencies are managed by EmioLabs. If running outside the platform, install the packages used across `geometry/`, `generation/`, `optimization/`, and `dashboard/` manually (CadQuery, gmsh, Optuna, Dash, pyvista, matplotlib).

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
python optimization/orchestrator.py
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
├── config/          # Active gripper config files (JSONC) read by generation and optimization
├── cool_grippers/   # Curated saved gripper configs with preview images — reference designs
├── dashboard/       # Dash web control panel — config editing, run controls, live monitoring
├── generation/      # Scripts to build a gripper mesh from the active config (standard and fine variants)
├── geometry/        # Parametric geometry engine — part definitions, assembly, mesh export, param schema
├── labtests/        # Registry of composable simulation tests used by the optimizer to score grippers
├── launcher/        # Entry-point scripts — bootstraps the environment and starts the web interface
├── optimization/    # CMA-ES optimization loop — trial orchestration, SOFA subprocess management, scoring
├── project/         # EmioLabs platform project files (platform-specific format, not Python)
├── runtime/         # Generated at runtime — Optuna DB, session config, trial results
├── scenes/          # SOFA scene scripts passed directly to runSofa.exe
├── tests/           # pytest unit tests for the pure-Python layers
└── names.py         # Single source for cross-component part/file names
```

---

## Features

- Parametric gripper geometry (~25 parameters: pincer shape, leg dimensions, tilt angles, etc.)
- CMA-ES evolutionary optimization via Optuna — automatic search across generations
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
- **Optuna + CMA-ES** — black-box optimization
- **pyvista** — offscreen 3D preview rendering
- **Dash / matplotlib** — results visualization and dashboard