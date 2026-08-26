"""
broadphase_order_probe -- captures the exact order collision models get
registered into BruteForceBroadPhase (via its own printLog output,
BruteForceBroadPhase.cpp: "CollisionModel <name>(<ptr>) ... is added in
broad phase (<n> collision models)"), for minimal_repro.py, from two
independent launches, and diffs the ORDER of model names (ignoring the raw
pointer value, which is expected to vary by ASLR regardless).

This isolates whether the divergence traced by lcp_diff_minimal.py (a
same-value permutation of the constraint system, first appearing exactly at
the first-contact step) originates as early as collision-model registration
order feeding the broad/narrow phase, rather than inside DirectSAPNarrowPhase
itself (whose own sort tie-break and active-list are both plain-int keyed,
not pointer-keyed, per direct source reading of DirectSAPNarrowPhase.cpp).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

LAB_ROOT = Path(r"c:\Users\Cesar\emio-labs\v25.12.00\assets\labs\lab_shapeOPT")
SCENE_FILE = LAB_ROOT / "labtests" / "grasp_hold_probe" / "minimal_repro.py"
SCRATCH = Path(__file__).parent
EMIOLABS_SOFA_ROOT = r"C:\Users\Cesar\AppData\Local\Programs\emio-labs\resources\sofa"
EMIOLABS_PYTHON = r"C:\Users\Cesar\AppData\Local\Programs\emio-labs\resources\sofa\bin\python\python.exe"

N_STEPS = 6

LINE_RE = re.compile(r"CollisionModel (\S+)\(0x[0-9a-fA-F]+\) of class (\S+) is added in broad phase \((\d+) collision models\)")


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


def _run(n_steps: int):
    _bootstrap()
    import Sofa.Core
    import Sofa.Simulation
    import importlib.util

    spec = importlib.util.spec_from_file_location("_bp_minimal_scene", str(SCENE_FILE))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_bp_minimal_scene"] = mod
    spec.loader.exec_module(mod)

    root = Sofa.Core.Node("root")
    mod.createScene(root)
    for obj in root.getObjects():
        if obj.getClassName() == "BruteForceBroadPhase":
            obj.printLog = True
    Sofa.Simulation.initRoot(root)
    root.animate = True

    for _ in range(n_steps):
        Sofa.Simulation.animate(root, root.dt.value)

    Sofa.Simulation.unload(root)


def run_and_capture(tag: str) -> str:
    out_path = SCRATCH / f"bp_min_{tag}.log"
    proc = subprocess.run(
        [EMIOLABS_PYTHON, __file__, "--dump", str(N_STEPS)],
        capture_output=True,
        text=True,
    )
    out_path.write_text(proc.stdout + "\n---STDERR---\n" + proc.stderr, encoding="utf-8", errors="replace")
    return proc.stdout


def extract_order(text: str) -> list[tuple[str, str]]:
    return [(m.group(1), m.group(2)) for m in LINE_RE.finditer(text)]


def main_diff():
    print("[broadphase_order_probe] running A...", file=sys.stderr)
    out_a = run_and_capture("A")
    print("[broadphase_order_probe] running B...", file=sys.stderr)
    out_b = run_and_capture("B")

    order_a = extract_order(out_a)
    order_b = extract_order(out_b)
    print(f"[broadphase_order_probe] {len(order_a)} registrations in A, {len(order_b)} in B")

    # registrations repeat every step (broad phase rebuilt each step); compare step-by-step blocks
    n_models = None
    for i, (name, cls) in enumerate(order_a):
        marker = ""
        if i < len(order_b):
            if order_b[i] != (name, cls):
                marker = "  <<< DIFFERS"
        else:
            marker = "  <<< MISSING IN B"
        print(f"  [{i}] A: {name} ({cls}){marker}")
        if marker:
            print(f"        B: {order_b[i] if i < len(order_b) else 'N/A'}")

    if order_a == order_b:
        print("\n[broadphase_order_probe] registration order IDENTICAL between A and B for all captured steps")
    else:
        print("\n[broadphase_order_probe] registration order DIFFERS between A and B")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--dump":
        _run(int(sys.argv[2]))
    else:
        main_diff()
