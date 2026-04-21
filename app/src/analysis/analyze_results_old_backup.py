"""
analyze_results.py — Read trial results from the trials/ folder and display:
  1. A leaderboard printed to console (all scores, best first)
  2. A matplotlib window with three things on one plot:
       - Individual trial scores as scatter points (chronological)
    - Rolling average over last 10 trials as a line
       - Per-generation best as a line
"""

import json
import os
import statistics
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from matplotlib.widgets import Button

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────
TOP_X = 10
CENTERED_AVG_HALF_WINDOW = 10
LIVE_REFRESH_SECONDS = 2.0
LAB_ROOT = Path(__file__).resolve().parents[3]
TRIALS_DIR = LAB_ROOT / "runtime" / "trials"
CMAES_STARTUP_TRIALS = int(os.environ.get("CMAES_STARTUP_TRIALS", "50"))
HARD_FAIL_SCORE = float(
    os.environ.get("HARD_FAIL_SCORE", "-3.0")
)  # generation-failure score
CONSISTENCY_PENALTY_COEF = float(os.environ.get("CONSISTENCY_PENALTY_COEF", "0.1"))
SCORE_AGGREGATION = os.environ.get("SCORE_AGGREGATION", "mean").strip().lower()


# ─────────────────────────────────────────────
# Data Loading
# ─────────────────────────────────────────────


def load_all_trials() -> list[dict]:
    """
    Load all trial results, including failures, from the trials directory.
    Computes final_score with consistency penalty using the current runtime settings.

    Inputs:
        None

    Returns:
        list[dict]: Trial records in chronological order.
    """
    records = []
    chron = 0
    failed_states = {"failed", "error", "cancelled", "skipped"}
    for gen_dir in sorted(TRIALS_DIR.glob("gen_*")):
        gen_index = int(gen_dir.name.split("_")[1])
        for trial_dir in sorted(gen_dir.glob("trial_*")):
            trial_index = int(trial_dir.name.split("_")[1])

            run_files = sorted(trial_dir.glob("score_run*.json"))
            status_files = sorted(trial_dir.glob("status_run*.json"))

            if not run_files:
                legacy = trial_dir / "score.json"
                if legacy.exists():
                    run_files = [legacy]

            if not run_files:
                failed_from_status = False
                fail_reason = "no score files"
                trial_stats_path = trial_dir / "trial_stats.json"
                if trial_stats_path.exists():
                    try:
                        trial_stats = json.loads(trial_stats_path.read_text())
                        stats_valid_scores = trial_stats.get("run_scores_valid", [])
                        stats_all_scores = trial_stats.get("run_scores", [])
                        records.append(
                            {
                                "gen_index": gen_index,
                                "trial_index": trial_index,
                                "gen_name": gen_dir.name,
                                "trial_name": trial_dir.name,
                                "score": trial_stats.get(
                                    "aggregate_score",
                                    trial_stats.get(
                                        "avg_score",
                                        trial_stats.get("median_score", 0.0),
                                    ),
                                ),
                                "final_score": trial_stats.get("final_score", 0.0),
                                "failed": False,
                                "fail_reason": str(trial_stats.get("outcome", "")),
                                "outcome_reason": str(trial_stats.get("outcome", "")),
                                "n_runs": int(trial_stats.get("n_runs", 0)),
                                "run_scores": [
                                    float(s)
                                    for s in stats_valid_scores
                                    if isinstance(s, (int, float))
                                ],
                                "all_run_scores": [
                                    float(s)
                                    for s in stats_all_scores
                                    if isinstance(s, (int, float))
                                ],
                                "chron": chron,
                            }
                        )
                        chron += 1
                        continue
                    except Exception:
                        pass
                for sf in status_files:
                    try:
                        s = json.loads(sf.read_text())
                    except Exception:
                        continue
                    state = str(s.get("state", "")).lower()
                    reason = str(s.get("reason", "")).lower()
                    if (
                        state in failed_states
                        or state == "pruned"
                        or "geometry export failed" in reason
                        or "geometry export timed out" in reason
                        or "test horizon complete" in reason
                        or "glitched through floor after pickup" in reason
                    ):
                        failed_from_status = True
                        if reason:
                            fail_reason = reason
                        break

                if failed_from_status or trial_dir.exists():
                    records.append(
                        {
                            "gen_index": gen_index,
                            "trial_index": trial_index,
                            "gen_name": gen_dir.name,
                            "trial_name": trial_dir.name,
                            "score": 0.0,
                            "final_score": 0.0,
                            "failed": True,
                            "fail_reason": fail_reason,
                            "outcome_reason": fail_reason,
                            "n_runs": 0,
                            "run_scores": [],
                            "all_run_scores": [],
                            "chron": chron,
                        }
                    )
                    chron += 1
                continue

            run_scores = []
            for sf in run_files:
                try:
                    run_scores.append(float(json.loads(sf.read_text())["cube_z_final"]))
                except Exception:
                    continue

            valid = [s for s in run_scores if s != float("-inf")]
            failed = len(valid) == 0
            if valid:
                if SCORE_AGGREGATION == "median":
                    score = statistics.median(valid)
                else:
                    score = statistics.mean(valid)
            else:
                score = 0.0
            outcome_reason = ""

            for sf in status_files:
                try:
                    s = json.loads(sf.read_text())
                except Exception:
                    continue
                reason = str(s.get("reason", "")).strip()
                if reason:
                    outcome_reason = reason
                    break

            # Compute consistency-penalized final_score
            final_score = score
            if valid and not failed:
                consistency_penalty = CONSISTENCY_PENALTY_COEF * (
                    max(valid) - min(valid)
                )
                final_score = score - consistency_penalty
            else:
                final_score = 0.0

            # Check if trial_stats.json exists (modern format) and use its value if available
            trial_stats_path = trial_dir / "trial_stats.json"
            if trial_stats_path.exists():
                try:
                    trial_stats = json.loads(trial_stats_path.read_text())
                    score = trial_stats.get(
                        "aggregate_score",
                        trial_stats.get(
                            "avg_score", trial_stats.get("median_score", score)
                        ),
                    )
                    final_score = trial_stats.get("final_score", final_score)
                except Exception:
                    pass

            records.append(
                {
                    "gen_index": gen_index,
                    "trial_index": trial_index,
                    "gen_name": gen_dir.name,
                    "trial_name": trial_dir.name,
                    "score": score,
                    "final_score": final_score,
                    "failed": failed,
                    "fail_reason": outcome_reason.lower() if failed else "",
                    "outcome_reason": outcome_reason.lower(),
                    "n_runs": len(valid),
                    "run_scores": valid,
                    "all_run_scores": run_scores,
                    "chron": chron,
                }
            )
            chron += 1
    return records


