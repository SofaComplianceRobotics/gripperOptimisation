::::: collapse Exported Files
### Open Generated Outputs

After generation, use these buttons to open exported files:
<br>

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
<br>
</div>



<p align="center">Use the sections below to launch the default SOFA workflow, switch to the custom build, or inspect the optimization results.</p>

<p align="center">The custom SOFA launchers now prompt you to choose one or more registered tests before they start.</p>

<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 18px; margin: 14px 0; align-items: stretch;">

<div style="border: 1px solid #d8dde3; border-radius: 12px; padding: 14px 16px; background: #fafbfc; display: flex; flex-direction: column; height: 100%; min-height: 250px;">
<p align="center"><strong>Default SOFA build</strong></p>
<p align="center">Launch scene</p>

<div style="margin-top: auto; display: grid; gap: 10px;">

#runsofa-button("assets/labs/lab_shapeOPT/lab_shapeOPT.py")

<p align="center">Launch recording scene</p>

#runsofa-button("assets/labs/lab_shapeOPT/lab_shapeOPT_recording.py")

<p align="center">Launch optimisation</p>

#python-button("assets/labs/lab_shapeOPT/app/src/launch/launch_optimize.py")
</div>
</div>

<div style="border: 1px solid #d8dde3; border-radius: 12px; padding: 14px 16px; background: #fafbfc; display: flex; flex-direction: column; height: 100%; min-height: 250px;">
<p align="center"><strong>Custom SOFA build</strong></p>
<p align="center">Launch scene</p>

<div style="margin-top: auto; display: grid; gap: 10px;">

#python-button("assets/labs/lab_shapeOPT/app/src/launch/launch_scene_custom_sofa.py")

<p align="center">Launch optimisation</p>

#python-button("assets/labs/lab_shapeOPT/app/src/launch/launch_optimize_custom_sofa.py")
</div>
</div>

<div style="border: 1px solid #d8dde3; border-radius: 12px; padding: 14px 16px; background: #fafbfc; display: flex; flex-direction: column; height: 100%; min-height: 250px;">
<p align="center"><strong>Analysis and monitoring</strong></p>
<p align="center">Analyze results</p>

<div style="margin-top: auto; display: grid; gap: 10px;">

#python-button("assets/labs/lab_shapeOPT/app/src/analysis/analyze_results.py")

<p align="center">Monitor progress</p>

#python-button("assets/labs/lab_shapeOPT/app/src/analysis/progress_monitor.py")

<p align="center">Benchmark concurrency</p>

#python-button("assets/labs/lab_shapeOPT/app/src/launch/launch_benchmark_sofa_concurrency.py")
</div>
</div>

</div>

:::::