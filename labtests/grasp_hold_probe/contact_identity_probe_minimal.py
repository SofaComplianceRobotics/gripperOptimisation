"""
contact_identity_probe_minimal -- walks the scene graph after each step
(plain Python object/child traversal, not log-dependent, so it works
regardless of dmsg_info() being compiled out) looking for every object whose
class name contains "contact", for minimal_repro.py. Reports how many
distinct contact-response objects exist and in what order they appear in
the scene graph, from two independent launches.

If there is more than one response object (e.g. one per colliding
collision-model-type pair: Triangle-Triangle, Triangle-Line, Point-Point,
etc.), the relative order those objects get created/inserted determines
which one's constraint rows land first in the global system -- a second,
coarser-grained candidate for the row-permutation already proven by
lcp_diff_minimal.py, distinct from ordering within a single response
object's own contact list.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

LAB_ROOT = Path(r"c:\Users\Cesar\emio-labs\v25.12.00\assets\labs\lab_shapeOPT")
SCENE_FILE = LAB_ROOT / "labtests" / "grasp_hold_probe" / "minimal_repro.py"
SCRATCH = Path(__file__).parent
EMIOLABS_SOFA_ROOT = r"C:\Users\Cesar\AppData\Local\Programs\emio-labs\resources\sofa"
EMIOLABS_PYTHON = r"C:\Users\Cesar\AppData\Local\Programs\emio-labs\resources\sofa\bin\python\python.exe"

N_STEPS = 6


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


def _walk_contacts(root, step):
    print(f"=== CONTACT IDENTITIES step {step} ===")

    def walk(node):
        for obj in node.objects:
            cls = obj.getClassName()
            if "contact" in cls.lower():
                # print constraint size too if the object exposes it, to see how many rows each response owns
                print(f"  [{cls}] name={obj.getName()!r} path={obj.getPathName()!r}")
        for child in node.children:
            walk(child)

    walk(root)
    print(f"=== END step {step} ===")


def _run(n_steps: int):
    _bootstrap()
    import Sofa.Core
    import Sofa.Simulation
    import importlib.util

    spec = importlib.util.spec_from_file_location("_ci_minimal_scene", str(SCENE_FILE))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_ci_minimal_scene"] = mod
    spec.loader.exec_module(mod)

    root = Sofa.Core.Node("root")
    mod.createScene(root)
    Sofa.Simulation.initRoot(root)
    root.animate = True

    for step in range(n_steps):
        Sofa.Simulation.animate(root, root.dt.value)
        _walk_contacts(root, step)

    Sofa.Simulation.unload(root)


def run_and_capture(tag: str) -> str:
    out_path = SCRATCH / f"ci_min_{tag}.log"
    proc = subprocess.run(
        [EMIOLABS_PYTHON, __file__, "--dump", str(N_STEPS)],
        capture_output=True,
        text=True,
    )
    out_path.write_text(proc.stdout + "\n---STDERR---\n" + proc.stderr, encoding="utf-8", errors="replace")
    return proc.stdout


def main_diff():
    print("[contact_identity_probe_minimal] running A...", file=sys.stderr)
    out_a = run_and_capture("A")
    print("[contact_identity_probe_minimal] running B...", file=sys.stderr)
    out_b = run_and_capture("B")

    lines_a = [l for l in out_a.splitlines() if "[" in l and "name=" in l or "step" in l]
    lines_b = [l for l in out_b.splitlines() if "[" in l and "name=" in l or "step" in l]

    print("--- A ---")
    for l in lines_a:
        print(l)
    print("\n--- B ---")
    for l in lines_b:
        print(l)

    print("\n--- diff ---")
    print("IDENTICAL" if lines_a == lines_b else "DIFFERS")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--dump":
        _run(int(sys.argv[2]))
    else:
        main_diff()
