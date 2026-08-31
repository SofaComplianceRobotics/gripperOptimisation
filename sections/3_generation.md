::::: collapse Geometry Generation

### Geometry Generation

The generation step turns the numbers of `lab_config.jsonc` into actual meshes.
a CAD kernel one gripper and one leg; a mesher then turns them into the files SOFA needs:

- an **STL** surface mesh for visualization,
- a coarser **collision STL** used for contact detection in the tests,
- a **VTK** volume mesh (tetrahedra) for the deformable model,
- a **JSON** file with the poses of the leg attachments.

In the dashboard, open the **Generate** tab, click **Generate**, and open the resulting preview to inspect your gripper in 3D.

::: highlight
#icon("warning") **Warning:**
Not every parameter combination produces a valid solid. Invalid values are rejected before generation by the parameter validity rules, but some geometrically extreme combinations can still make the CAD operations fail.
During optimization such candidates are simply discarded with a penalty score, failure is an expected part of exploring a shape space.
:::

##### Reference designs

The folder `cool_grippers/` contains curated parameter sets saved from past optimization runs, designs worth keeping as references or starting points. Each subfolder holds one complete config in the same format as the active one. To try one, copy its content into `config/lab_config.jsonc` and regenerate.

:::: exercise
**Exercise 3:**

Generate the gripper with the change you made in Exercise 2 and look at the preview. Then go back to `config/lab_config.jsonc`, play around with different values for a few parameters, and regenerate each time to see how the shape responds. You do not have to keep values inside their search range: anything out of range is clamped back to the nearest bound, and the **Generate** tab log lists every `[clamp]` it applied.
::::

:::::
