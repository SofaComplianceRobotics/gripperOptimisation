# Lab ShapeOPT

Parametric gripper design and shape optimization lab, built for the EmioLabs platform.

---

## Description

Lab ShapeOPT lets you generate soft robotic gripper geometries from a parameter config and evaluate how well they grasp objects in a SOFA physics simulation. An optimization loop (Optuna + CMA-ES) searches the parameter space automatically, scoring hundreds of gripper candidates across generations and surfacing the best-performing designs.

Built for researchers and engineers exploring gripper morphology — no manual tuning required once the loop is running.

---

## Demo

<!-- Add screenshots or screen recordings here -->

---

## Installation

**Prerequisites:** EmioLabs installed (provides SOFA and runSofa.exe). Python 3.10+.

```bash
pip install -r app/requirements.txt
```

---

## Usage

**Run through EmioLabs** (recommended) — use the provided buttons and markdown guides in the platform.

**Or manually from the terminal:**

Generate and simulate one gripper from the active config:
```bash
python app/src/generation/generate_gripper.py
```
Then launch the SOFA scene through EmioLabs or via:
```bash
runSofa.exe -l SofaPython3 lab_shapeOPT.py
```

Run the optimization loop:
```bash
python app/src/launch/launch_optimize.py
```

Analyze results after optimization:
```bash
python app/src/analysis/analyze_results.py
```

---

## Features

- Parametric gripper geometry (~25 parameters: pincer shape, leg dimensions, tilt angles, etc.)
- CMA-ES evolutionary optimization via Optuna — automatic search across generations
- SOFA simulation integration — each candidate is physically evaluated for grasp success
- Parallel trial execution with process throttling and clean subprocess cleanup
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
- **matplotlib** — results visualization

---

## Contributing



---

## License



---

## Credits / Acknowledgments

Built as part of the EmioLabs v25.12.00 platform.
