"""
analyze_plotting.py — Matplotlib visualization and interactive plots.

Creates performance plots with trial scores, rolling averages,
  and per-generation trends.
"""

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from matplotlib.widgets import Button

from analyze_config import CENTERED_AVG_HALF_WINDOW, LIVE_REFRESH_SECONDS
from analyze_io import load_all_trials


def plot_combined(records: list[dict], summaries: list[dict]) -> None:
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

    _ = summaries

    def compute_plot_data(current_records: list[dict]) -> dict:
        # Plot each trial at its chronological index, but label x-axis with generation numbers
        success_records = [r for r in current_records if not r["failed"]]
        failed_records = [r for r in current_records if r["failed"]]

        # X-axis: trial index (chronological)
        success_xs = [r["chron"] for r in success_records]
        success_ys = [r["score"] for r in success_records]
        failed_xs = [r["chron"] for r in failed_records]
        failed_ys = [r["score"] for r in failed_records]

        # Calculate centered moving average (by trial index)
        avg_x, avg_y = [], []
        for i, r in enumerate(current_records):
            lo = max(0, i - CENTERED_AVG_HALF_WINDOW)
            hi = min(len(current_records) - 1, i + CENTERED_AVG_HALF_WINDOW)
            window = current_records[lo : hi + 1]
            window_scores = [w["final_score"] for w in window]
            avg_x.append(r["chron"])
            avg_y.append(sum(window_scores) / len(window_scores))

        # Calculate best-so-far (by trial index)
        best_x, best_y = [], []
        running_best = None
        for r in current_records:
            if not r["failed"]:
                if running_best is None or r["final_score"] > running_best:
                    running_best = r["final_score"]
            if running_best is not None:
                best_x.append(r["chron"])
                best_y.append(running_best)

        # Generation breaks and tick positions
        gen_tick_positions = []
        gen_tick_labels = []
        prev_gen = None
        for r in current_records:
            if r["gen_index"] != prev_gen:
                gen_tick_positions.append(r["chron"])
                gen_tick_labels.append(str(r["gen_index"]))
            prev_gen = r["gen_index"]

        return {
            "success_xs": success_xs,
            "success_ys": success_ys,
            "failed_xs": failed_xs,
            "failed_ys": failed_ys,
            "avg_x": avg_x,
            "avg_y": avg_y,
            "best_x": best_x,
            "best_y": best_y,
            "gen_tick_positions": gen_tick_positions,
            "gen_tick_labels": gen_tick_labels,
        }

    plot_data = compute_plot_data(records)

    fig, ax = plt.subplots(figsize=(14, 8))
    fig.subplots_adjust(bottom=0.20)

    # No vertical lines for generation breaks; x-ticks show generation boundaries

    success_scatter = ax.scatter(
        plot_data["success_xs"],
        plot_data["success_ys"],
        color="#4a90d9",
        s=40,
        alpha=0.6,
        label="Trial Scores",
        zorder=3,
    )
    failed_scatter = ax.scatter(
        plot_data["failed_xs"],
        plot_data["failed_ys"],
        color="#d94a4a",
        s=40,
        marker="x",
        alpha=0.6,
        label="Failed Trials",
        zorder=3,
    )

    (avg_line,) = ax.plot(
        plot_data["avg_x"],
        plot_data["avg_y"],
        color="#2ecc71",
        linestyle="--",
        linewidth=2,
        label=f"Rolling Avg (±{CENTERED_AVG_HALF_WINDOW})",
        alpha=0.8,
        zorder=4,
    )

    (best_line,) = ax.plot(
        plot_data["best_x"],
        plot_data["best_y"],
        color="#e74c3c",
        linestyle="-",
        linewidth=2,
        label="Best So Far",
        alpha=0.8,
        zorder=4,
    )

    ax.set_xlabel("Generation", fontsize=12, fontweight="bold")
    # Set x-ticks at the start of each generation, labeled with generation number
    ax.set_xticks(plot_data["gen_tick_positions"])
    ax.set_xticklabels(plot_data["gen_tick_labels"], rotation=0, fontsize=10)
    ax.set_ylabel("Final Score (Consistency-Adjusted)", fontsize=12, fontweight="bold")
    ax.set_title("Gripper Optimization Results", fontsize=14, fontweight="bold")
    ax.grid(axis="y", which="both", alpha=0.3)
    ax.legend(loc="lower right", fontsize=10)

    ax.yaxis.set_major_locator(ticker.MaxNLocator(nbins=10))
    ax.xaxis.set_major_locator(ticker.MaxNLocator(nbins=20))

    state = {
        "live": False,
        "controls_visible": True,
        "trial_scores": True,
        "failed_trials": True,
        "rolling_avg": True,
        "best_so_far": True,
        "gen_breaks": True,
    }

    def set_offsets(scatter_artist, xs: list[float], ys: list[float]) -> None:
        if xs and ys:
            scatter_artist.set_offsets(list(zip(xs, ys)))
        else:
            scatter_artist.set_offsets([[float("nan"), float("nan")]])

    def refit_axes(updated: dict) -> None:
        all_x = (
            updated["success_xs"]
            + updated["failed_xs"]
            + updated["avg_x"]
            + updated["best_x"]
        )
        all_y = (
            updated["success_ys"]
            + updated["failed_ys"]
            + updated["avg_y"]
            + updated["best_y"]
        )

        if all_x:
            x_min = min(all_x)
            x_max = max(all_x)
            x_pad = max(1.0, 0.02 * max(1.0, x_max - x_min))
            ax.set_xlim(x_min - x_pad, x_max + x_pad)

        if all_y:
            y_min = min(all_y)
            y_max = max(all_y)
            y_pad = 1.0 if y_min == y_max else 0.05 * (y_max - y_min)
            ax.set_ylim(y_min - y_pad, y_max + y_pad)

    def apply_visibility() -> None:
        success_scatter.set_visible(state["trial_scores"])
        failed_scatter.set_visible(state["failed_trials"])
        avg_line.set_visible(state["rolling_avg"])
        best_line.set_visible(state["best_so_far"])
        # No gen_break_lines to update
        ax.legend(loc="lower right", fontsize=10)
        fig.canvas.draw_idle()

    def refresh_plot(updated_records: list[dict]) -> None:
        nonlocal records
        records = updated_records
        updated = compute_plot_data(records)

        set_offsets(success_scatter, updated["success_xs"], updated["success_ys"])
        set_offsets(failed_scatter, updated["failed_xs"], updated["failed_ys"])
        avg_line.set_data(updated["avg_x"], updated["avg_y"])
        best_line.set_data(updated["best_x"], updated["best_y"])

        refit_axes(updated)
        apply_visibility()

    btn_colors = {True: "#a0a0a0", False: "#d7d7d7"}

    def style_button(button: Button, enabled: bool) -> None:
        button.color = btn_colors[enabled]
        button.hovercolor = "#bdbdbd"
        button.ax.set_facecolor(btn_colors[enabled])

    live_ax = fig.add_axes([0.02, 0.11, 0.09, 0.06])
    panel_ax = fig.add_axes([0.12, 0.11, 0.13, 0.06])
    trial_ax = fig.add_axes([0.02, 0.03, 0.11, 0.06])
    failed_ax = fig.add_axes([0.14, 0.03, 0.11, 0.06])
    avg_ax = fig.add_axes([0.26, 0.03, 0.11, 0.06])
    best_ax = fig.add_axes([0.38, 0.03, 0.11, 0.06])
    breaks_ax = fig.add_axes([0.50, 0.03, 0.11, 0.06])

    btn_live = Button(live_ax, "Live: OFF")
    btn_panel = Button(panel_ax, "Hide Controls")
    btn_trial = Button(trial_ax, "Trial")
    btn_failed = Button(failed_ax, "Failed")
    btn_avg = Button(avg_ax, "Avg")
    btn_best = Button(best_ax, "Best")
    btn_breaks = Button(breaks_ax, "Breaks")

    style_button(btn_live, state["live"])
    style_button(btn_trial, state["trial_scores"])
    style_button(btn_failed, state["failed_trials"])
    style_button(btn_avg, state["rolling_avg"])
    style_button(btn_best, state["best_so_far"])
    style_button(btn_breaks, state["gen_breaks"])
    style_button(btn_panel, True)

    refresh_timer = fig.canvas.new_timer(interval=int(LIVE_REFRESH_SECONDS * 1000))

    def on_timer() -> None:
        try:
            updated_records = load_all_trials()
            if updated_records:
                refresh_plot(updated_records)
        except Exception as exc:
            print(f"[warn] Live refresh failed: {exc}")

    refresh_timer.add_callback(on_timer)

    def toggle_live(_event) -> None:
        state["live"] = not state["live"]
        if state["live"]:
            refresh_timer.start()
            btn_live.label.set_text("Live: ON")
        else:
            refresh_timer.stop()
            btn_live.label.set_text("Live: OFF")
        style_button(btn_live, state["live"])
        fig.canvas.draw_idle()

    def toggle_trial(_event) -> None:
        state["trial_scores"] = not state["trial_scores"]
        style_button(btn_trial, state["trial_scores"])
        apply_visibility()

    def toggle_failed(_event) -> None:
        state["failed_trials"] = not state["failed_trials"]
        style_button(btn_failed, state["failed_trials"])
        apply_visibility()

    def toggle_avg(_event) -> None:
        state["rolling_avg"] = not state["rolling_avg"]
        style_button(btn_avg, state["rolling_avg"])
        apply_visibility()

    def toggle_best(_event) -> None:
        state["best_so_far"] = not state["best_so_far"]
        style_button(btn_best, state["best_so_far"])
        apply_visibility()

    def toggle_breaks(_event) -> None:
        state["gen_breaks"] = not state["gen_breaks"]
        style_button(btn_breaks, state["gen_breaks"])
        apply_visibility()

    panel_axes = [live_ax, trial_ax, failed_ax, avg_ax, best_ax, breaks_ax]

    def toggle_controls_panel(_event) -> None:
        state["controls_visible"] = not state["controls_visible"]
        for panel in panel_axes:
            panel.set_visible(state["controls_visible"])
        btn_panel.label.set_text(
            "Hide Controls" if state["controls_visible"] else "Show Controls"
        )
        fig.canvas.draw_idle()

    btn_live.on_clicked(toggle_live)
    btn_trial.on_clicked(toggle_trial)
    btn_failed.on_clicked(toggle_failed)
    btn_avg.on_clicked(toggle_avg)
    btn_best.on_clicked(toggle_best)
    btn_breaks.on_clicked(toggle_breaks)
    btn_panel.on_clicked(toggle_controls_panel)

    def on_close(_event) -> None:
        refresh_timer.stop()

    fig.canvas.mpl_connect("close_event", on_close)

    refit_axes(plot_data)
    apply_visibility()
    plt.show()
