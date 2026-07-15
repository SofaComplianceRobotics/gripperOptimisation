::::: collapse Introduction

### Introduction

In the previous labs, the design of Emio's legs and gripper was improved *by hand*: you changed a parameter, ran a simulation, looked at the result, and iterated.
This lab automates that loop. An optimization algorithm explores the space of possible gripper shapes on its own, evaluating each candidate in physics simulation, and progressively converges towards designs that grasp well.

The loop it runs, hundreds of times, is:

1. **Generate** — a set of parameter values defines a gripper geometry. CadQuery builds the 3D solid, Gmsh meshes it.
2. **Simulate** — SOFA runs the gripper through one or more physical test scenarios, each in its own isolated subprocess.
3. **Score** — the physics results are aggregated into a single fitness score for the candidate.
4. **Update** — the score feeds back into the optimizer (CMA-ES), which shifts its search towards the promising region of the parameter space.
5. **Repeat** — the next candidates are sampled and evaluated, five in parallel.

::: highlight
##### Why a web dashboard?

Unlike the other labs, this one is driven from a **web page** rather than from buttons in this document.
An optimization run produces a continuous stream of results — scores, progress bars, plots, a leaderboard — that you want to watch **live** while the run is going.
The lab therefore starts a local web server and opens a dashboard in your browser, where every graph updates in real time.
:::

::: highlight
#icon("warning") **Warning:**
The dashboard requires the [sofaopt](https://github.com/SofaComplianceRobotics/SofaOptimisation) optimization framework to be installed in the emio-labs Python (see the lab's `README.md`).
The first launch can take a little longer while the environment is prepared.
:::

Click the button below to start the dashboard. A browser tab should open automatically (if not, browse to `http://localhost:8050`):

#python-button("assets/labs/lab_shapeOPT/launcher/launch_web.py")

:::: exercise
**Exercise 1:**

1. Launch the dashboard with the button above.
2. Take a tour of the tabs and identify the role of each one:
    - **Config** — the active gripper parameters (the file you will edit in the next section)
    - **Generate** — build the gripper meshes from the active parameters
    - **Scenes** — launch SOFA scenes interactively (inverse kinematics, motor recording, watch a test)
    - **Optimise** — select the tests and start/stop an optimization run
    - **Performance** — score history, trends and the leaderboard of the best designs
    - **Progress** — live state of the trials currently being simulated
    - **Parameter Bounds** — the search range of every parameter
    - **Playground** — explore the results of past runs
3. Keep the dashboard open: every following section uses it.
::::

:::::
