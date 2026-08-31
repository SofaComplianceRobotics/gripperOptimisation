::::: collapse The Parametric Gripper

### The Parametric Gripper

For an algorithm to search over shapes, a shape must first be reduced to a list of numbers.
The gripper of this lab is entirely described by **~25 parameters**, stored in a single configuration file, `config/lab_config.jsonc`:

#open-button("assets/labs/lab_shapeOPT/config/lab_config.jsonc")

The parameters fall into four groups:

- **Ring** (`cylinder_*`) - the central ring that connects to the robot: radius, wall thickness, and the heights and angular extents of its three plateaus.
- **Leg attachments** (`leg_attachement_*`) - how the pockets receiving Emio's legs are built.
- **Pincers** (`pincer_*`, `p0_*`, `p1_*`) - the fingers of the gripper. Their curved profile is a spline whose control points are given in **polar coordinates** (a distance and an angle), together with tangent handles that control the smoothness of the curve.
- **Meshing** (`mesh_*`) - how finely the solid is discretized into triangles for the simulation.

::: highlight
#icon("info-circle") **Note:**
The legs themselves are parametric too. Ten extra `leg_*` parameters describe the leg centerline as a Bezier spline; the default values reproduce the stock blue leg exactly.
During optimization, one leg shape is generated per candidate and plugged into all four attachments, so the leg and the gripper are optimized **together** in the same trial.
:::

##### Where do the search bounds come from?

Each parameter the optimizer tunes has a search range `[min, max]` and a set of validity rules: a wall thickness must stay positive, the three plateau angles must fit inside a 45° budget, and so on.
The range is the box the search stays inside; the rules reject combinations that could never form a valid solid, before any time is spent simulating them.
The **Parameter Bounds** tab of the dashboard lists the range of every parameter in the search.
When you generate a gripper by hand, any value in `lab_config.jsonc` that falls outside a parameter's range is clamped back to the nearest bound, and the adjustment is printed as a `[clamp]` line in the **Generate** tab log.

:::: exercise
**Exercise 2:**

1. Open `lab_config.jsonc` with the button above and read through the parameters. Can you guess what `pincer_profile_height` and `p1_dist` control?
2. In the dashboard, open the **Parameter Bounds** tab and find those same parameters. Note their allowed ranges - this is the box inside which the optimizer will search. Now change `pincer_profile_height` in the config to another value inside its range and save the file. You will see the effect in the next section, when you generate the geometry. Stay within the range while you experiment: any value outside it is clamped back to the nearest bound, and the log tells you so.
::::

:::::
