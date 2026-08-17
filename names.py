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

# Per-finger collision meshes (same distal fraction as GRIPPER_COLLISION_STL,
# but each finger kept as its own solid/file). SOFA loads these as two
# separate collision bodies so the fingers can be tested against each other —
# a single merged mesh/collision model can never register self-contact.
GRIPPER_COLLISION_FINGER_STLS = (
    f"{GRIPPER_NAME}_collision_finger1.stl",
    f"{GRIPPER_NAME}_collision_finger2.stl",
)

# Emio leg part name (stock blue legs shipped with the platform; the
# fallback used when no trial-generated leg is supplied via OPT_LEG_NAME).
LEG_NAME = "blueleg"

# The lab's own generated leg (manual "Generate" button, LegParams.export_stem
# default). Deliberately distinct from LEG_NAME: legs/ is a directory shared
# with the rest of the emio-labs platform, so the lab must never overwrite
# the stock blueleg files other labs may also read.
LEG_WORKING_NAME = "shapeopt_leg"

# Subdirectory of assets/data/meshes/ where center-part meshes are deposited
# for SOFA to find.
CENTERPARTS_DIRNAME = "centerparts"

# Subdirectory of assets/data/meshes/ where leg meshes/positions are
# deposited for SOFA to find (parts.leg.Leg reads <legName>.stl/.txt here).
LEGS_DIRNAME = "legs"
