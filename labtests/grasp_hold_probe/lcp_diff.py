"""
lcp_diff — runs grasp_hold_probe (full robot, frozen, loose/broken tolerance)
for a handful of steps in TWO separate processes with PROBE_DUMP_LCP=1, then
parses SOFA's own printLCP() output (W matrix, dfree/"delta", force/"lambda")
from both and reports the exact first entry where they differ.

This finds where the tiny difference is actually born, instead of inferring
it from downstream position/velocity effects.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

SCRATCH = Path(__file__).parent
EMIOLABS_PYTHON = r"C:\Users\Cesar\AppData\Local\Programs\emio-labs\resources\sofa\bin\python\python.exe"
RUNNER = SCRATCH / "lcp_dump_runner.py"

N_STEPS = 6  # covers the known first-divergence step (3) with a little margin


def run_and_capture(tag: str) -> str:
    out_path = SCRATCH / f"lcp_{tag}.log"
    env_prefix = "PROBE_SKIP_PLAYBACK=1 PROBE_DUMP_LCP=1"
    proc = subprocess.run(
        [EMIOLABS_PYTHON, str(RUNNER), str(N_STEPS)],
        capture_output=True,
        text=True,
        env={
            **__import__("os").environ,
            "PROBE_SKIP_PLAYBACK": "1",
            "PROBE_DUMP_LCP": "1",
        },
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
                w = [flat]  # fallback: couldn't reshape, keep as one row so diffing still works
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


def main():
    print("[lcp_diff] running A...", file=sys.stderr)
    out_a = run_and_capture("A")
    print("[lcp_diff] running B...", file=sys.stderr)
    out_b = run_and_capture("B")

    blocks_a = parse_blocks(out_a)
    blocks_b = parse_blocks(out_b)
    print(f"[lcp_diff] parsed {len(blocks_a)} blocks from A, {len(blocks_b)} from B", file=sys.stderr)

    n = min(len(blocks_a), len(blocks_b))
    for i in range(n):
        ba, bb = blocks_a[i], blocks_b[i]
        print(f"\n--- block {i} ({ba['phase']} resolution) ---")

        d_diff = first_diff_vec(ba["delta"], bb["delta"])
        print(f"  dfree/delta: {'IDENTICAL' if d_diff is None else d_diff}")

        l_diff = first_diff_vec(ba["lambda"], bb["lambda"])
        print(f"  force/lambda: {'IDENTICAL' if l_diff is None else l_diff}")

        if ba["W"] is not None:
            w_diff = first_diff_mat(ba["W"], bb["W"])
            print(f"  W matrix ({len(ba['W'])}x{len(ba['W'][0]) if ba['W'] else 0}): {'IDENTICAL' if w_diff is None else w_diff}")

        if d_diff is not None or l_diff is not None or (ba["W"] is not None and first_diff_mat(ba["W"], bb["W"]) is not None):
            print(f"  >>> FIRST DIVERGENCE at block {i} ({ba['phase']} resolution) <<<")
            if ba["W"] is not None:
                print("\n  --- full first-contact 3x3 block (rows/cols 0-2) ---")
                for r in range(3):
                    row_a = [f"{ba['W'][r][c]:+.9f}" for c in range(3)]
                    row_b = [f"{bb['W'][r][c]:+.9f}" for c in range(3)]
                    same = row_a == row_b
                    marker = "   " if same else " <<"
                    print(f"    A row {r}: {row_a}{marker}")
                    print(f"    B row {r}: {row_b}{marker}")
            break
    else:
        print("\n[lcp_diff] all captured blocks identical — divergence must be after these steps or not captured")


if __name__ == "__main__":
    main()
