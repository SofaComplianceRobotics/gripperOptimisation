"""
matrixlinearsystem_order_probe -- direct evidence of MatrixLinearSystem's
`groups` map iteration order, captured from its own real (not stripped)
msg_info() call in makeLocalMatrixGroups: "Create a matrix to be mapped,
shared among the following components: ..., for a contribution on
mechanical state <path>". That line only fires inside the
`isMapped1 || isMapped2` branch, i.e. exactly the address-ordered iteration
over `groups` under scrutiny, and prints the mechanical-state path for each
group in the order `groups` was walked.

Runs scene.py with PROBE_SKIP_PLAYBACK=1 (frozen full robot, cube reachable
normally -- the confirmed-divergent baseline), with printLog enabled on
whichever component in the scene is MatrixLinearSystem (auto-created by
GenericConstraintCorrection + SparseLDLSolver, not explicitly added), and
diffs the ORDER of mechanical-state paths logged between two independent
launches.

Usage: python matrixlinearsystem_order_probe.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

LAB_ROOT = Path(r"c:\Users\Cesar\emio-labs\v25.12.00\assets\labs\lab_shapeOPT")
SCENE_FILE = LAB_ROOT / "labtests" / "grasp_hold_probe" / "scene.py"
SCRATCH = Path(__file__).parent
EMIOLABS_SOFA_ROOT = r"C:\Users\Cesar\AppData\Local\Programs\emio-labs\resources\sofa"
EMIOLABS_PYTHON = r"C:\Users\Cesar\AppData\Local\Programs\emio-labs\resources\sofa\bin\python\python.exe"

N_STEPS = 2

LINE_RE = re.compile(r"Create a matrix to be mapped, shared among the following components: (.*?), for a contribution on mechanical state (\S+)")


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
    os.environ["PROBE_SKIP_PLAYBACK"] = "1"


def _run(n_steps: int):
    _bootstrap()
    import Sofa.Core
    import Sofa.Simulation
    import importlib.util

    spec = importlib.util.spec_from_file_location("_mls_scene", str(SCENE_FILE))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_mls_scene"] = mod
    spec.loader.exec_module(mod)

    root = Sofa.Core.Node("root")
    mod.createScene(root)
    Sofa.Simulation.initRoot(root)

    found = []

    def walk(node):
        for obj in node.objects:
            cls = obj.getClassName()
            if "MatrixLinearSystem" in cls or "LinearSystem" in cls:
                obj.printLog = True
                found.append((cls, obj.getPathName()))
        for child in node.children:
            walk(child)

    walk(root)
    print(f"[probe] found {len(found)} linear-system component(s): {found}", file=sys.stderr)

    root.animate = True

    for _ in range(n_steps):
        Sofa.Simulation.animate(root, root.dt.value)

    Sofa.Simulation.unload(root)


def run_and_capture(tag: str) -> str:
    out_path = SCRATCH / f"mls_order_{tag}.log"
    proc = subprocess.run(
        [EMIOLABS_PYTHON, __file__, "--dump", str(N_STEPS)],
        capture_output=True,
        text=True,
    )
    out_path.write_text(proc.stdout + "\n---STDERR---\n" + proc.stderr, encoding="utf-8", errors="replace")
    return proc.stdout, proc.stderr


def main():
    print("[matrixlinearsystem_order_probe] running A...", file=sys.stderr)
    out_a, err_a = run_and_capture("A")
    print("[matrixlinearsystem_order_probe] running B...", file=sys.stderr)
    out_b, err_b = run_and_capture("B")

    print("component search (A):", [l for l in err_a.splitlines() if "[probe] found" in l])
    print("component search (B):", [l for l in err_b.splitlines() if "[probe] found" in l])

    order_a = LINE_RE.findall(out_a)
    order_b = LINE_RE.findall(out_b)
    print(f"\n{len(order_a)} groups log lines in A, {len(order_b)} in B")

    for i, (comp_a, path_a) in enumerate(order_a):
        marker = ""
        if i < len(order_b):
            if order_b[i] != (comp_a, path_a):
                marker = "  <<< DIFFERS"
        else:
            marker = "  <<< MISSING IN B"
        print(f"  [{i}] A: state={path_a} components=[{comp_a}]{marker}")
        if marker:
            print(f"        B: {order_b[i] if i < len(order_b) else 'N/A'}")

    print("\nIDENTICAL" if order_a == order_b else "DIFFERS")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--dump":
        _run(int(sys.argv[2]))
    else:
        main()
