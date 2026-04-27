"""
analyze_plotting.py — Matplotlib visualization and interactive plots.

Creates performance plots with per-test contribution bars (diverging stacked),
rolling averages, and per-generation trends.
"""

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import matplotlib.patches as mpatches
from matplotlib.widgets import Button
import numpy as np

from analyze_config import CENTERED_AVG_HALF_WINDOW, LIVE_REFRESH_SECONDS
from analyze_io import load_all_trials

# ---------------------------------------------------------------------------
# Colour palette — matches UI.py SLICE_COLORS
# ---------------------------------------------------------------------------
TEST_COLORS = [
    "#404867",  # (matches C_BANNER in UI.py)
    "#6b7aad",
    "#9aa3cc",
    "#2c3e6b",
    "#c0392b",
    "#2ecc71",
    "#e67e22",
    "#9b59b6",
]

NEG_ALPHA = 0.40  # alpha for negative-contribution segments
NEG_HATCH = "////"  # hatch for negative segments

C_BANNER = "#404867"
C_BG = "#ffffff"
C_SECTION = "#fafbfc"
C_BORDER = "#d0d3d8"
C_FINAL = "#c0392b"  # final-score tick colour
C_AVG = "#2ecc71"  # rolling average line
C_BEST = "#e74c3c"  # best-so-far line


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_all_test_names(records: list[dict]) -> list[str]:
    """Return a stable ordered list of every unique test name seen across all records."""
    seen: list[str] = []
    for r in records:
        for name in (r.get("test_scores") or {}).keys():
            if name not in seen:
                seen.append(name)
    return seen


def _test_color(test_name: str, name_order: list[str]) -> str:
    """Return the hex color assigned to a test, consistent across the whole plot."""
    try:
        idx = name_order.index(test_name)
    except ValueError:
        idx = abs(hash(test_name)) % len(TEST_COLORS)
    return TEST_COLORS[idx % len(TEST_COLORS)]


def _compute_contributions(record: dict) -> dict[str, float]:
    """Compute per-test weighted contribution for one trial record.

    contribution_i = normalize(aggregate_score_i) * weight_pct_i

    Falls back gracefully when test_scores is absent (legacy records).
    """
    test_scores: dict = record.get("test_scores") or {}

    if not test_scores:
        return {"score": float(record.get("final_score", record.get("score", 0.0)))}

    contributions: dict[str, float] = {}
    for test_name, test_info in test_scores.items():
        if not isinstance(test_info, dict):
            continue
        agg = float(test_info.get("aggregate_score", 0.0) or 0.0)
        raw_max = test_info.get("max_score")
        # Treat missing/None as legacy (score already normalised); 0.0 means unknown.
        max_score = float(raw_max) if raw_max is not None else 1.0
        wpct = float(test_info.get("weight_pct", 0.0) or 0.0)
        norm = min(agg / max_score, 1.0) if max_score > 0 else 0.0
        contributions[test_name] = norm * wpct

    return (
        contributions
        if contributions
        else {"score": float(record.get("final_score", record.get("score", 0.0)))}
    )


# ---------------------------------------------------------------------------
# Plot-data builder
# ---------------------------------------------------------------------------


