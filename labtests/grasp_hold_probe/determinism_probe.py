"""
determinism_probe — isolates WHERE grasp_hold's run-to-run divergence comes from.

Runs labtests/grasp_hold_probe/scene.py (a throwaway debug copy of grasp_hold
with PROBE_* strip toggles — see that file's docstring) twice, records the
cube's Rigid3 pose + velocity + narrow-phase pair count every physics step,
and reports the first step where the two runs disagree.

Two comparison conditions:
  A) same-process double run: build+run, tear down, build+run again, in one
     Python process.
  B) cross-process double run: two separate `python determinism_probe.py
     --dump <path>` subprocess launches — exactly what sofaopt's runner.py
     does per trial today.

Any PROBE_* env var set in this process's environment is inherited by the
subprocess launches for (B) automatically (subprocess.run with no env= arg
inherits os.environ).

Usage:
    python determinism_probe.py                  # runs the full A+B comparison
    python determinism_probe.py --dump out.json  # single run, dumps trace (used internally for B)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

LAB_ROOT = Path(r"c:\Users\Cesar\emio-labs\v25.12.00\assets\labs\lab_shapeOPT")
SCENE_FILE = LAB_ROOT / "labtests" / "grasp_hold_probe" / "scene.py"

N_STEPS = 300  # 300 * DT_DIRECT(0.01) = 3.0s sim time

EMIOLABS_SOFA_ROOT = r"C:\Users\Cesar\AppData\Local\Programs\emio-labs\resources\sofa"


def _bootstrap():
    import os

    # The shell's own SOFA_ROOT/PYTHONPATH point at a generic downloaded
    # SOFA_v25.12.00_Win64 build (no splib3/Emio site-packages, different DLL
    # ABI than the emio-labs bundled build). Strip any trace of it from
    # sys.path so it can't shadow the correct build below.
    sys.path[:] = [p for p in sys.path if "SOFA_v25.12.00_Win64" not in p]

    sys.path.insert(0, str(Path("C:/Users/Cesar/Documents/SofaOptimisation/src")))
    from sofaopt.core.sofa_bootstrap import register_sofa_dll_dirs, reconfigure_streams_utf8

    reconfigure_streams_utf8()
    os.environ["SOFA_ROOT"] = EMIOLABS_SOFA_ROOT
    os.environ.pop("SOFAPYTHON3_ROOT", None)
    register_sofa_dll_dirs(EMIOLABS_SOFA_ROOT)
    site_packages = str(Path(EMIOLABS_SOFA_ROOT) / "plugins" / "SofaPython3" / "lib" / "python3" / "site-packages")
    sys.path.insert(0, site_packages)
    print(f"[probe] SOFA_ROOT = {EMIOLABS_SOFA_ROOT}", file=sys.stderr)

    # bootstrap_lab() only puts LAB_ROOT on sys.path; the real launcher (the
    # emio-labs app / dashboard) additionally provides assets/ (utils/, parts/)
    # on PYTHONPATH, which we're bypassing here — add it manually.
    assets_root = LAB_ROOT.parent.parent
    if str(assets_root) not in sys.path:
        sys.path.insert(0, str(assets_root))


def _load_scene_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("_probe_scene", str(SCENE_FILE))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_probe_scene"] = mod
    spec.loader.exec_module(mod)
    return mod


def run_once(mod, Sofa, SofaRuntime, run_tag: str) -> list:
    """Build the scene fresh, step it N_STEPS times, return per-step diagnostics."""
    for plugin in ("Sofa.Component.AnimationLoop",):
        try:
            SofaRuntime.importPlugin(plugin)
        except Exception:
            pass

    root = Sofa.Core.Node("root")
    mod.createScene(root)

    floor_tri = root.Simulation.floor.collision.getObject("TriangleCollisionModel")
    cube_tri = root.Simulation.Cube.collision.cubeCollisionTriangles
    root.Simulation.addObject(
        "ContactListener",
        name="probeFloorCubeListener",
        collisionModel1=floor_tri.getLinkPath(),
        collisionModel2=cube_tri.getLinkPath(),
    )

    Sofa.Simulation.initRoot(root)
    root.animate = True

    cube_mo = root.Simulation.Cube.MechanicalObject
    narrowphase = root.getObject("DirectSAPNarrowPhase") or root.getObject("BVHNarrowPhase")
    floor_listener = root.Simulation.getObject("probeFloorCubeListener")

    trace = []
    for step in range(N_STEPS):
        Sofa.Simulation.animate(root, root.dt.value)
        n_contacts = None
        try:
            n_contacts = len(floor_listener.getContactElements())
        except Exception:
            pass
        nb_pairs = None
        if narrowphase is not None:
            try:
                nb_pairs = int(narrowphase.nbPairs.value)
            except Exception:
                nb_pairs = None
        trace.append({
            "pos": [float(v) for v in cube_mo.position.value[0]],
            "vel": [float(v) for v in cube_mo.velocity.value[0]],
            "nb_pairs": nb_pairs,
            "floor_contacts": n_contacts,
        })

    Sofa.Simulation.unload(root)
    final_y = trace[-1]["pos"][1]
    print(f"[probe:{run_tag}] {N_STEPS} steps done, final cube Y = {final_y:.6f}", file=sys.stderr)
    return trace


def first_divergence(trace_a, trace_b, tol=1e-9):
    n = min(len(trace_a), len(trace_b))
    for i in range(n):
        pa, pb = trace_a[i]["pos"], trace_b[i]["pos"]
        diff = max(abs(x - y) for x, y in zip(pa, pb))
        if diff > tol:
            return i, diff
    return None, 0.0


def diagnose_window(trace_a, trace_b, center, radius=12):
    lo, hi = max(0, center - radius), min(len(trace_a), len(trace_b), center + radius)
    print(f"\n--- step-by-step around divergence (steps {lo}-{hi}) ---", file=sys.stderr)
    header = f"{'step':>4} | {'Y_a':>12} {'Y_b':>12} {'dY':>10} | {'pairs_a':>7} {'pairs_b':>7}"
    print(header, file=sys.stderr)
    for i in range(lo, hi):
        a, b = trace_a[i], trace_b[i]
        dy = a["pos"][1] - b["pos"][1]
        print(
            f"{i:>4} | {a['pos'][1]:>12.8f} {b['pos'][1]:>12.8f} {dy:>10.2e} | "
            f"{str(a['nb_pairs']):>7} {str(b['nb_pairs']):>7}",
            file=sys.stderr,
        )


def main_dump(out_path: str):
    _bootstrap()
    import Sofa.Core
    import Sofa.Simulation
    import SofaRuntime

    mod = _load_scene_module()
    trace = run_once(mod, Sofa, SofaRuntime, "dump")
    Path(out_path).write_text(json.dumps(trace))


def main_compare():
    _bootstrap()
    import os
    import Sofa.Core
    import Sofa.Simulation
    import SofaRuntime

    active_toggles = {k: v for k, v in os.environ.items() if k.startswith("PROBE_")}
    print(f"[probe] active toggles: {active_toggles or '(none — baseline)'}", file=sys.stderr)

    repeats = int(os.environ.get("PROBE_REPEATS", "5"))
    mod = _load_scene_module()

    # A single pair isn't trustworthy evidence (confirmed: bare cube+floor showed
    # both "identical" and "diverges" across repeated single-pair attempts) — so
    # same-process gets the same repeated-trial treatment as cross-process.
    print(f"\n=== A) same-process, {repeats} independent pairs ===", file=sys.stderr)
    a_results = []
    for r in range(repeats):
        trace_a1 = run_once(mod, Sofa, SofaRuntime, f"A{r}.1")
        trace_a2 = run_once(mod, Sofa, SofaRuntime, f"A{r}.2")
        idx_a, diff_a = first_divergence(trace_a1, trace_a2)
        a_results.append({"pair": r, "first_divergence_step": idx_a, "max_diff": diff_a})
        status = "IDENTICAL" if idx_a is None else f"diverged at step {idx_a} (diff {diff_a:.3e})"
        print(f"  pair {r}: {status}", file=sys.stderr)
    n_diverged_a = sum(1 for r in a_results if r["first_divergence_step"] is not None)

    print(f"\n=== B) cross-process, {repeats} independent pairs ===", file=sys.stderr)
    import subprocess

    scratch = Path(__file__).parent
    b_results = []
    for r in range(repeats):
        out1, out2 = scratch / f"probe_b1_{r}.json", scratch / f"probe_b2_{r}.json"
        for out in (out1, out2):
            subprocess.run([sys.executable, __file__, "--dump", str(out)], check=True, capture_output=True)
        trace_b1 = json.loads(out1.read_text())
        trace_b2 = json.loads(out2.read_text())
        idx_b, diff_b = first_divergence(trace_b1, trace_b2)
        b_results.append({"pair": r, "first_divergence_step": idx_b, "max_diff": diff_b})
        status = "IDENTICAL" if idx_b is None else f"diverged at step {idx_b} (diff {diff_b:.3e})"
        print(f"  pair {r}: {status}", file=sys.stderr)
        out1.unlink(missing_ok=True)
        out2.unlink(missing_ok=True)

    n_diverged = sum(1 for r in b_results if r["first_divergence_step"] is not None)

    print("\n=== VERDICT ===", file=sys.stderr)
    verdict = {
        "toggles": active_toggles,
        "repeats": repeats,
        "same_process_diverged_count": n_diverged_a,
        "same_process_divergence_rate": n_diverged_a / repeats,
        "same_process_results": a_results,
        "cross_process_diverged_count": n_diverged,
        "cross_process_divergence_rate": n_diverged / repeats,
        "cross_process_results": b_results,
    }
    print(json.dumps(verdict, indent=2))


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--dump":
        main_dump(sys.argv[2])
    else:
        main_compare()
