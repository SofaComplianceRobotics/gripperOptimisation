"""
lcp_diff_minimal -- same technique as lcp_diff.py (parse SOFA's own
printLCP() "Before/After Resolution" dump: W matrix, dfree/delta,
force/lambda), but pointed at minimal_repro.py instead of the full robot
scene, and self-contained (turns printLog on directly from Python instead of
relying on scene.py's PROBE_DUMP_LCP env-var plumbing, which minimal_repro.py
deliberately does not have).

Finds exactly which of (contact geometry feeding the solver) vs (the solve
itself) is where the minimal scene's step-3 divergence is actually born,
instead of inferring it from the downstream position/velocity effect already
measured by freemotion_probe_minimal.py.
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

N_STEPS = 6  # covers the known first-divergence step (3) with a little margin


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

    spec = importlib.util.spec_from_file_location("_lcp_minimal_scene", str(SCENE_FILE))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_lcp_minimal_scene"] = mod
    spec.loader.exec_module(mod)

    root = Sofa.Core.Node("root")
    mod.createScene(root)
    root.ConstraintSolver.printLog = True
    Sofa.Simulation.initRoot(root)
    root.animate = True

    for _ in range(n_steps):
        Sofa.Simulation.animate(root, root.dt.value)

    Sofa.Simulation.unload(root)


def run_and_capture(tag: str) -> str:
    out_path = SCRATCH / f"lcp_min_{tag}.log"
    proc = subprocess.run(
        [EMIOLABS_PYTHON, __file__, "--dump", str(N_STEPS)],
        capture_output=True,
        text=True,
    )
    out_path.write_text(proc.stdout + "\n---STDERR---\n" + proc.stderr, encoding="utf-8", errors="replace")
    return proc.stdout


LCP_BLOCK_RE = re.compile(
    r"---> (Before|After) Resolution.*?"
    r"(?:W = \[(?P<W>.*?)\];)?\s*"
    r"delta = \[(?P<delta>.*?)\];\s*"
    r"lambda = \[(?P<lambda>.*?)\];",
    re.DOTALL,
)


def parse_blocks(text: str) -> list[dict]:
    blocks = []
    for m in LCP_BLOCK_RE.finditer(text):
        delta = [float(x) for x in m.group("delta").split()]
        lam = [float(x) for x in m.group("lambda").split()]
        dim = len(delta)

        w_raw = m.group("W")
        w = None
        if w_raw and w_raw.strip():
            flat = [float(x) for x in w_raw.split()]
            if dim and len(flat) == dim * dim:
                w = [flat[r * dim:(r + 1) * dim] for r in range(dim)]
            else:
                w = [flat]
        blocks.append({"phase": m.group(1), "W": w, "delta": delta, "lambda": lam})
    return blocks


def first_diff_vec(a: list[float], b: list[float]):
    n = min(len(a), len(b))
    if len(a) != len(b):
        return (-1, f"LENGTH MISMATCH: {len(a)} vs {len(b)}")
    for i in range(n):
        if a[i] != b[i]:
            return (i, f"{a[i]!r} vs {b[i]!r} (diff {abs(a[i]-b[i]):.3e})")
    return None


def first_diff_mat(a, b):
    if a is None or b is None:
        return None
    if len(a) != len(b):
        return (-1, -1, f"DIM MISMATCH: {len(a)} vs {len(b)}")
    for r in range(len(a)):
        if len(a[r]) != len(b[r]):
            return (r, -1, f"ROW LENGTH MISMATCH: {len(a[r])} vs {len(b[r])}")
        for c in range(len(a[r])):
            if a[r][c] != b[r][c]:
                return (r, c, f"{a[r][c]!r} vs {b[r][c]!r} (diff {abs(a[r][c]-b[r][c]):.3e})")
    return None


def main_diff():
    print("[lcp_diff_minimal] running A...", file=sys.stderr)
    out_a = run_and_capture("A")
    print("[lcp_diff_minimal] running B...", file=sys.stderr)
    out_b = run_and_capture("B")

    blocks_a = parse_blocks(out_a)
    blocks_b = parse_blocks(out_b)
    print(f"[lcp_diff_minimal] parsed {len(blocks_a)} blocks from A, {len(blocks_b)} from B", file=sys.stderr)

    n = min(len(blocks_a), len(blocks_b))
    found = False
    for i in range(n):
        ba, bb = blocks_a[i], blocks_b[i]
        print(f"\n--- block {i} ({ba['phase']} resolution) ---")

        d_diff = first_diff_vec(ba["delta"], bb["delta"])
        print(f"  dfree/delta: {'IDENTICAL' if d_diff is None else d_diff}")

        l_diff = first_diff_vec(ba["lambda"], bb["lambda"])
        print(f"  force/lambda: {'IDENTICAL' if l_diff is None else l_diff}")

        w_diff = None
        if ba["W"] is not None:
            w_diff = first_diff_mat(ba["W"], bb["W"])
            print(f"  W matrix ({len(ba['W'])}x{len(ba['W'][0]) if ba['W'] else 0}): {'IDENTICAL' if w_diff is None else w_diff}")

        if d_diff is not None or l_diff is not None or w_diff is not None:
            print(f"  >>> FIRST DIVERGENCE at block {i} ({ba['phase']} resolution) <<<")
            found = True
            break

    if not found:
        print("\n[lcp_diff_minimal] all captured blocks identical -- divergence must be after these steps or not captured")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--dump":
        _run(int(sys.argv[2]))
    else:
        main_diff()
