"""Persistent generation worker for the dashboard's Generate button.

Kept alive by dashboard/process_manager.py so repeated clicks skip
the ~1.3s of Python start-up and `import cadquery` that a fresh
generate_all.py subprocess pays every time. The CAD stack is imported once,
here, and then reused.

Protocol: one JSON object per line on stdin, one JSON reply per line on
stdout. The generation scripts' own stdout/stderr is redirected to the log
file named in the request (the dashboard already tails it), so it never
mixes into the reply channel.

    ->  (on startup, once)              {"ok": true, "ready": true}
    <-  {"cmd": "generate",
         "config": "<path>", "log": "<path>"}
    ->  {"ok": true, "elapsed": 2.41}
    ->  {"ok": false, "error": "..."}
    <-  {"cmd": "ping"}    ->  {"ok": true}
    <-  {"cmd": "shutdown"}   (no reply; process exits)

The worker is disposable: it replies ok=false on any failure and keeps
serving, the manager recycles it periodically, and the manager always has
the cold generate_all.py subprocess to fall back on.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import sys
import time
import traceback
from pathlib import Path

LAB_ROOT = Path(__file__).resolve().parents[1]
for _p in (str(LAB_ROOT), str(Path(__file__).resolve().parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _gripper_common import ensure_cadquery_runtime, load_jsonc, params_from_config

ensure_cadquery_runtime()

from geometry.export_pipeline import run_export  # noqa: E402
from geometry.params import ModelParams  # noqa: E402
from names import CENTERPARTS_DIRNAME  # noqa: E402

CENTERPARTS_DIR = LAB_ROOT.parent.parent / "data" / "meshes" / CENTERPARTS_DIRNAME
LEG_SCRIPT = Path(__file__).resolve().parent / "generate_leg.py"


def _generate(config_path: Path) -> None:
    """Run the gripper and leg export for one config, same outputs as
    generate_gripper.py + generate_leg.py.

    The gripper runs in-process (this worker keeps the CAD stack warm); the
    leg runs as a concurrent subprocess (it needs beziers/numpy, not the CAD
    imports, and gmsh's global state rules out a second thread here), so the
    two overlap.
    """
    cfg = load_jsonc(config_path)

    leg_proc = subprocess.Popen(
        [sys.executable, str(LEG_SCRIPT), "--config", str(config_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=str(LEG_SCRIPT.parent),
    )

    gripper_error: Exception | None = None
    try:
        gripper_params = params_from_config(cfg, ModelParams())
        stl_path = run_export(gripper_params, secondary_dir=CENTERPARTS_DIR)
        if stl_path is None:
            raise RuntimeError("Mesh export did not produce an STL path.")
        for path in (stl_path, stl_path.with_suffix(".json"), stl_path.with_suffix(".vtk")):
            if path.exists():
                print(f"Exported: {path}")
    except Exception as exc:  # still drain the leg before surfacing this
        gripper_error = exc

    leg_out, _ = leg_proc.communicate()
    if leg_out:
        print(leg_out, end="" if leg_out.endswith("\n") else "\n")

    if gripper_error is not None:
        raise gripper_error
    if leg_proc.returncode != 0:
        raise RuntimeError(f"Leg generation failed (exit code {leg_proc.returncode}).")


def _handle_generate(msg: dict) -> dict:
    log_path = Path(msg["log"])
    config_path = Path(msg["config"])
    log_path.parent.mkdir(parents=True, exist_ok=True)

    start = time.perf_counter()
    with open(log_path, "a", encoding="utf-8", buffering=1) as log:
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            try:
                _generate(config_path)
            except Exception as exc:
                traceback.print_exc(file=log)
                return {"ok": False, "error": str(exc)}
            elapsed = time.perf_counter() - start
            print(f"Total generation time: {elapsed:.3f}s")
    return {"ok": True, "elapsed": elapsed}


def _handle(msg: dict) -> dict:
    cmd = msg.get("cmd")
    if cmd == "ping":
        return {"ok": True}
    if cmd == "generate":
        return _handle_generate(msg)
    return {"ok": False, "error": f"unknown command {cmd!r}"}


def main() -> None:
    sys.stdout.write(json.dumps({"ok": True, "ready": True}) + "\n")
    sys.stdout.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            reply = {"ok": False, "error": "malformed request"}
        else:
            if msg.get("cmd") == "shutdown":
                return
            try:
                reply = _handle(msg)
            except Exception as exc:  # never let one bad request kill the worker
                reply = {"ok": False, "error": f"worker error: {exc}"}
        sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