def compute_plot_data(records: list[dict], all_test_names: list[str]) -> dict:
    """Pre-compute all series needed for a full plot redraw.

    Args:
        records: Trial records from analyze_io.load_all_trials().
        all_test_names: Ordered unique test names (from _collect_all_test_names).

    Returns:
        dict with keys: xs, final_scores, failed_mask, is_complete, contributions,
        avg_x, avg_y, best_x, best_y, gen_tick_positions, gen_tick_labels.
    """
    xs = [r["chron"] for r in records]
    contributions = [_compute_contributions(r) for r in records]
    final_scores = [sum(c.values()) for c in contributions]
    failed_mask = [bool(r.get("failed", False)) for r in records]
    is_complete = [bool(r.get("is_complete", True)) for r in records]
    contributions = [_compute_contributions(r) for r in records]

    # Centred rolling average
    avg_x, avg_y = [], []
    for i, r in enumerate(records):
        lo = max(0, i - CENTERED_AVG_HALF_WINDOW)
        hi = min(len(records) - 1, i + CENTERED_AVG_HALF_WINDOW)
        window = records[lo : hi + 1]
        scores = [sum(_compute_contributions(w).values()) for w in window]
        avg_x.append(r["chron"])
        avg_y.append(sum(scores) / len(scores))

    # Best-so-far
    best_x, best_y = [], []
    running_best = None
    for i, r in enumerate(records):
        if not failed_mask[i]:
            fs = final_scores[i]
            if running_best is None or fs > running_best:
                running_best = fs
        if running_best is not None:
            best_x.append(r["chron"])
            best_y.append(running_best)

    # Generation tick marks (one per unique generation boundary)
    gen_tick_positions, gen_tick_labels = [], []
    prev_gen = None
    for r in records:
        if r["gen_index"] != prev_gen:
            gen_tick_positions.append(r["chron"])
            gen_tick_labels.append(str(r["gen_index"]))
        prev_gen = r["gen_index"]

    return {
        "xs": xs,
        "final_scores": final_scores,
        "failed_mask": failed_mask,
        "is_complete": is_complete,
        "contributions": contributions,
        "avg_x": avg_x,
        "avg_y": avg_y,
        "best_x": best_x,
        "best_y": best_y,
        "gen_tick_positions": gen_tick_positions,
        "gen_tick_labels": gen_tick_labels,
    }


# ---------------------------------------------------------------------------
# Bar rendering
# ---------------------------------------------------------------------------


def _draw_bars(
    ax,
    plot_data: dict,
    all_test_names: list[str],
    bar_width: float,
    show_failed: bool = True,
) -> None:
    """Draw diverging stacked contribution bars on ax.

    Positive contributions stack upward, negatives stack downward. Failed
    trials render at reduced opacity; incomplete trials at lower opacity.
    """
    xs = plot_data["xs"]
    contributions = plot_data["contributions"]
    failed_mask = plot_data["failed_mask"]
    is_complete = plot_data["is_complete"]

    tick_w = bar_width * 1

    for i, (x, contrib, failed, complete) in enumerate(
        zip(xs, contributions, failed_mask, is_complete)
    ):
        if failed and not show_failed:
            continue

        base_alpha = 0.30 if failed else 1.0
        pos_bottom = 0.0
        neg_bottom = 0.0
        incomplete_alpha = 0.5 if not complete else 1.0

        for test_name in all_test_names:
            val = contrib.get(test_name, 0.0)
            if val == 0.0:
                continue

            color = _test_color(test_name, all_test_names)

            if val > 0:
                ax.bar(
                    x,
                    val,
                    bottom=pos_bottom,
                    width=bar_width,
                    color=color,
                    alpha=0.85 * base_alpha * incomplete_alpha,
                    linewidth=0.5,
                    edgecolor=color,
                    zorder=2,
                )
                pos_bottom += val
            else:
                ax.bar(
                    x,
                    val,
                    bottom=neg_bottom,
                    width=bar_width,
                    color=color,
                    alpha=0.85 * base_alpha * incomplete_alpha,
                    linewidth=0.5,
                    edgecolor=color,
                    zorder=2,
                )
                neg_bottom += val

        net_score = pos_bottom + neg_bottom
        line_style = "--" if not complete else "-"
        ax.plot(
            [x - tick_w / 2, x + tick_w / 2],
            [net_score, net_score],
            color=C_FINAL,
            linewidth=2.0 if not failed else 1.0,
            linestyle=line_style,
            alpha=base_alpha * incomplete_alpha,
            solid_capstyle="round",
            zorder=4,
        )


# ---------------------------------------------------------------------------
# Legend builder
# ---------------------------------------------------------------------------


