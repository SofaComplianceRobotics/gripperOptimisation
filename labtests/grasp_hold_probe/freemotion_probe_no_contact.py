"""
freemotion_probe_no_contact -- isolates the MatrixLinearSystem.groups bug
from any possible contact/collision event, to prove it is a separate
mechanism from the contact-response-ordering instability found via the
minimal cube+floor repro.

Runs scene.py with PROBE_SKIP_PLAYBACK=1 (full robot with gripper, frozen,
never driven -- confirmed below to diverge in leg0_beam.free_position from
step 0, matching the original full-scene evidence), with and without
PROBE_CUBE_UNREACHABLE=1 layered on top. That flag builds the exact same
legs+gripper+cube+floor+collision-pipeline structure (same total DOF count,
same MatrixLinearSystem.groups population) but spawns the cube far enough
away that it can never fall into contact range within the probe's step
window. If leg0_beam.free_position still diverges from step 0 with contact
made physically impossible, the divergence is provably coming from
free-motion matrix assembly alone, with zero involvement of collision
detection, narrow phase, or contact response -- a clean separation from the
second mechanism (which, in the minimal cube+floor repro, was shown to do
the opposite: free_position is bit-identical through the entire free-fall
phase and only starts diverging at the first contact step).

Note: PROBE_LEGS_ONLY (frozen, no gripper) does NOT reproduce the step-0
divergence at all, with or without PROBE_CUBE_UNREACHABLE -- confirmed by
direct measurement (10/10 identical pairs). The gripper's presence appears
necessary for MatrixLinearSystem.groups to have enough shared/mapped
components to actually reorder. PROBE_SKIP_PLAYBACK (keeps the gripper) is
the correct baseline to use here.

Usage: python freemotion_probe_no_contact.py --baseline   # cube reachable, confirms the known-divergent baseline
       python freemotion_probe_no_contact.py --unreachable # cube unreachable, tests separation from contact
       python freemotion_probe_no_contact.py --dump out.json <n>  # single run (internal)
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

LAB_ROOT = Path(r"c:\Users\Cesar\emio-labs\v25.12.00\assets\labs\lab_shapeOPT")
SCENE_FILE = LAB_ROOT / "labtests" / "grasp_hold_probe" / "scene.py"
EMIOLABS_SOFA_ROOT = r"C:\Users\Cesar\AppData\Local\Programs\emio-labs\resources\sofa"
EMIOLABS_PYTHON = r"C:\Users\Cesar\AppData\Local\Programs\emio-labs\resources\sofa\bin\python\python.exe"

N_STEPS = 10
REPEATS = 10


def _bootstrap(unreachable: bool):
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
    if unreachable:
        os.environ["PROBE_CUBE_UNREACHABLE"] = "1"


def main_dump(out_path: str, n_steps: int, unreachable: bool):
    _bootstrap(unreachable)
    import Sofa.Core
    import Sofa.Simulation
    import importlib.util

    spec = importlib.util.spec_from_file_location("_fm_nc_scene", str(SCENE_FILE))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_fm_nc_scene"] = mod
    spec.loader.exec_module(mod)

    root = Sofa.Core.Node("root")
    mod.createScene(root)
    Sofa.Simulation.initRoot(root)
    root.animate = True

    leg_mo = root.Simulation.Emio.Leg0.Leg0RigidBase.RigidifiedPoints.Leg.MechanicalObject

    trace = []
    for _ in range(n_steps):
        Sofa.Simulation.animate(root, root.dt.value)
        trace.append([float(v) for row in leg_mo.free_position.value for v in row])

    Sofa.Simulation.unload(root)
    Path(out_path).write_text(json.dumps(trace))


def run_pair(scratch: Path, tag: str, unreachable: bool):
    out_a, out_b = scratch / f"fmnc_a_{tag}.json", scratch / f"fmnc_b_{tag}.json"
    flag = "--unreachable-dump" if unreachable else "--baseline-dump"
    subprocess.run([EMIOLABS_PYTHON, __file__, flag, str(out_a), str(N_STEPS)], check=True, capture_output=True)
    subprocess.run([EMIOLABS_PYTHON, __file__, flag, str(out_b), str(N_STEPS)], check=True, capture_output=True)
    trace_a = json.loads(out_a.read_text())
    trace_b = json.loads(out_b.read_text())
    out_a.unlink(missing_ok=True)
    out_b.unlink(missing_ok=True)
    return trace_a, trace_b


def main_repeat(n: int, unreachable: bool):
    scratch = Path(__file__).parent
    diverged_step0 = 0
    for r in range(n):
        trace_a, trace_b = run_pair(scratch, str(r), unreachable)
        same0 = trace_a[0] == trace_b[0]
        same_all = trace_a == trace_b
        status = "step0 SAME" if same0 else "step0 DIFF"
        status += ", all-steps IDENTICAL" if same_all else ", DIVERGED"
        print(f"pair {r}: {status}")
        if not same0:
            diverged_step0 += 1

    label = "cube unreachable" if unreachable else "cube reachable (baseline)"
    print(f"\n[{label}] {diverged_step0}/{n} pairs diverged at step 0")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] in ("--baseline-dump", "--unreachable-dump"):
        main_dump(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else N_STEPS, sys.argv[1] == "--unreachable-dump")
    elif len(sys.argv) >= 2 and sys.argv[1] == "--baseline":
        main_repeat(REPEATS, unreachable=False)
    elif len(sys.argv) >= 2 and sys.argv[1] == "--unreachable":
        main_repeat(REPEATS, unreachable=True)
    else:
        print(__doc__)
