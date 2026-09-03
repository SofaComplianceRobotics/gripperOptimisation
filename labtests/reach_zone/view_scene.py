"""
view_scene: standalone viewer for reach_zone's result.

Not a registered labtest (no test.json / scoring.py, so labtests/registry.py
never picks it up) -- scene.py launches this by hand once its sweep finishes
on a manual run, so you can look at the swept-out zone without the sweep's
own waypoint motion or the robot's pose from the last probed direction in
the way.

Builds the robot in its normal resting inverse-mode pose (assembles, target
never moves) and adds the most recently saved reach_zone result as a static
translucent shape. If reach_zone hasn't been run yet, the robot loads with
no shape.
"""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(next(c for c in Path(__file__).parents if (c / "labtests").is_dir())))
from launcher.bootstrap import bootstrap_lab

SCRIPT_DIR, SRC_ROOT, APP_ROOT, LAB_ROOT = bootstrap_lab(__file__)

from labtests.reach_zone import geometry  # noqa: E402


def createScene(rootnode):
    """Build a static inverse-mode scene showing the last saved reach_zone shape."""
    from labtests.core.base_scene import build_base_scene
    from labtests.core.modules.effector_target import setup as setup_effector
    from parts.controllers.assemblycontroller import AssemblyController  # type: ignore

    nodes = build_base_scene(rootnode, inverse=True)
    if nodes is None:
        return

    # Assembles the robot into its resting pose; the target is never moved
    # afterward, so no further controller is needed.
    nodes.emio.addObject(AssemblyController(nodes.emio))
    setup_effector(nodes, nodes.emio, initial_target_pos=[0, geometry.CENTER_Y, 0, 0, 0, 0, 1])

    result = geometry.load_result(LAB_ROOT)
    if result is None:
        print("[reach_zone view] no saved result yet -- run reach_zone from the Scenes tab first.")
        return rootnode

    vertices, triangles = geometry.build_zone_solid(result["levels"])
    geometry.add_mesh_visual(rootnode, vertices, triangles)
    print(
        f"[reach_zone view] showing zone volume={result['volume_mm3']:.1f}mm^3 "
        f"from {len(result['levels'])} levels"
    )

    return rootnode