def _build_legend(ax, all_test_names: list[str]) -> None:
    """Attach a legend to ax covering per-test colors and overlay lines."""
    handles = []
    for name in all_test_names:
        color = _test_color(name, all_test_names)
        handles.append(mpatches.Patch(facecolor=color, alpha=0.85, label=f"{name}"))
    handles.append(
        plt.Line2D([0], [0], color=C_FINAL, linewidth=2, label="Final score")
    )
    handles.append(
        plt.Line2D(
            [0],
            [0],
            color=C_AVG,
            linestyle="--",
            linewidth=2,
            label=f"Rolling avg (±{CENTERED_AVG_HALF_WINDOW})",
        )
    )
    handles.append(
        plt.Line2D(
            [0], [0], color=C_BEST, linestyle="-", linewidth=2, label="Best so far"
        )
    )
    handles.append(
        mpatches.Patch(
            facecolor="#cccccc",
            alpha=0.6,
            hatch="////",
            edgecolor="#666666",
            label="Incomplete (running)",
        )
    )
    ax.legend(handles=handles, loc="lower right", fontsize=9, framealpha=0.9, ncol=2)


# ---------------------------------------------------------------------------
# X-axis tick helper — avoids black-bar overload at many generations
# ---------------------------------------------------------------------------


def _set_gen_ticks(ax, positions: list, labels: list, max_ticks: int = 12) -> None:
    """Set X-axis ticks to generation boundaries, thinning when there are many generations."""
    n = len(positions)
    if n == 0:
        return
    if n <= max_ticks:
        ax.set_xticks(positions)
        ax.set_xticklabels(labels, rotation=0, fontsize=10)
    else:
        step = max(1, (n + max_ticks - 1) // max_ticks)
        ax.set_xticks(positions[::step])
        ax.set_xticklabels(labels[::step], rotation=0, fontsize=10)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def plot_combined(records: list[dict], summaries: list[dict]) -> None:
    """Plot per-test contribution bars, rolling average, and best-so-far.

    Args:
        records: Trial records from analyze_io.load_all_trials.
        summaries: Generation summary records (unused; kept for API symmetry).
    """
    if not records:
        print("[warn] No trial data to plot.")
        return

    _ = summaries

    all_test_names = _collect_all_test_names(records)

    def _compute_bar_width(recs: list[dict]) -> float:
        n = len(recs)
        xs_range = max(r["chron"] for r in recs) - min(r["chron"] for r in recs) + 1
        return max(0.4, xs_range / n * 0.8)

    bar_width = _compute_bar_width(records)
    plot_data = compute_plot_data(records, all_test_names)

    fig, ax = plt.subplots(figsize=(14, 8))
    fig.patch.set_facecolor(C_BG)
    ax.set_facecolor(C_SECTION)
    fig.subplots_adjust(bottom=0.14)

    # ── State ──────────────────────────────────────────────────────────────
    state = {
        "live": False,
        "show_failed": True,
        "rolling_avg": True,
        "best_so_far": True,
    }

    # ── Redraw helper ──────────────────────────────────────────────────────
    def full_redraw(updated_records: list[dict]) -> None:
        nonlocal records, plot_data, bar_width

        records = updated_records

        # Refresh test names in-place so all closures stay consistent
        new_names = _collect_all_test_names(records)
        all_test_names.clear()
        all_test_names.extend(new_names)

        if records:
            bar_width = _compute_bar_width(records)

        plot_data = compute_plot_data(records, all_test_names)

        ax.cla()
        ax.set_facecolor(C_SECTION)

        _draw_bars(
            ax, plot_data, all_test_names, bar_width, show_failed=state["show_failed"]
        )
        ax.axhline(0, color=C_BORDER, linewidth=1.0, zorder=1)

        avg_x, avg_y = plot_data["avg_x"], plot_data["avg_y"]
        best_x, best_y = plot_data["best_x"], plot_data["best_y"]

        if state["rolling_avg"] and avg_x:
            ax.plot(
                avg_x,
                avg_y,
                color=C_AVG,
                linestyle="--",
                linewidth=2,
                alpha=0.85,
                zorder=5,
            )
        if state["best_so_far"] and best_x:
            ax.plot(
                best_x,
                best_y,
                color=C_BEST,
                linestyle="-",
                linewidth=2,
                alpha=0.85,
                zorder=5,
            )

        ax.set_xlabel("Generation", fontsize=12, fontweight="bold")
        _set_gen_ticks(
            ax,
            plot_data["gen_tick_positions"],
            plot_data["gen_tick_labels"],
        )
        ax.set_ylabel("Score contribution", fontsize=12, fontweight="bold")
        ax.set_title(
            "Gripper Optimization — Per-Test Contributions",
            fontsize=14,
            fontweight="bold",
            color=C_BANNER,
        )
        ax.grid(axis="y", which="both", alpha=0.25, linestyle="--")
        ax.yaxis.set_major_locator(ticker.MaxNLocator(nbins=10))
        for spine in ax.spines.values():
            spine.set_edgecolor(C_BORDER)

        _build_legend(ax, all_test_names)
        _refit_axes()
        fig.canvas.draw_idle()

    def _refit_axes() -> None:
        all_ys = list(plot_data["final_scores"])
        for contrib in plot_data["contributions"]:
            pos = sum(v for v in contrib.values() if v > 0)
            neg = sum(v for v in contrib.values() if v < 0)
            all_ys.extend([pos, neg])
        if plot_data["avg_y"]:
            all_ys.extend(plot_data["avg_y"])
        if plot_data["best_y"]:
            all_ys.extend(plot_data["best_y"])
        if not all_ys:
            return
        y_min, y_max = min(all_ys), max(all_ys)
        pad = max(1.0, abs(y_max - y_min) * 0.08)
        ax.set_ylim(y_min - pad, y_max + pad)

        xs = plot_data["xs"]
        if xs:
            x_pad = max(1.0, (max(xs) - min(xs)) * 0.02)
            ax.set_xlim(min(xs) - x_pad, max(xs) + x_pad)

    # ── Buttons — single row ───────────────────────────────────────────────
    btn_colors = {True: "#a0a0a0", False: "#d7d7d7"}

    def style_btn(btn, on: bool) -> None:
        btn.color = btn_colors[on]
        btn.hovercolor = "#bdbdbd"
        btn.ax.set_facecolor(btn_colors[on])

    live_ax   = fig.add_axes([0.02, 0.04, 0.10, 0.06])
    failed_ax = fig.add_axes([0.13, 0.04, 0.10, 0.06])
    avg_ax    = fig.add_axes([0.24, 0.04, 0.10, 0.06])
    best_ax   = fig.add_axes([0.35, 0.04, 0.10, 0.06])

    btn_live   = Button(live_ax,   "Live: OFF")
    btn_failed = Button(failed_ax, "Failed")
    btn_avg    = Button(avg_ax,    "Avg")
    btn_best   = Button(best_ax,   "Best")

    style_btn(btn_live,   state["live"])
    style_btn(btn_failed, state["show_failed"])
    style_btn(btn_avg,    state["rolling_avg"])
    style_btn(btn_best,   state["best_so_far"])

    refresh_timer = fig.canvas.new_timer(interval=int(LIVE_REFRESH_SECONDS * 1000))

    def on_timer() -> None:
        try:
            updated = load_all_trials()
            full_redraw(updated if updated else records)
        except Exception as exc:
            print(f"[warn] Live refresh failed: {exc}")

    refresh_timer.add_callback(on_timer)

    def toggle_live(_e) -> None:
        state["live"] = not state["live"]
        if state["live"]:
            refresh_timer.start()
            btn_live.label.set_text("Live: ON")
        else:
            refresh_timer.stop()
            btn_live.label.set_text("Live: OFF")
        style_btn(btn_live, state["live"])
        fig.canvas.draw_idle()

    def toggle_failed(_e) -> None:
        state["show_failed"] = not state["show_failed"]
        style_btn(btn_failed, state["show_failed"])
        full_redraw(records)

    def toggle_avg(_e) -> None:
        state["rolling_avg"] = not state["rolling_avg"]
        style_btn(btn_avg, state["rolling_avg"])
        full_redraw(records)

    def toggle_best(_e) -> None:
        state["best_so_far"] = not state["best_so_far"]
        style_btn(btn_best, state["best_so_far"])
        full_redraw(records)

    btn_live.on_clicked(toggle_live)
    btn_failed.on_clicked(toggle_failed)
    btn_avg.on_clicked(toggle_avg)
    btn_best.on_clicked(toggle_best)

    def on_close(_e) -> None:
        refresh_timer.stop()

    fig.canvas.mpl_connect("close_event", on_close)

    full_redraw(records)
    plt.show()
