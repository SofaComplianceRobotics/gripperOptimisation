"""
Lab Generation - dashboard "Generate" button entrypoint.

Runs the gripper and leg generation scripts from the same lab_config.jsonc,
so hitting one button produces both parts. The two scripts write to disjoint
output trees (the gripper to runtime/exports + centerparts, the leg to
legs/), so they run concurrently here. Kept as a separate combined script
(rather than folding leg generation into generate_gripper.py) so the
optimizer's prepare_trial hook, which needs the two parts as trial-unique,
independently-named files, can keep calling generate_gripper.py /
generate_leg.py directly without this script's overhead or its shared,
non-trial-unique output names.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

GENERATION_DIR = Path(__file__).resolve().parent

SCRIPTS = ("generate_gripper.py", "generate_leg.py")


def main() -> None:
    procs = [
        subprocess.Popen(
            [sys.executable, str(GENERATION_DIR / script)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        for script in SCRIPTS
    ]

    failures = []
    for script, proc in zip(SCRIPTS, procs):
        out, _ = proc.communicate()
        print(f"--- {script} ---", flush=True)
        if out:
            sys.stdout.write(out)
            if not out.endswith("\n"):
                sys.stdout.write("\n")
            sys.stdout.flush()
        if proc.returncode != 0:
            failures.append(f"{script} (exit code {proc.returncode})")

    if failures:
        raise SystemExit("Generation failed: " + ", ".join(failures))


if __name__ == "__main__":
    main()
