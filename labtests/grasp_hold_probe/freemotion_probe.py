"""
freemotion_probe — direct empirical test of whether the free-motion solve
(EulerImplicitSolver + SparseLDLSolver + AMD ordering, computed BEFORE
collision detection/response run each step) produces identical output between
two independent runs, at every step — not inferred from source reading.

Captures the cube's `free_position` (the literal output of that solve, prior
to any constraint correction) each step, from two separate process launches,
and diffs them directly.

Usage: python freemotion_probe.py            # runs both + diffs
       python freemotion_probe.py --dump out.json <n_steps>   # single run (internal)
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


def main_dump(out_path: str, n_steps: int):
    _bootstrap()
    import Sofa.Core
    import Sofa.Simulation
    import importlib.util

    spec = importlib.util.spec_from_file_location("_fm_scene", str(SCENE_FILE))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_fm_scene"] = mod
    spec.loader.exec_module(mod)

    root = Sofa.Core.Node("root")
    mod.createScene(root)
    Sofa.Simulation.initRoot(root)
    root.animate = True

    bodies = {
        "cube": root.Simulation.Cube.MechanicalObject,
        "leg0_beam": root.Simulation.Emio.Leg0.Leg0RigidBase.RigidifiedPoints.Leg.MechanicalObject,
        "gripper_center": root.Simulation.Emio.CenterPart.MechanicalObject,
    }

    # probe what free-motion-related Data fields are actually readable
    available = [d for d in ("free_position", "free_velocity", "position", "velocity") if bodies["cube"].findData(d) is not None]
    print(f"[freemotion_probe] tracking bodies: {list(bodies.keys())}, fields: {available}", file=sys.stderr)

    trace = []
    for step in range(n_steps):
        Sofa.Simulation.animate(root, root.dt.value)
        entry = {"step": step}
        for body_name, mo in bodies.items():
            for name in available:
                data = mo.findData(name)
                if data is None:
                    continue
                # beam DOFs have many points; flatten all of them for a full comparison
                entry[f"{body_name}.{name}"] = [float(v) for row in data.value for v in row]
        trace.append(entry)

    Sofa.Simulation.unload(root)
    Path(out_path).write_text(json.dumps(trace))


def first_diff(a, b, key):
    n = min(len(a), len(b))
    for i in range(n):
        va, vb = a[i].get(key), b[i].get(key)
        if va is None or vb is None:
            continue
        if len(va) != len(vb):
            return i, f"LENGTH MISMATCH {len(va)} vs {len(vb)}"
        diffs = [abs(x - y) for x, y in zip(va, vb)]
        if any(d > 0 for d in diffs):
            return i, f"{va} vs {vb} (max diff {max(diffs):.3e})"
    return None, None


def main_compare():
    scratch = Path(__file__).parent
    out_a, out_b = scratch / "fm_a.json", scratch / "fm_b.json"
    print("[freemotion_probe] running A...", file=sys.stderr)
    subprocess.run([EMIOLABS_PYTHON, __file__, "--dump", str(out_a), str(N_STEPS)], check=True)
    print("[freemotion_probe] running B...", file=sys.stderr)
    subprocess.run([EMIOLABS_PYTHON, __file__, "--dump", str(out_b), str(N_STEPS)], check=True)

    trace_a = json.loads(out_a.read_text())
    trace_b = json.loads(out_b.read_text())

    keys = [k for k in trace_a[0].keys() if k != "step"]
    print(f"\n[freemotion_probe] comparing fields: {keys}")
    for key in keys:
        idx, detail = first_diff(trace_a, trace_b, key)
        if idx is None:
            print(f"  {key}: IDENTICAL for all {N_STEPS} steps")
        else:
            print(f"  {key}: first diverges at step {idx} -> {detail}")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--dump":
        main_dump(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else N_STEPS)
    else:
        main_compare()
