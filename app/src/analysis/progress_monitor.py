"""
Progress Monitor - Live Tkinter dashboard for optimization status.

Shows global progress, current generation progress, and per-trial run status
in a grid layout (TRIALS_PER_ROW trials per row).
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk


# ─────────────────────────────────────────────
# Paths / constants
# ─────────────────────────────────────────────
LAB_ROOT = Path(__file__).resolve().parents[3]
TRIALS_DIR = LAB_ROOT / "runtime" / "trials"
LABTESTS_DIR = LAB_ROOT / "app" / "src" / "labtests"
PROGRESS_FILE = TRIALS_DIR / "progress.json"
POLL_MS = 300
DEFAULT_TRIALS_PER_GEN = 4
DEFAULT_RUNS_PER_TRIAL = 1
TRIALS_PER_ROW = 5
RUN_BAR_HEIGHT = 16
LABEL_MAX_CHARS = 10


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_short_labels() -> dict[str, str]:
    """Read short_label from each test's test.json; fall back to the folder name."""
    labels: dict[str, str] = {}
    if not LABTESTS_DIR.is_dir():
        return labels
    for test_dir in LABTESTS_DIR.iterdir():
        if not test_dir.is_dir() or test_dir.name.startswith("_"):
            continue
        meta = _read_json(test_dir / "test.json")
        short = (meta or {}).get("short_label") or test_dir.name
        labels[test_dir.name] = str(short)
    return labels


def _make_run_label(
    test_name: str,
    test_run_index: object,
    test_run_total: object,
    short_labels: dict[str, str],
    max_chars: int = LABEL_MAX_CHARS,
) -> str:
    """Build a compact run label using the test's short_label."""
    short_name = short_labels.get(test_name, test_name)
    if len(short_name) <= max_chars:
        return short_name
    # Preserve trailing index when truncating
    parts = short_name.rsplit(" ", 1)
    if len(parts) == 2:
        name_part, idx_part = parts
        available = max_chars - 1 - len(idx_part)
        return f"{name_part[:max(1, available)]} {idx_part}"
    return short_name[:max_chars]


# ─────────────────────────────────────────────
# UI
# ─────────────────────────────────────────────


