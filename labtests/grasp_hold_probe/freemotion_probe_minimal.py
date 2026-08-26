"""
freemotion_probe_minimal -- direct empirical test of whether the minimal
cube+floor repro's free-motion solve (computed each step BEFORE collision
detection/response run) is already non-deterministic during free fall,
before the cube ever touches the floor.

This distinguishes two competing explanations for minimal_repro.py's
divergence:

  - if free_position/free_velocity already diverge on steps where the cube
    is still falling (no contact yet), the cause is upstream of collision,
    in the free-motion matrix assembly path (MatrixLinearSystem, e.g. the
    address-ordered m_mass/m_stiffness maps flagged as a candidate) -- the
    same family of bug as the larger scene, just reached through a
    different address-sorted map.
  - if free_position/free_velocity stay bit-identical through the free-fall
    steps and only start differing once contact begins, the cause is in
    collision detection/response instead, not MatrixLinearSystem.

Also records the cube's post-step y-position each step so the step at
which contact begins is visible directly in the output, rather than
assumed from a hand computed fall time.

Usage: python freemotion_probe_minimal.py                      # runs both + diffs, once
       python freemotion_probe_minimal.py --repeat N            # N independent A/B pairs, reports divergence rate and first-diverging step per pair
       python freemotion_probe_minimal.py --dump out.json <n>   # single run (internal)
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

LAB_ROOT = Path(r"c:\Users\Cesar\emio-labs\v25.12.00\assets\labs\lab_shapeOPT")
SCENE_FILE = LAB_ROOT / "labtests" / "grasp_hold_probe" / "minimal_repro.py"
EMIOLABS_SOFA_ROOT = r"C:\Users\Cesar\AppData\Local\Programs\emio-labs\resources\sofa"
EMIOLABS_PYTHON = r"C:\Users\Cesar\AppData\Local\Programs\emio-labs\resources\sofa\bin\python\python.exe"

N_STEPS = 15
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

    spec = importlib.util.spec_from_file_location("_fm_minimal_scene", str(SCENE_FILE))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_fm_minimal_scene"] = mod
    spec.loader.exec_module(mod)

    root = Sofa.Core.Node("root")
    mod.createScene(root)
    Sofa.Simulation.initRoot(root)
    root.animate = True

    bodies = {
        "cube": root.Simulation.Cube.MechanicalObject,
        "floor": root.Simulation.floor.mstate,
    }

    available = [d for d in ("free_position", "free_velocity", "position") if bodies["cube"].findData(d) is not None]

    trace = []
    for step in range(n_steps):
        Sofa.Simulation.animate(root, root.dt.value)
        entry = {"step": step}
        for body_name, mo in bodies.items():
            for name in available:
                data = mo.findData(name)
                if data is None:
                    continue
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
            return i, f"max diff {max(diffs):.3e}"
    return None, None


def cube_y_trace(trace):
    return [round(e["cube.position"][1], 4) for e in trace]


def run_pair(scratch: Path, tag: str):
    out_a, out_b = scratch / f"fmm_a_{tag}.json", scratch / f"fmm_b_{tag}.json"
    subprocess.run([EMIOLABS_PYTHON, __file__, "--dump", str(out_a), str(N_STEPS)], check=True, capture_output=True)
    subprocess.run([EMIOLABS_PYTHON, __file__, "--dump", str(out_b), str(N_STEPS)], check=True, capture_output=True)
    trace_a = json.loads(out_a.read_text())
    trace_b = json.loads(out_b.read_text())
    out_a.unlink(missing_ok=True)
    out_b.unlink(missing_ok=True)
    return trace_a, trace_b


def main_compare():
    scratch = Path(__file__).parent
    print("[freemotion_probe_minimal] running A...", file=sys.stderr)
    trace_a, trace_b = run_pair(scratch, "single")

    keys = [k for k in trace_a[0].keys() if k != "step"]
    print(f"\n[freemotion_probe_minimal] comparing fields: {keys}")
    for key in keys:
        idx, detail = first_diff(trace_a, trace_b, key)
        if idx is None:
            print(f"  {key}: IDENTICAL for all {N_STEPS} steps")
        else:
            print(f"  {key}: first diverges at step {idx} -> {detail}")

    print(f"\ncube y-position trace (A): {cube_y_trace(trace_a)}")
    print(f"cube y-position trace (B): {cube_y_trace(trace_b)}")


def main_repeat(n: int):
    scratch = Path(__file__).parent
    free_pos_first_divergence_steps = []
    contact_started_by_step = None

    for r in range(n):
        trace_a, trace_b = run_pair(scratch, str(r))
        idx_fp, detail_fp = first_diff(trace_a, trace_b, "cube.free_position")
        idx_pos, detail_pos = first_diff(trace_a, trace_b, "cube.position")
        y_a = cube_y_trace(trace_a)
        print(f"pair {r}: cube.position first diverges at step {idx_pos if idx_pos is not None else 'never'}"
              f"{f' ({detail_pos})' if detail_pos else ''}, "
              f"cube.free_position first diverges at step {idx_fp if idx_fp is not None else 'never'}"
              f"{f' ({detail_fp})' if detail_fp else ''} | cube y-trace {y_a}")
        if idx_fp is not None:
            free_pos_first_divergence_steps.append(idx_fp)

    print(f"\n{len(free_pos_first_divergence_steps)}/{n} pairs diverged in cube.free_position")
    if free_pos_first_divergence_steps:
        print(f"first-divergence step across diverged pairs: min={min(free_pos_first_divergence_steps)}, "
              f"max={max(free_pos_first_divergence_steps)}")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--dump":
        main_dump(sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else N_STEPS)
    elif len(sys.argv) >= 2 and sys.argv[1] == "--repeat":
        main_repeat(int(sys.argv[2]) if len(sys.argv) > 2 else REPEATS)
    else:
        main_compare()
