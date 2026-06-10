"""Cross-component part and file names.

These names are the contract between the geometry export, the optimizer,
and the SOFA scenes: the export pipeline writes mesh files under them, the
optimizer copies/renames them, and the Emio robot loads its parts by them.
Each name is defined exactly once, here.
"""

# Emio center part (the gripper). Mesh files are exported as
# <GRIPPER_NAME>.stl / .vtk / .json under the centerparts directory.
GRIPPER_NAME = "new_gripper"

# Fine 3D-print export stem — distinct so it never overwrites the sim mesh.
GRIPPER_PRINT_NAME = "new_gripper_print"

# Coarse collision mesh (distal pincer fraction only).
GRIPPER_COLLISION_STL = f"{GRIPPER_NAME}_collision.stl"

# Emio leg part name (stock blue legs shipped with the platform).
LEG_NAME = "blueleg"

# Subdirectory of assets/data/meshes/ where center-part meshes are deposited
# for SOFA to find.
CENTERPARTS_DIRNAME = "centerparts"