class MonitorApp:
    """Tkinter live monitor — trial grid layout, score-based bars."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("ShapeOPT Live Monitor")
        self.root.geometry("1400x840")
        self.root.configure(bg="white")

        self.run_widgets: dict[str, dict[str, object]] = {}
        self.trial_widgets: dict[int, dict[str, object]] = {}
        self.slot_state_cache: dict[str, dict] = {}
        self.last_progress: dict | None = None
        self.last_gen_current = 0
        self.layout_signature: tuple[int, int] | None = None
        self.trials_per_gen = DEFAULT_TRIALS_PER_GEN
        self.runs_per_trial = DEFAULT_RUNS_PER_TRIAL
        self._runs_wheel_bound = False
        self._short_labels: dict[str, str] = _load_short_labels()

        # ── Header ──
        top = ttk.Frame(root, padding=(12, 8, 12, 4))
        top.pack(fill="x")

        self.header = ttk.Label(
            top, text="Waiting for optimizer...", font=("Segoe UI", 12, "bold")
        )
        self.header.pack(anchor="w", pady=(0, 2))

        stat_row = ttk.Frame(top)
        stat_row.pack(fill="x")
        self.global_info = ttk.Label(stat_row, text="Global: --")
        self.global_info.pack(side="left")
        self.eta_info = ttk.Label(
            stat_row, text="  |  elapsed --  remaining --  ETA --", foreground="#555"
        )
        self.eta_info.pack(side="left")

        self.tests_info = ttk.Label(top, text="Tests: --", foreground="#555")
        self.tests_info.pack(anchor="w")

        self.global_bar = ttk.Progressbar(
            top,
            orient="horizontal",
            mode="determinate",
            maximum=100,
            style="GlobalGreen.Horizontal.TProgressbar",
        )
        self.global_bar.pack(fill="x", pady=(2, 2))

        self.gen_info = ttk.Label(top, text="Generation: --", foreground="#555")
        self.gen_info.pack(anchor="w")

        self.gen_bar = ttk.Progressbar(
            top,
            orient="horizontal",
            mode="determinate",
            maximum=100,
            style="GenGreen.Horizontal.TProgressbar",
        )
        self.gen_bar.pack(fill="x", pady=(2, 6))

        ttk.Separator(root, orient="horizontal").pack(fill="x", padx=12, pady=4)

        # ── Trials grid ──
        body = ttk.Frame(root, padding=(12, 4, 12, 12))
        body.pack(fill="both", expand=True)

        runs_container = ttk.Frame(body)
        runs_container.pack(fill="both", expand=True)

        self.runs_canvas = tk.Canvas(runs_container, bg="white", highlightthickness=0)
        scrollbar = ttk.Scrollbar(
            runs_container, orient="vertical", command=self.runs_canvas.yview
        )
        self.runs_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.runs_canvas.pack(side="left", fill="both", expand=True)

        self.runs_inner = ttk.Frame(self.runs_canvas)
        self.runs_inner_id = self.runs_canvas.create_window(
            (0, 0), window=self.runs_inner, anchor="nw"
        )
        self.runs_inner.bind("<Configure>", self._on_inner_configure)
        self.runs_canvas.bind("<Configure>", self._on_canvas_configure)
        for widget in (runs_container, self.runs_canvas, self.runs_inner):
            widget.bind("<Enter>", self._bind_runs_mousewheel)
            widget.bind("<Leave>", self._unbind_runs_mousewheel)

        self._build_trial_sections()
        self._tick()

    # ── Layout ──────────────────────────────────

    def _build_trial_sections(self) -> None:
        """Rebuild the trial grid from scratch."""
        for child in self.runs_inner.winfo_children():
            child.destroy()
        self.run_widgets.clear()
        self.trial_widgets.clear()
        self.slot_state_cache.clear()

        for col in range(TRIALS_PER_ROW):
            self.runs_inner.columnconfigure(col, weight=1, uniform="trial_col")

        for trial in range(1, self.trials_per_gen + 1):
            row_idx = (trial - 1) // TRIALS_PER_ROW
            col_idx = (trial - 1) % TRIALS_PER_ROW

            card = ttk.Labelframe(self.runs_inner, text=f"Trial {trial:02d}", padding=6)
            card.grid(row=row_idx, column=col_idx, sticky="nsew", padx=4, pady=4)
            card.columnconfigure(1, weight=1)

            summary = ttk.Label(
                card,
                text="Score: --",
                foreground="#333",
                font=("Segoe UI", 9, "bold"),
                wraplength=200,
            )
            summary.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 4))

            self.trial_widgets[trial] = {"card": card, "summary": summary}

            for run in range(1, self.runs_per_trial + 1):
                key = f"t{trial}_r{run}"

                name_lbl = ttk.Label(card, width=LABEL_MAX_CHARS, anchor="w")
                name_lbl.grid(row=run, column=0, sticky="w", padx=(0, 3))

                bar = tk.Canvas(
                    card,
                    height=RUN_BAR_HEIGHT,
                    width=60,
                    bg="#eef1f4",
                    highlightthickness=1,
                    highlightbackground="#c6ccd3",
                    bd=0,
                )
                bar.grid(row=run, column=1, sticky="ew", pady=2)
                fill_id = bar.create_rectangle(
                    0, 0, 0, RUN_BAR_HEIGHT, fill="#5a6370", width=0
                )

                score_lbl = ttk.Label(card, width=10, anchor="e")
                score_lbl.grid(row=run, column=2, sticky="e", padx=(3, 0))

                self.run_widgets[key] = {
                    "name_lbl": name_lbl,
                    "bar": bar,
                    "fill_id": fill_id,
                    "score_lbl": score_lbl,
                }

    def _sync_layout(self, progress: dict | None) -> None:
        """Rebuild grid if trials-per-gen or runs-per-trial changed."""
        trials_per_gen = self.trials_per_gen
        runs_per_trial = self.runs_per_trial
        if isinstance(progress, dict):
            rt = progress.get("trials_per_gen")
            rr = progress.get("runs_per_trial")
            if isinstance(rt, int) and rt > 0:
                trials_per_gen = rt
            if isinstance(rr, int) and rr > 0:
                runs_per_trial = rr
        sig = (trials_per_gen, runs_per_trial)
        if sig != self.layout_signature:
            self.layout_signature = sig
            self.trials_per_gen = trials_per_gen
            self.runs_per_trial = runs_per_trial
            self._build_trial_sections()

    # ── Scroll ──────────────────────────────────

    def _on_inner_configure(self, event) -> None:
        self.runs_canvas.configure(scrollregion=self.runs_canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        self.runs_canvas.itemconfigure(self.runs_inner_id, width=event.width)

    def _bind_runs_mousewheel(self, event=None) -> None:
        if self._runs_wheel_bound:
            return
        self._runs_wheel_bound = True
        self.root.bind_all("<MouseWheel>", self._on_runs_mousewheel, add="+")
        self.root.bind_all("<Button-4>", self._on_runs_mousewheel, add="+")
        self.root.bind_all("<Button-5>", self._on_runs_mousewheel, add="+")

    def _unbind_runs_mousewheel(self, event=None) -> None:
        if not self._runs_wheel_bound:
            return
        self._runs_wheel_bound = False
        self.root.unbind_all("<MouseWheel>")
        self.root.unbind_all("<Button-4>")
        self.root.unbind_all("<Button-5>")

    def _on_runs_mousewheel(self, event) -> str:
        delta = -1 if (event.num == 4 or event.delta > 0) else 1
        self.runs_canvas.yview_scroll(delta, "units")
        return "break"

    # ── Top panel ───────────────────────────────

    def _update_top(self, progress: dict | None) -> None:
        if not progress:
            self.header.configure(text="Waiting for optimizer...")
            self.global_info.configure(text="Global: --")
            self.eta_info.configure(text="  |  elapsed --  remaining --  ETA --")
            self.gen_info.configure(text="Generation: --")
            self.tests_info.configure(text="Tests: --")
            self.global_bar["value"] = 0
            self.gen_bar["value"] = 0
            return

        self.last_progress = progress

        gen_current = progress.get("gen_current", 0)
        gen_total = progress.get("gen_total", 0)
        trial_current = float(progress.get("trial_current", 0))
        trial_total = float(progress.get("trial_total", 0))
        global_pct = float(progress.get("pct", 0.0))

        trials_per_gen = trial_total / gen_total if gen_total else 0
        completed_this_gen = max(
            0.0, trial_current - (gen_current - 1) * trials_per_gen
        )
        gen_pct = (
            100.0 * min(1.0, completed_this_gen / trials_per_gen)
            if trials_per_gen
            else 0.0
        )

        best = progress.get("best_score")
        avg = progress.get("avg_score")
        best_str = f"{best:.2f}" if isinstance(best, (int, float)) else "--"
        avg_str = f"{avg:.2f}" if isinstance(avg, (int, float)) else "--"

        test_weights: dict = progress.get("test_weights") or {}
        run_plan = progress.get("run_plan") or []
        if run_plan:
            seen: dict[str, int] = {}
            for item in run_plan:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("test_name") or "--")
                count = item.get("test_run_total", 1)
                if name not in seen and isinstance(count, int):
                    seen[name] = count
            parts = []
            for name, count in seen.items():
                w = test_weights.get(name)
                parts.append(
                    f"{name} ×{count}"
                    + (f" w={w}%" if isinstance(w, (int, float)) else "")
                )
            tests_text = ", ".join(parts)
        else:
            names = progress.get("test_names") or []
            parts = []
            for name in names:
                w = test_weights.get(name)
                parts.append(name + (f" w={w}%" if isinstance(w, (int, float)) else ""))
            tests_text = ", ".join(parts) if parts else "--"

        self.header.configure(
            text=f"Generation {gen_current}/{gen_total}  —  best={best_str}  avg={avg_str}"
        )
        self.global_info.configure(
            text=f"Global: {trial_current:.0f}/{trial_total:.0f} trials ({global_pct:.1f}%)"
        )
        self.gen_info.configure(text=f"This gen: {gen_pct:.1f}%")
        self.tests_info.configure(text=f"Tests: {tests_text}")

        started_at = float(progress.get("started_at") or 0.0)
        now = time.time()
        elapsed = max(0.0, now - started_at) if started_at > 0 else 0.0

        if global_pct > 0.01 and elapsed > 0:
            remaining = max(0.0, elapsed / (global_pct / 100.0) - elapsed)
            eta_str = datetime.fromtimestamp(now + remaining).strftime("%H:%M:%S")
            self.eta_info.configure(
                text=(
                    f"  |  elapsed {self._fmt_duration(elapsed)}"
                    f"  remaining {self._fmt_duration(remaining)}  ETA {eta_str}"
                )
            )
        else:
            self.eta_info.configure(
                text=f"  |  elapsed {self._fmt_duration(elapsed)}  remaining --  ETA --"
            )

        self.global_bar["value"] = global_pct
        self.gen_bar["value"] = gen_pct

    # ── Trial grid ──────────────────────────────

    def _update_runs(self, progress: dict | None) -> None:
        if isinstance(progress, dict):
            current_gen = int(progress.get("gen_current", self.last_gen_current) or 0)
            if current_gen > 0:
                self.last_gen_current = current_gen
        else:
            current_gen = self.last_gen_current

        self._sync_layout(progress)

        test_weights: dict = {}
        if isinstance(progress, dict):
            tw = progress.get("test_weights")
            if isinstance(tw, dict):
                test_weights = tw

        # Read all trial states for the current generation
        trial_states: dict[int, dict] = {}
        for t in range(1, self.trials_per_gen + 1):
            ts = _read_json(
                TRIALS_DIR
                / f"gen_{current_gen:04d}"
                / f"trial_{t:02d}"
                / "trial_state.json"
            )
            if isinstance(ts, dict):
                trial_states[t] = ts

        # Build run lookup from trial states
        status_lookup: dict[tuple[int, int], dict] = {}
        for trial, ts in trial_states.items():
            for run_data in ts.get("runs") or []:
                if isinstance(run_data, dict):
                    run_idx = int(run_data.get("run", 0))
                    if run_idx > 0:
                        status_lookup[(trial, run_idx)] = run_data

        terminal_states = {"done", "failed", "skipped", "error", "cancelled"}
        trial_slot_states: dict[int, list[str]] = {
            t: [] for t in range(1, self.trials_per_gen + 1)
        }
        trial_test_scores: dict[int, dict[str, list[float | None]]] = {
            t: {} for t in range(1, self.trials_per_gen + 1)
        }

        for trial in range(1, self.trials_per_gen + 1):
            ts = trial_states.get(trial, {})
            test_max_scores: dict[str, float] = ts.get("test_max_scores") or {}

            for run in range(1, self.runs_per_trial + 1):
                key = f"t{trial}_r{run}"
                if key not in self.run_widgets:
                    continue

                entry = self.run_widgets[key]
                s = status_lookup.get((trial, run))

                if s is not None:
                    self.slot_state_cache[key] = s
                else:
                    s = self.slot_state_cache.get(
                        key,
                        {
                            "state": "not-started",
                            "test_name": None,
                            "run_label": None,
                            "score": None,
                        },
                    )

                test_name = str(s.get("test_name") or "-")
                test_run_index = s.get("test_run_index")
                test_run_total = s.get("test_run_total")
                state_l = str(s.get("state") or "not-started").lower()

                trial_slot_states[trial].append(state_l)

                raw_score = s.get("score")
                score_value: float | None = (
                    float(raw_score) if isinstance(raw_score, (int, float)) else None
                )
                trial_test_scores[trial].setdefault(test_name, []).append(score_value)

                max_score = test_max_scores.get(test_name)
                cur = int(s.get("current_frame") or 0)
                tot = s.get("total_frames")

                # Bar fill: hold_time/max_score while running (falls back to frame
                # progress), score/max once done, 0% otherwise
                live_hold = s.get("hold_time")
                if state_l in ("launching", "running"):
                    if (
                        isinstance(live_hold, (int, float))
                        and isinstance(max_score, (int, float))
                        and max_score > 0
                    ):
                        pct = max(0.0, min(100.0, 100.0 * live_hold / max_score))
                    else:
                        pct = (
                            max(0.0, min(100.0, 100.0 * cur / tot))
                            if isinstance(tot, int) and tot > 0
                            else 0.0
                        )
                elif (
                    score_value is not None
                    and isinstance(max_score, (int, float))
                    and max_score > 0
                ):
                    pct = max(0.0, min(100.0, 100.0 * score_value / max_score))
                else:
                    pct = 0.0

                # Short label (left of bar)
                short = _make_run_label(
                    test_name, test_run_index, test_run_total, self._short_labels
                )

                # Score text (right of bar)
                if state_l in ("launching", "running") and isinstance(live_hold, (int, float)):
                    if isinstance(max_score, (int, float)):
                        score_str = f"{live_hold:.2f}/{max_score:.1f}"
                    else:
                        score_str = f"{live_hold:.2f}"
                elif score_value is None:
                    score_str = "--"
                elif isinstance(max_score, (int, float)):
                    score_str = f"{score_value:.2f}/{max_score:.1f}"
                else:
                    score_str = f"{score_value:.3f}"

                color = self._color_for_state(state_l)
                entry["name_lbl"].configure(text=short)
                self._set_bar(entry["bar"], entry["fill_id"], pct, color)
                entry["score_lbl"].configure(text=score_str)

        # Trial summaries
        for trial in range(1, self.trials_per_gen + 1):
            widget = self.trial_widgets.get(trial)
            if not widget:
                continue

            ts = trial_states.get(trial, {})
            states = trial_slot_states.get(trial, [])
            all_terminal = bool(states) and all(st in terminal_states for st in states)

            # Final trial score
            final = ts.get("final_score")
            if isinstance(final, (int, float)) and all_terminal:
                score_text = f"{final:.2f}"
            else:
                flat = [
                    sc
                    for scores in trial_test_scores.get(trial, {}).values()
                    for sc in scores
                    if sc is not None and sc not in (float("-inf"), -2.0)
                ]
                if flat:
                    prefix = "" if all_terminal else "~"
                    score_text = f"{prefix}{sum(flat) / len(flat):.2f}"
                else:
                    score_text = "--"

            # Per-test scores from authoritative test_scores block when available
            ts_test_scores: dict = ts.get("test_scores") or {}
            test_max_scores_t: dict = ts.get("test_max_scores") or {}
            bits: list[str] = []

            if ts_test_scores:
                for tname, info in ts_test_scores.items():
                    agg = info.get("aggregate_score")
                    max_s = test_max_scores_t.get(tname)
                    w = info.get("weight_pct") or test_weights.get(tname)
                    if isinstance(agg, (int, float)):
                        sp = (
                            f"{agg:.2f}/{max_s:.1f}"
                            if isinstance(max_s, (int, float))
                            else f"{agg:.2f}"
                        )
                        wp = f"({w:.0f}%)" if isinstance(w, (int, float)) else ""
                        bits.append(f"{tname}={sp}{wp}")
                    else:
                        bits.append(f"{tname}=--")
            else:
                for tname, scores in trial_test_scores.get(trial, {}).items():
                    valid = [sc for sc in scores if sc not in (None, float("-inf"))]
                    max_s = test_max_scores_t.get(tname)
                    w = test_weights.get(tname)
                    if valid:
                        agg = sum(valid) / len(valid)
                        sp = (
                            f"{agg:.2f}/{max_s:.1f}"
                            if isinstance(max_s, (int, float))
                            else f"{agg:.2f}"
                        )
                        wp = f"({w}%)" if isinstance(w, (int, float)) else ""
                        bits.append(f"{tname}={sp}{wp}")
                    else:
                        bits.append(f"{tname}=--")

            text = f"Score: {score_text}"
            if bits:
                text += "\n" + "  ".join(bits)
            widget["summary"].configure(text=text)

        if current_gen <= 0:
            self.header.configure(text="Waiting for optimizer...")

    # ── Tick ────────────────────────────────────

    def _tick(self) -> None:
        progress = _read_json(PROGRESS_FILE)
        self._update_top(progress)
        self._update_runs(progress)
        self.root.after(POLL_MS, self._tick)

    # ── Statics ─────────────────────────────────

    @staticmethod
    def _fmt_duration(seconds: float) -> str:
        s = int(max(0, seconds))
        h, rem = divmod(s, 3600)
        m, sec = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{sec:02d}"

    @staticmethod
    def _color_for_state(state: str) -> str:
        if state in ("launching", "running"):
            return "#0270ff"
        if state in ("failed", "skipped", "error", "cancelled"):
            return "#e03131"
        if state == "done":
            return "#2f9e44"
        return "#868e96"

    @staticmethod
    def _set_bar(canvas: tk.Canvas, fill_id: int, pct: float, color: str) -> None:
        w = max(1, int(canvas.winfo_width() or int(canvas.cget("width"))))
        h = max(1, int(canvas.winfo_height() or int(canvas.cget("height"))))
        fill_w = int(w * max(0.0, min(100.0, pct)) / 100.0)
        canvas.coords(fill_id, 0, 0, fill_w, h)
        canvas.itemconfigure(fill_id, fill=color)


def main() -> None:
    """Launch the Tkinter live monitor window."""
    root = tk.Tk()
    style = ttk.Style(root)
    for theme in ("vista", "xpnative", "default"):
        if theme in style.theme_names():
            style.theme_use(theme)
            break

    style.configure(
        "GlobalGreen.Horizontal.TProgressbar",
        background="#2ea043",
        troughcolor="#e9e9e9",
    )
    style.configure(
        "GenGreen.Horizontal.TProgressbar", background="#2ea043", troughcolor="#e9e9e9"
    )

    MonitorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
