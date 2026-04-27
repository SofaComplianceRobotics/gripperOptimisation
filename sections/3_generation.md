::: collapse Generate 3D model
### Generation

Generate STL, VTK and JSON from `lab_config.json`:

#python-button("assets/labs/lab_shapeOPT/app/src/generation/generate_gripper.py")

Generate a fine-mesh version for real-life 3D printing (`new_gripper_print.stl`):

#python-button("assets/labs/lab_shapeOPT/app/src/generation/generate_gripper_fine.py")

#icon("info-circle") The fine mesh uses 2mm / 0.8mm triangle sizes (vs the simulation mesh). It takes longer to generate but produces a higher-quality surface for printing.

#icon("info-circle") Generated files are copied into `assets/labs/lab_shapeOPT/runtime/exports` and `assets\data\meshes\centerparts`.

:::