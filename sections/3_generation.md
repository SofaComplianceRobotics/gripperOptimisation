::: collapse Generate 3D model

### Generation

Generate STL, VTK, and JSON files from the current `lab_config.jsonc`:

#python-button("assets/labs/lab_shapeOPT/app/src/generation/generate_gripper.py")

Generate a high-resolution mesh for 3D printing (`new_gripper_print.stl`):

#python-button("assets/labs/lab_shapeOPT/app/src/generation/generate_gripper_fine.py")

#icon("info-circle") The fine mesh uses 2.0 mm / 0.8 mm triangles instead of the simulation mesh settings. It takes longer but gives a smoother surface suitable for printing.

---

**Output files**

| File | Where | Description |
|---|---|---|
| `new_gripper.stl` | `data/meshes/centerparts/` | Visual surface mesh |
| `new_gripper.vtk` | `data/meshes/centerparts/` | FEM volume mesh for SOFA |
| `new_gripper.json` | `data/meshes/centerparts/` | Geometry metadata |
| `new_gripper_collision.stl` | `data/meshes/centerparts/` | Coarse collision mesh for the physics engine |
| `new_gripper_print.stl` | `data/meshes/centerparts/` | Fine mesh for 3D printing (fine-gen only) |

Copies of all files are also written to `runtime/exports/`.

:::
