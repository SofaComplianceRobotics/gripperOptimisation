::::: collapse Geometry Generation

### Geometry Generation

The generation step turns the numbers of `lab_config.jsonc` into actual meshes.
[CadQuery](https://cadquery.readthedocs.io) builds the ring, the leg attachments and the pincers as solids and fuses them into one gripper; [Gmsh](https://gmsh.info) then meshes the result into the files SOFA needs:

- an **STL** surface mesh for visualization,
- a coarser **collision STL** used for contact detection in the tests,
- a **VTK** volume mesh (tetrahedra) for the deformable model,
- a **JSON** file with the poses of the leg attachments.

In the dashboard, open the **Generate** tab, click **Generate**, and open the resulting preview to inspect your gripper in 3D.

::: highlight
#icon("warning") **Warning:**
Not every parameter combination produces a valid solid. Invalid values are rejected before generation by the validity rules of `geometry/params.py`, but some geometrically extreme combinations can still make the CAD operations fail.
During optimization such candidates are simply discarded with a penalty score — failure is an expected part of exploring a shape space.
:::

##### Reference designs

The folder `cool_grippers/` contains curated parameter sets saved from past optimization runs — designs worth keeping as references or starting points. Each subfolder holds one complete config in the same format as the active one. To try one, copy its content into `config/lab_config.jsonc` and regenerate.

#open-button("assets/labs/lab_shapeOPT/cool_grippers/gripper_3/lab_config_2.jsonc")

|          ![](assets/labs/lab_shapeOPT/cool_grippers/gripper_3/preview.png){width=50%, .center}           |
|:--------------------------------------------------------------------------------------------------------:|
|                       **One of the saved reference designs (`cool_grippers/gripper_3`)**                  |

:::: exercise
**Exercise 3:**

1. In the **Generate** tab, generate the gripper with the change you made in Exercise 2 and look at the preview. Did the pincers change the way you expected?
2. Open the reference config above, copy its values into `config/lab_config.jsonc` (button in the previous section), and generate again.
3. Compare the two shapes. Which one do you *think* will grasp better? Keep your guess in mind — the next sections will let the simulation answer.
::::

:::::
