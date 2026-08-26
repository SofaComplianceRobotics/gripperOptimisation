"""
matrixlinearsystem_groups_repro_probe: divergence-rate harness for
matrixlinearsystem_groups_repro.py. Launches the scene independently
multiple times, tracking the shared Attach body's free_position each step,
and reports how many independent launch pairs diverge and at which step.

Usage: python matrixlinearsystem_groups_repro_probe.py            # runs both + diffs, once
       python matrixlinearsystem_groups_repro_probe.py --repeat N # N independent A/B pairs, divergence rate
       python matrixlinearsystem_groups_repro_probe.py --dump out.json <n>  # single run (internal)
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCENE_FILE = Path(__file__).parent / "matrixlinearsystem_groups_repro.py"
EMIOLABS_SOFA_ROOT = r"C:\Users\Cesar\AppData\Local\Programs\emio-labs\resources\sofa"
EMIOLABS_PYTHON = r"C:\Users\Cesar\AppData\Local\Programs\emio-labs\resources\sofa\bin\python\python.exe"

N_STEPS = 5
REPEATS = 10


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


def main_dump(out_path: str, n_steps: int):
    _bootstrap()
    import Sofa.Core
    import Sofa.Simulation
    import importlib.util

    spec = importlib.util.spec_from_file_location("_mlsg_scene", str(SCENE_FILE))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_mlsg_scene"] = mod
    spec.loader.exec_module(mod)

    root = Sofa.Core.Node("root")
    mod.createScene(root)
    Sofa.Simulation.initRoot(root)
    root.animate = True

    attach_mo = root.Simulation.Attach.mo
    trace = []
    for _ in range(n_steps):
        Sofa.Simulation.animate(root, root.dt.value)
        trace.append([float(v) for v in attach_mo.free_position.value[0]])

    Sofa.Simulation.unload(root)
    Path(out_path).write_text(json.dumps(trace))


def run_pair(scratch: Path, tag: str):
    out_a, out_b = scratch / f"mlsgr_a_{tag}.json", scratch / f"mlsgr_b_{tag}.json"
    subprocess.run([EMIOLABS_PYTHON, __file__, "--dump", str(out_a), str(N_STEPS)], check=True, capture_output=True)
    subprocess.run([EMIOLABS_PYTHON, __file__, "--dump", str(out_b), str(N_STEPS)], check=True, capture_output=True)
    trace_a = json.loads(out_a.read_text())
    trace_b = json.loads(out_b.read_text())
    out_a.unlink(missing_ok=True)
    out_b.unlink(missing_ok=True)
    return trace_a, trace_b


def main_compare():
    scratch = Path(__file__).parent
    trace_a, trace_b = run_pair(scratch, "single")
    same0 = trace_a[0] == trace_b[0]
    if same0:
        print("Attach.free_position: IDENTICAL at step 0")
    else:
        diffs = [abs(x - y) for x, y in zip(trace_a[0], trace_b[0])]
        print(f"Attach.free_position: DIFFERS at step 0 (max diff {max(diffs):.6g})")
        print(f"  A: {trace_a[0]}")
        print(f"  B: {trace_b[0]}")


def main_repeat(n: int):
    scratch = Path(__file__).parent
    diverged = 0
    for r in range(n):
        trace_a, trace_b = run_pair(scratch, str(r))
        same0 = trace_a[0] == trace_b[0]
        status = "IDENTICAL"
        if not same0:
            diffs = [abs(x - y) for x, y in zip(trace_a[0], trace_b[0])]
            status = f"DIVERGED at step 0 (max diff {max(diffs):.6g})"
            diverged += 1
        print(f"pair {r}: {status}")
    print(f"\n{diverged}/{n} pairs diverged at step 0")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--dump":
        main_dump(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else N_STEPS)
    elif len(sys.argv) >= 2 and sys.argv[1] == "--repeat":
        main_repeat(int(sys.argv[2]) if len(sys.argv) > 2 else REPEATS)
    else:
        main_compare()