def load_gen_summaries() -> list[dict]:
    """
    Load generation summaries from summary.json files.

    Inputs:
        None

    Returns:
        list[dict]: Summary records by generation.
    """
    summaries = []
    for gen_dir in sorted(TRIALS_DIR.glob("gen_*")):
        summary_path = gen_dir / "summary.json"
        if not summary_path.exists():
            continue
        try:
            data = json.loads(summary_path.read_text())
            summaries.append(
                {
                    "gen_index": data["gen"],
                    "avg_score": data["avg_score"],
                    "best_score": data["best_score"],
                    "n_trials": data.get("n_trials"),
                    "n_valid": data.get("n_valid"),
                }
            )
        except Exception:
            continue
    return summaries


# ─────────────────────────────────────────────
# Leaderboard
# ─────────────────────────────────────────────


def print_leaderboard(records: list[dict]):
    """
    Print top valid trials ranked by final_score (consistency-adjusted) and per-generation failure statistics.

    Inputs:
        records (list[dict]): Trial records.

    Returns:
        None
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


# ─────────────────────────────────────────────
# Plot
# ─────────────────────────────────────────────


def plot_combined(records: list[dict], summaries: list[dict]):
    """
    Plot trial scores, generation trends, and failed-trial markers.

    Inputs:
        records (list[dict]): Trial records.
        summaries (list[dict]): Generation summary records.

    Returns:
        None
    """
    if not records:
        print("[warn] No trial data to plot.")
        return

    def compute_plot_data(current_records: list[dict]) -> dict:
        gen_chrons: dict[int, list[int]] = {}
        for r in current_records:
            gen_chrons.setdefault(r["gen_index"], []).append(r["chron"])

        # Calculate centered moving average with +/- CENTERED_AVG_HALF_WINDOW trials.
        avg_x, avg_y = [], []
        for i, r in enumerate(current_records):
            lo = max(0, i - CENTERED_AVG_HALF_WINDOW)
            hi = min(len(current_records) - 1, i + CENTERED_AVG_HALF_WINDOW)
            window = current_records[lo : hi + 1]
            window_scores = [w["final_score"] for w in window]
            avg_x.append(r["chron"])
            avg_y.append(sum(window_scores) / len(window_scores))

        # Calculate best-so-far across all trials (chronological, monotonically non-decreasing)
        best_x, best_y = [], []
        running_best = None
        for r in current_records:
            if not r["failed"]:
                if running_best is None or r["final_score"] > running_best:
                    running_best = r["final_score"]
            if running_best is not None:
                best_x.append(r["chron"])
                best_y.append(running_best)

        xs = [r["chron"] for r in current_records]
        success_records = [r for r in current_records if not r["failed"]]
        failed_records = [r for r in current_records if r["failed"]]

        success_xs = [r["chron"] for r in success_records]
        success_ys = [r["score"] for r in success_records]
        failed_xs = [r["chron"] for r in failed_records]
        failed_ys = [r["score"] for r in failed_records]
        final_score_xs = [r["chron"] for r in success_records]
        final_score_ys = [r["final_score"] for r in success_records]

        run_xs, run_ys = [], []
        for r in success_records:
            for s in r["run_scores"]:
                run_xs.append(r["chron"])
                run_ys.append(s)

        gen_breaks = []
        prev_gen = None
        for r in current_records:
            if r["gen_index"] != prev_gen and prev_gen is not None:
                gen_breaks.append(r["chron"] - 0.5)
            prev_gen = r["gen_index"]

        gen_mid_x = [(min(c) + max(c)) / 2 for c in gen_chrons.values()]
        gen_labels = [f"gen {g}" for g in sorted(gen_chrons.keys())]
        cmaes_switch_x = (
            CMAES_STARTUP_TRIALS - 0.5
            if 0 < CMAES_STARTUP_TRIALS < len(current_records)
            else None
        )

        return {
            "xs": xs,
            "success_xs": success_xs,
            "success_ys": success_ys,
            "failed_xs": failed_xs,
            "failed_ys": failed_ys,
            "final_score_xs": final_score_xs,
            "final_score_ys": final_score_ys,
            "run_xs": run_xs,
            "run_ys": run_ys,
            "avg_x": avg_x,
            "avg_y": avg_y,
            "best_x": best_x,
            "best_y": best_y,
            "gen_breaks": gen_breaks,
            "gen_mid_x": gen_mid_x,
            "gen_labels": gen_labels,
            "cmaes_switch_x": cmaes_switch_x,
        }

    data = compute_plot_data(records)

    fig, ax = plt.subplots(figsize=(max(10, len(data["xs"]) * 0.45), 5))
    fig.subplots_adjust(bottom=0.2)
    # Plot successful trials in brown, failed trials in red

    # Plot successful trials in brown, failed trials in red
    scatter = ax.scatter(
        data["success_xs"],
        data["success_ys"],
        c="#b34418",
        s=20,
        zorder=4,
        label="Trial score (avg)",
    )

    scatter_failed = ax.scatter(
        data["failed_xs"],
        data["failed_ys"],
        c="#d62728",
        s=60,
        zorder=4,
        marker="x",
        label="Failed trial",
    )

    scatter_final = ax.scatter(
        data["final_score_xs"],
        data["final_score_ys"],
        c="#67bd67",
        s=60,
        zorder=3,
        marker="o",
        label="Final score",
    )

    scatter_runs = ax.scatter(
        data["run_xs"],
        data["run_ys"],
        c="#e08040",
        s=25,
        zorder=5,
        label="Individual runs",
        marker="x",
    )
    (avg_line,) = ax.plot(
        data["avg_x"],
        data["avg_y"],
        color="steelblue",
        linewidth=2,
        linestyle="-",
        zorder=3,
        label=f"Centered avg (+/-{CENTERED_AVG_HALF_WINDOW})",
    )

    (best_line,) = ax.plot(
        data["best_x"],
        data["best_y"],
        color="darkorange",
        linewidth=2,
        linestyle="--",
        zorder=3,
        label="Gen best",
    )

    vlines = [
        ax.axvline(x, color="gray", linestyle=":", linewidth=1, zorder=1)
        for x in data["gen_breaks"]
    ]

    cmaes_switch_line = ax.axvline(
        data["cmaes_switch_x"] if data["cmaes_switch_x"] is not None else float("nan"),
        color="#7f3c8d",
        linestyle="-.",
        linewidth=1.8,
        zorder=2,
        label=f"CMA-ES starts (trial {CMAES_STARTUP_TRIALS})",
    )
    cmaes_switch_line.set_visible(data["cmaes_switch_x"] is not None)

    ax2 = ax.twiny()
    ax2.set_xlim(ax.get_xlim())
    ax2.set_xticks(data["gen_mid_x"])
    ax2.set_xticklabels(data["gen_labels"], fontsize=8)
    ax2.tick_params(length=0)

    ax.set_xlabel("Trial (chronological)")
    ax.set_ylabel("Final score (consistency-adjusted)")
    ax.set_title(
        "Gripper optimization progress", fontsize=13, fontweight="bold", pad=20
    )
    ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.legend(loc="upper left")

    # ── Toggle buttons ────────────────────────────────────────────────────────
    state = {
        "scatter": True,
        "final_score": True,
        "runs": False,
        "failed": True,
        "avg": True,
        "best": True,
        "vlines": True,
        "cmaes_switch": True,
        "live_refresh": True,
    }

    def set_scatter_offsets(artist, xs, ys):
        if xs and ys:
            artist.set_offsets(list(zip(xs, ys)))
        else:
            artist.set_offsets([[float("nan"), float("nan")]])

    def fit_axes_to_all_data(updated: dict) -> None:
        if updated["xs"]:
            ax.set_xlim(min(updated["xs"]) - 1, max(updated["xs"]) + 1)

        y_sources = [
            updated["success_ys"],
            updated["failed_ys"],
            updated["final_score_ys"],
            updated["run_ys"],
            updated["avg_y"],
            updated["best_y"],
        ]
        y_values = [
            float(v)
            for series in y_sources
            for v in series
            if isinstance(v, (int, float))
        ]
        if y_values:
            y_min = min(y_values)
            y_max = max(y_values)
            if y_min == y_max:
                pad = 1.0
            else:
                pad = 0.05 * (y_max - y_min)
            ax.set_ylim(y_min - pad, y_max + pad)

    def update_toolbar_home_view() -> None:
        toolbar = getattr(fig.canvas, "toolbar", None)
        if toolbar is None:
            return
        nav_stack = getattr(toolbar, "_nav_stack", None)
        if nav_stack is None:
            return
        try:
            nav_stack.clear()
            toolbar.push_current()
        except Exception:
            pass

    def refresh_plot_data(updated_records: list[dict]) -> None:
        nonlocal records, vlines
        records = updated_records
        updated = compute_plot_data(records)

        set_scatter_offsets(scatter, updated["success_xs"], updated["success_ys"])
        set_scatter_offsets(scatter_failed, updated["failed_xs"], updated["failed_ys"])
        set_scatter_offsets(
            scatter_final,
            updated["final_score_xs"],
            updated["final_score_ys"],
        )
        set_scatter_offsets(scatter_runs, updated["run_xs"], updated["run_ys"])

        avg_line.set_data(updated["avg_x"], updated["avg_y"])
        best_line.set_data(updated["best_x"], updated["best_y"])

        for vl in vlines:
            vl.remove()
        vlines = [
            ax.axvline(x, color="gray", linestyle=":", linewidth=1, zorder=1)
            for x in updated["gen_breaks"]
        ]

        if updated["cmaes_switch_x"] is not None:
            cmaes_switch_line.set_xdata(
                [updated["cmaes_switch_x"], updated["cmaes_switch_x"]]
            )
            cmaes_switch_line.set_visible(state["cmaes_switch"])
        else:
            cmaes_switch_line.set_visible(False)

        fit_axes_to_all_data(updated)

        ax2.set_xlim(ax.get_xlim())
        ax2.set_xticks(updated["gen_mid_x"])
        ax2.set_xticklabels(updated["gen_labels"], fontsize=8)

        scatter.set_visible(state["scatter"])
        scatter_final.set_visible(state["final_score"])
        scatter_runs.set_visible(state["runs"])
        scatter_failed.set_visible(state["failed"])
        avg_line.set_visible(state["avg"])
        best_line.set_visible(state["best"])
        for vl in vlines:
            vl.set_visible(state["vlines"])

        ax.legend(loc="upper left")
        update_toolbar_home_view()
        fig.canvas.draw_idle()

    btn_colors = {
        True: "#a0a0a0",
        False: "#cacaca",
    }

    btn_ax_scatter = fig.add_axes([0.02, 0.05, 0.11, 0.06])
    btn_ax_final = fig.add_axes([0.14, 0.05, 0.11, 0.06])
    btn_ax_runs = fig.add_axes([0.26, 0.05, 0.11, 0.06])
    btn_ax_failed = fig.add_axes([0.38, 0.05, 0.11, 0.06])
    btn_ax_avg = fig.add_axes([0.50, 0.05, 0.11, 0.06])
    btn_ax_best = fig.add_axes([0.62, 0.05, 0.11, 0.06])
    btn_ax_vlines = fig.add_axes([0.74, 0.05, 0.11, 0.06])
    btn_ax_cmaes = fig.add_axes([0.86, 0.05, 0.11, 0.06])
    btn_ax_live = fig.add_axes([0.02, 0.12, 0.11, 0.06])

    btn_scatter = Button(
        btn_ax_scatter, "Trial scores", color="#a0a0a0", hovercolor="#cacaca"
    )
    btn_final = Button(
        btn_ax_final, "Final scores", color="#a0a0a0", hovercolor="#cacaca"
    )
    btn_runs = Button(btn_ax_runs, "Indiv. runs", color="#a0a0a0", hovercolor="#cacaca")
    btn_failed = Button(
        btn_ax_failed, "Failures", color="#a0a0a0", hovercolor="#cacaca"
    )
    btn_avg = Button(
        btn_ax_avg,
        f"Centered avg (+/-{CENTERED_AVG_HALF_WINDOW})",
        color="#a0a0a0",
        hovercolor="#cacaca",
    )
    btn_best = Button(btn_ax_best, "Gen best", color="#a0a0a0", hovercolor="#cacaca")
    btn_vlines = Button(
        btn_ax_vlines, "Gen borders", color="#a0a0a0", hovercolor="#cacaca"
    )
    btn_cmaes = Button(
        btn_ax_cmaes, "CMAES switch", color="#a0a0a0", hovercolor="#cacaca"
    )
    btn_live = Button(btn_ax_live, "Live: ON", color="#a0a0a0", hovercolor="#cacaca")

    def toggle_scatter(_):
        state["scatter"] = not state["scatter"]
        scatter.set_visible(state["scatter"])
        btn_scatter.color = btn_colors[state["scatter"]]
        btn_scatter.hovercolor = btn_colors[not state["scatter"]]
        btn_scatter.ax.set_facecolor(btn_colors[state["scatter"]])
        fig.canvas.draw_idle()

    def toggle_final(_):
        state["final_score"] = not state["final_score"]
        scatter_final.set_visible(state["final_score"])
        btn_final.color = btn_colors[state["final_score"]]
        btn_final.hovercolor = btn_colors[not state["final_score"]]
        btn_final.ax.set_facecolor(btn_colors[state["final_score"]])
        fig.canvas.draw_idle()

    def toggle_runs(_):
        state["runs"] = not state["runs"]
        scatter_runs.set_visible(state["runs"])
        btn_runs.color = btn_colors[state["runs"]]
        btn_runs.hovercolor = btn_colors[not state["runs"]]
        btn_runs.ax.set_facecolor(btn_colors[state["runs"]])
        fig.canvas.draw_idle()

    def toggle_failed(_):
        state["failed"] = not state["failed"]
        scatter_failed.set_visible(state["failed"])
        btn_failed.color = btn_colors[state["failed"]]
        btn_failed.hovercolor = btn_colors[not state["failed"]]
        btn_failed.ax.set_facecolor(btn_colors[state["failed"]])
        fig.canvas.draw_idle()

    def toggle_avg(_):
        state["avg"] = not state["avg"]
        avg_line.set_visible(state["avg"])
        btn_avg.color = btn_colors[state["avg"]]
        btn_avg.hovercolor = btn_colors[not state["avg"]]
        btn_avg.ax.set_facecolor(btn_colors[state["avg"]])
        fig.canvas.draw_idle()

    def toggle_best(_):
        state["best"] = not state["best"]
        best_line.set_visible(state["best"])
        btn_best.color = btn_colors[state["best"]]
        btn_best.hovercolor = btn_colors[not state["best"]]
        btn_best.ax.set_facecolor(btn_colors[state["best"]])
        fig.canvas.draw_idle()

    def toggle_vlines(_):
        state["vlines"] = not state["vlines"]
        for vl in vlines:
            vl.set_visible(state["vlines"])
        btn_vlines.color = btn_colors[state["vlines"]]
        btn_vlines.hovercolor = btn_colors[not state["vlines"]]
        btn_vlines.ax.set_facecolor(btn_colors[state["vlines"]])
        fig.canvas.draw_idle()

    def toggle_cmaes(_):
        state["cmaes_switch"] = not state["cmaes_switch"]
        cmaes_switch_line.set_visible(state["cmaes_switch"])
        btn_cmaes.color = btn_colors[state["cmaes_switch"]]
        btn_cmaes.hovercolor = btn_colors[not state["cmaes_switch"]]
        btn_cmaes.ax.set_facecolor(btn_colors[state["cmaes_switch"]])
        fig.canvas.draw_idle()

    btn_scatter.on_clicked(toggle_scatter)
    btn_final.on_clicked(toggle_final)
    btn_runs.on_clicked(toggle_runs)
    btn_failed.on_clicked(toggle_failed)
    btn_avg.on_clicked(toggle_avg)
    btn_best.on_clicked(toggle_best)
    btn_vlines.on_clicked(toggle_vlines)
    btn_cmaes.on_clicked(toggle_cmaes)

    refresh_timer = fig.canvas.new_timer(interval=int(LIVE_REFRESH_SECONDS * 1000))

    def on_refresh_timer():
        try:
            updated_records = load_all_trials()
            if updated_records:
                refresh_plot_data(updated_records)
        except Exception as e:
            print(f"[warn] Live refresh failed: {e}")

    refresh_timer.add_callback(on_refresh_timer)
    refresh_timer.start()

    def toggle_live_refresh(_):
        state["live_refresh"] = not state["live_refresh"]
        if state["live_refresh"]:
            refresh_timer.start()
            btn_live.label.set_text("Live: ON")
        else:
            refresh_timer.stop()
            btn_live.label.set_text("Live: OFF")
        btn_live.color = btn_colors[state["live_refresh"]]
        btn_live.hovercolor = btn_colors[not state["live_refresh"]]
        btn_live.ax.set_facecolor(btn_colors[state["live_refresh"]])
        fig.canvas.draw_idle()

    btn_live.on_clicked(toggle_live_refresh)

    def on_close(_event):
        refresh_timer.stop()

    fig.canvas.mpl_connect("close_event", on_close)

    fig.tight_layout(rect=[0, 0.15, 1, 1])

    mng = plt.get_current_fig_manager()
    mng.window.state("zoomed")

    plt.show()


# ─────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────


def main():
    records = load_all_trials()
    summaries = load_gen_summaries()

    if not records:
        print("[error] No score files found. Has the optimizer run yet?")
        return

    print_leaderboard(records)
    plot_combined(records, summaries)


if __name__ == "__main__":
    main()
