::::: collapse Introduction

### Introduction

In a previous labs, the design of Emio's legs and gripper was improved *by hand*: you changed a parameter, ran a simulation, looked at the result, and iterated.
This lab automates that loop. An optimization algorithm explores the space of possible gripper shapes on its own, evaluating each candidate in physics simulation, and progressively converges towards designs that grasp well.

The loop it runs, hundreds of times, is:

1. **Generate**: a set of parameter values defines a gripper geometry, which is built as a 3D solid and then meshed for simulation.
2. **Simulate**: SOFA runs the gripper through one or more physical test scenarios.
3. **Score**: the results of theses tests are aggregated into a single fitness score for the candidate, this dictates how good a gripper is.
4. **Update**: the score feeds into the optimizer using the CMA-ES algorithm, which shifts its search towards the promising region of the parameter space.
5. **Repeat**: the next candidates are sampled and evaluated.

::: highlight
#icon("warning") **Warning:**
The dashboard requires the [sofaopt](https://github.com/SofaComplianceRobotics/SofaOptimisation) optimization framework to be installed in the emio-labs Python (see the lab's `README.md`).
The first launch can take a little longer while the environment is prepared.
:::

Click the button below to start the dashboard. A browser tab should open automatically (if not, browse to `http://localhost:8050`):

#python-button("assets/labs/lab_shapeOPT/launcher/launch_web.py")

Launch the dashboard with the button above, then take a tour of the tabs and identify the role of each one:

- **Config**: the active gripper parameters (the file you will edit in the next section)
- **Generate**: build the gripper meshes from the active parameters
- **Scenes**: launch SOFA scenes interactively (inverse kinematics, motor recording, watch a test)
- **Optimise**: select the tests and start/stop an optimization run
- **Performance**: score history, trends and the leaderboard of the best designs
- **Progress**: live state of the trials currently being simulated
- **Parameter Bounds**: the search range of every parameter
- **Playground**: a sandbox to try search algorithms on toy 2D landscapes before running the real thing

Keep the dashboard open: every following section uses it.

:::: exercise
**Exercise 1:**

1. Go to the **Playground** tab. The heatmap is a landscape: brighter is a higher score, and the marked dots are where the algorithm has sampled so far. It is the same kind of search this lab runs over the gripper's parameters, just with 2 of them instead of two dozen so the whole thing fits on screen.

2. Start with the most obvious strategy. Set **Algorithm** to **Grid search**, **Map mode** to **Default**, **Seed** to `0`, and leave **Grid pts/axis** at `8`. Press **▶ Run**. The points land on a regular lattice: grid search fixes a resolution up front (here 8 points per axis, so $8^2 = 64$ evaluations in 2D) and checks every combination at that resolution, ignoring the scores as they come in and ignoring the budget entirely.

3. Without clearing, switch **Algorithm** to **Random search**, set **Budget** to `60`, keep **Seed** `0`, and press **▶ Run** again. The points scatter with no pattern. Random search does not learn from its results either, but for the same number of evaluations it covers the square more evenly than the grid and never locks itself into a resolution chosen blindly: it is the more efficient of the two.

4. Without clearing, switch **Algorithm** to **CMA-ES** (keep Budget `60`, Seed `0`) and press **▶ Run** once more. A new curve appears in the right-hand panel: by the end of its 60 trials its points are clustered tightly around the peak, and its curve reaches a near-maximum score using a fraction of the evaluations the other two needed. This one uses every score to decide where to sample next.
::::

:::: quiz
**Question:**
::: question Looking at the curves you just got, was CMA-ES actually worth using here?

Not really, on this map: with a budget of 60 spread over only 2 dimensions, even random search's points are dense enough that some of them land close to the peak. CMA-ES gets there a bit faster, but the gap is modest. On an easy, low-dimensional problem, brute luck goes a long way.
:::
::::

Now see how that changes as the search gets harder. Set **Dimensions** to `8` (keep Map mode **Default**, Budget `60`, Seed `0`), then press **⟳ Generate map** and confirm (this also clears the previous runs). Switch to **Grid search** first: at the default 8 points per axis it is disabled from 5 dimensions up, with a warning explaining why. Grid search uses the same resolution on every axis, so its cost is (points per axis) raised to the power of the number of dimensions: $8^8$ is about 16.7 million evaluations. Even shrinking to 3 points per axis is $3^8 = 6561$, and 5 points per axis is $5^8 = 390{,}625$: a budget of 60 is nowhere near, and it only gets worse with more parameters.

Now run **Random search** (**▶ Run**), then **CMA-ES** (**▶ Run**); the other two, Bayesian and REINFORCE, are there too if you want to compare more. Random search's points are spread so thin across 8 dimensions that almost none land near the peak. CMA-ES is the only one still homing in on the peak, decimating it. That gap between "a few extra parameters" and a search that still works is exactly why this lab needs a real optimizer instead of luck, and grid search refusing to even run here is the same lesson from a different angle.

:::::
