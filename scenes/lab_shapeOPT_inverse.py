"""
Lab ShapeOPT Inverse Scene - Manual inverse-mode control.

Use this to manually drive the gripper via the inverse solver GUI.
The robot/GUI setup is shared with the recording scene — see
scenes/_manual_scene.py.
"""

from launcher.bootstrap import bootstrap_lab

SCRIPT_DIR, SRC_ROOT, APP_ROOT, LAB_ROOT = bootstrap_lab(__file__)

from scenes._manual_scene import build_manual_scene


def createScene(rootnode):
    """Build the inverse-mode scene for manual gripper control via the SOFA ImGui."""
    nodes, args = build_manual_scene(rootnode, LAB_ROOT)
    if nodes is None:
        return

    if args.connection:
        nodes.emio.addConnectionComponents()

    return rootnode