::::: collapse Simulation Tests and Scoring

### Simulation Tests and Scoring

An optimizer needs a single number telling it how good each candidate is: the **fitness score**.
Here, that number comes from physics: every candidate gripper is mounted on a simulated Emio in SOFA and put through one or more **tests**, each measuring one aspect of grasping.

| Test | What it measures | Runs per candidate |
|---|---|:---:|
| **Grasp Hold** | Grip strength — the cube is moved in erratic patterns and shaken while the gripper tries to hold it. Scored by hold time. | 1 |
| **Random Cube Pick** | Generality — lifts cubes of three different sizes (8/10/12 cm) once each. Scores are summed. | 3 |
| **Tilt Test** | Stability — penalizes grippers that tilt in edge-case poses. | 1 |

Each test lives in its own folder under `labtests/` with a SOFA scene and its scoring rules, and is discovered automatically — the checkboxes you see in the **Optimise** tab come straight from these folders.
Tests with randomness (like Random Cube Pick) run several times per candidate so one lucky or unlucky run does not distort the score.

::: highlight
#icon("info-circle") **Note:**
The contact tests do not use inverse kinematics: SOFA's inverse mode cannot run together with collisions.
Instead, they **replay a pre-recorded motor motion** (opening and closing the gripper) identically for every candidate — so the only thing that varies between two trials is the shape being tested.
The **Scenes** tab is where such recordings are made.
:::

:::: collapse Why isn't every test worth the same?
An easy test can poison an optimization. The Tilt test almost always produces a non-zero score — even a gripper that cannot pick anything up "passes" it to some degree.
If all tests counted equally from the start, the leaderboard would fill with grippers that resist tilt but never grasp.
The scoring therefore keeps the pressure on the hard grasping tests: the Tilt score only matters as a differentiator between grippers that already demonstrated they can hold a cube. This kind of test **gating** is handled by the sofaopt framework.
::::

##### Watching a test

Numbers are useful; watching is better. The **Scenes** tab can launch any test in a live SOFA window with the currently generated gripper, so you can see *why* a design scores the way it does — pincers that never touch the cube, a grasp that slips, a gripper that crumples.

:::: exercise
**Exercise 4:**

1. In the **Scenes** tab, launch the *Grasp Hold* test with the reference gripper you generated in Exercise 3 and watch the whole cycle: descent, closure, shaking, hold.
2. Regenerate your own Exercise-2 gripper (**Generate** tab) and run the same test. Was your guess from Exercise 3 right?
3. Look at the score reported at the end of each run. That single number is all the optimizer will ever see of a candidate.
::::

:::::
