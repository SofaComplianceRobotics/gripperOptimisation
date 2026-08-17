"""
lcp_dump_runner — build the grasp_hold_probe scene, step it N times, let SOFA's
own printLog output (enabled via PROBE_DUMP_LCP=1, read by scene.py) go to
stdout naturally. Invoked as a subprocess by lcp_diff.py, which captures and
parses this process's stdout.

Usage: python lcp_dump_runner.py <n_steps>
"""

from __future__ import annotations

import sys
from pathlib import Path

LAB_ROOT = Path(r"c:\Users\Cesar\emio-labs\v25.12.00\assets\labs\lab_shapeOPT")
SCENE_FILE = LAB_ROOT / "labtests" / "grasp_hold_probe" / "scene.py"
EMIOLABS_SOFA_ROOT = r"C:\Users\Cesar\AppData\Local\Programs\emio-labs\resources\sofa"


def _bootstrap():
    import os

    sys.path[:] = [p for p in sys.path if "SOFA_v25.12.00_Win64" not in p]
    sys.path.insert(0, str(Path("C:/Users/Cesar/Documents/SofaOptimisation/src")))
    from sofaopt.core.sofa_bootstrap import register_sofa_dll_dirs, reconfigure_streams_utf8

    reconfigure_streams_utf8()
    os.environ["SOFA_ROOT"] = EMIOLABS_SOFA_ROOT
    os.environ.pop("SOFAPYTHON3_ROOT", None)
    register_sofa_dll_dirs(EMIOLABS_SOFA_ROOT)
    site_packages = str(Path(EMIOLABS_SOFA_ROOT) / "plugins" / "SofaPython3" / "lib" / "python3" / "site-packages")
    sys.path.insert(0, site_packages)

    assets_root = LAB_ROOT.parent.parent
    if str(assets_root) not in sys.path:
        sys.path.insert(0, str(assets_root))


def _dump_contact_identities(root, step: int) -> None:
    """Walk the whole scene graph and print every object whose class name
    contains 'contact' (case-insensitive), in traversal order — SOFA usually
    names contact-response objects after the colliding collision models, so
    this should let us label which physical bodies each constraint index
    belongs to, in the order they'd be swept into the constraint list.
    """
    print(f"=== CONTACT IDENTITIES step {step} ===")

    def walk(node, depth=0):
        for obj in node.objects:
            cls = obj.getClassName()
            if "contact" in cls.lower():
                print(f"  [{cls}] name={obj.getName()!r} path={obj.getPathName()!r}")
        for child in node.children:
            walk(child, depth + 1)

    walk(root)
    print(f"=== END CONTACT IDENTITIES step {step} ===")


def main(n_steps: int):
    _bootstrap()
    import Sofa.Core
    import Sofa.Simulation
    import SofaRuntime

    import importlib.util

    spec = importlib.util.spec_from_file_location("_lcp_scene", str(SCENE_FILE))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_lcp_scene"] = mod
    spec.loader.exec_module(mod)

    root = Sofa.Core.Node("root")
    mod.createScene(root)
    Sofa.Simulation.initRoot(root)
    root.animate = True

    for step in range(n_steps):
        Sofa.Simulation.animate(root, root.dt.value)
        _dump_contact_identities(root, step)

    Sofa.Simulation.unload(root)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 6)
