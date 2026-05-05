::::: collapse Exported Files

### Open Generated Outputs

Open the simulation mesh files after generation:

**Simulation mesh** (`new_gripper`)

<div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; text-align: center;">

<div>

STL

#icon("play")

#open-button("assets/data/meshes/centerparts/new_gripper.stl")

</div>

<div>

VTK

#icon("cubes")

#open-button("assets/data/meshes/centerparts/new_gripper.vtk")

</div>

<div>

JSON

#icon("align-left")

#open-button("assets/data/meshes/centerparts/new_gripper.json")

</div>

</div>

**Fine mesh for printing** (`new_gripper_print`)

<div style="display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; text-align: center;">

<div>

STL

#icon("play")

#open-button("assets/data/meshes/centerparts/new_gripper_print.stl")

</div>

---

### SOFA & Tools

<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 18px; margin: 14px 0; align-items: stretch;">

<div style="border: 1px solid #d8dde3; border-radius: 12px; padding: 14px 16px; background: #fafbfc; display: flex; flex-direction: column; height: 100%; min-height: 250px;">
<p align="center"><strong>Custom SOFA build</strong></p>
<p align="center">Inverse scene (no recording)</p>

<div style="margin-top: auto; display: grid; gap: 10px;">

#runsofa-button("assets/labs/lab_shapeOPT/lab_shapeOPT_inverse.py")

<p align="center">Recording scene</p>

#runsofa-button("assets/labs/lab_shapeOPT/lab_shapeOPT_recording.py")

<p align="center">Run a single scene</p>

#python-button("assets/labs/lab_shapeOPT/app/src/launch/launch_scene_custom_sofa.py")

<p align="center">Run the optimiser</p>

#python-button("assets/labs/lab_shapeOPT/app/src/launch/launch_optimize_custom_sofa.py")

</div>
</div>

<div style="border: 1px solid #d8dde3; border-radius: 12px; padding: 14px 16px; background: #fafbfc; display: flex; flex-direction: column; height: 100%; min-height: 250px;">
<p align="center"><strong>Analysis & monitoring</strong></p>

<div style="margin-top: auto; display: grid; gap: 10px;">

<p align="center">Benchmark SOFA concurrency</p>

#python-button("assets/labs/lab_shapeOPT/app/src/launch/launch_benchmark_sofa_concurrency.py")

</div>
</div>

</div>

:::::
