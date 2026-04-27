"""
analyze_leaderboard.py — Ranking, statistics, and leaderboard generation.

Produces console output summaries of trial rankings and failure analysis.
"""

from analyze_config import TOP_X


def print_leaderboard(records: list[dict]) -> None:
    """Print top valid trials ranked by final_score and per-generation failure statistics.

    Args:
        records: Trial records from load_all_trials().
    """
    valid_records = [r for r in records if not r["failed"]]
    sorted_records = sorted(valid_records, key=lambda r: r["final_score"], reverse=True)

    col_w = 28
    print(f"\n{'─'*55}")
    print(f"  {'RANK':<6} {'TRIAL':<{col_w}} {'FINAL SCORE':>10}")
    print(f"{'─'*55}")

    for rank, r in enumerate(sorted_records, 1):
        label = f"{r['gen_name']}/{r['trial_name']}"
        marker = " ◀ BEST" if rank == 1 else ""
        print(f"  {rank:<6} {label:<{col_w}} {r['final_score']:>10.4f}{marker}")
        if rank >= TOP_X and len(sorted_records) > TOP_X:
            print(f"  ... ({len(sorted_records) - TOP_X} more trials not shown)")
            break

    print(f"{'─'*55}\n")

    if not sorted_records:
        print("[warn] No valid trials found to rank.\n")

    total = len(records)
    failed = sum(1 for r in records if r["failed"])
    print(
        f"[reliability] failed trials: {failed}/{total} ({(100 * failed / total):.1f}%)"
    )

    print("\n[reliability by generation]")
    by_gen: dict[int, list[dict]] = {}
    for r in records:
        by_gen.setdefault(r["gen_index"], []).append(r)

    for gen_index in sorted(by_gen.keys()):
        gen_records = by_gen[gen_index]
        gen_total = len(gen_records)
        gen_failed = sum(1 for r in gen_records if r["failed"])
        pct = 100 * gen_failed / gen_total if gen_total else 0.0
        print(f"  gen {gen_index:04d}: {gen_failed}/{gen_total} failed ({pct:.1f}%)")
    print("")
