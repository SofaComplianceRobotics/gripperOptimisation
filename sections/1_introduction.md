::: highlight
##### Overview

This lab generates a custom center gripper for Emio directly from parametric CadQuery geometry.
The main workflow is simple: edit values in the lab configuration file, then generate the STL, VTK, and JSON files used by the rest of the pipeline.
:::

::::highlight
#icon("warning") **Warning:**
This lab runs in Emio's embedded Python runtime.
The first generation can take longer because required packages may need to be installed.
If your network or permissions block pip installs, generation will fail until that policy issue is resolved.

::: collapse the following modules will be installed if not already present:    
- numpy    
- cadquery    
- cadquery-ocp    
- gmsh
:::

::::
