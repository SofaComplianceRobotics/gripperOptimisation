::: highlight
##### Overview

This lab generates a parametric soft gripper for Emio from a simple config file and can optimise its shape automatically using physics simulations.

**Two workflows:**

- **Manual design** — edit values in `lab_config.jsonc`, generate the mesh, then run SOFA to test it yourself.
- **Shape optimisation** — run the CMA-ES optimiser, which generates hundreds of gripper variants, simulates each one in parallel, and converges on the best-scoring shape.

Both start from the same config file and share the same mesh export pipeline.
:::

::::highlight
#icon("warning") **First run may take a few minutes**

This lab runs in Emio's embedded Python runtime. Required packages are installed automatically on first use. If your network or security policy blocks `pip`, generation will fail until that is resolved.

::: collapse Packages installed on first use
- `numpy`
- `cadquery`
- `cadquery-ocp`
- `gmsh`
:::

::::
