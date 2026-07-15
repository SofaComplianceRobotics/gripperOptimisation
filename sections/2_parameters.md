::::: collapse The Parametric Gripper

### The Parametric Gripper

For an algorithm to search over shapes, a shape must first be reduced to a list of numbers.
The gripper of this lab is entirely described by **~25 parameters**, stored in a single configuration file, `config/lab_config.jsonc`:

#open-button("assets/labs/lab_shapeOPT/config/lab_config.jsonc")

The parameters fall into four groups:

- **Ring** (`cylinder_*`) — the central ring that connects to the robot: radius, wall thickness, and the heights and angular extents of its three plateaus.
- **Leg attachments** (`leg_attachement_tilt_angle`) — how the pockets receiving Emio's legs are tilted.
- **Pincers** (`pincer_*`, `p0_*`, `p1_*`) — the fingers of the gripper. Their curved profile is a spline whose control points are given in **polar coordinates** (a distance and an angle), together with tangent handles that control the smoothness of the curve.
- **Meshing** (`mesh_*`) — how finely the solid is discretized into triangles for the simulation.

::: highlight
#icon("info-circle") **Note:**
The legs themselves are parametric too. Ten extra `leg_*` parameters describe the leg centerline as a Bezier spline; the default values reproduce the stock blue leg exactly.
During optimization, one leg shape is generated per candidate and plugged into all four attachments, so the leg and the gripper are optimized **together** in the same trial.
:::

##### Where do the search bounds come from?

Every parameter carries its own metadata in `geometry/params.py` (and `geometry/leg_params.py` for the legs): a search range `[min, max]` for the optimizer and validity rules (for instance, a wall thickness must stay positive).
Not all parameters are searched: only the ones carrying a search range are tunable at all (11 currently); `config/lab_config.optimization.json` lists which of those the optimizer is allowed to touch right now. Everything else — ring dimensions, pincer profile, mesh sizing — is permanently fixed at its configured value.
You can inspect all of this in the **Parameter Bounds** tab of the dashboard.

:::: exercise
**Exercise 2:**

1. Open `lab_config.jsonc` with the button above and read through the parameters. Can you guess what `pincer_profile_height` and `p1_dist` control?
2. In the dashboard, open the **Parameter Bounds** tab and find those same parameters. Note their allowed ranges — this is the box inside which the optimizer will search.
3. Change `pincer_profile_height` in the config (stay within its bounds) and save the file. You will see the effect of your change in the next section, when you generate the geometry.
::::

:::::
