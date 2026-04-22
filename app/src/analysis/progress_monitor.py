"""
Progress Monitor - Live Tkinter dashboard for optimization status.

Shows global progress, current generation progress, and per-run frame status.
"""

from __future__ import annotations

import os
import json
import time
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk


# ─────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────
LAB_ROOT = Path(__file__).resolve().parents[3]
TRIALS_DIR = LAB_ROOT / "runtime" / "trials"
PROGRESS_FILE = TRIALS_DIR / "progress.json"
POLL_MS = 300
DEFAULT_TRIALS_PER_GEN = 4
DEFAULT_RUNS_PER_TRIAL = 1
AUTO_FOCUS_MARGIN_PX = int(os.environ.get("MONITOR_AUTO_FOCUS_MARGIN_PX", "0"))
RUN_BAR_WIDTH = 270


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────


def _read_json(path: Path) -> dict | None:
    """
    Read a JSON file if present.

    Inputs:
        path (Path): JSON file path.

    Returns:
        dict | None: Parsed data or None if unavailable.
    """
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _iter_trial_state_files() -> list[Path]:
    """
    List one trial_state JSON file per trial under trials.

    Inputs:
        None

    Returns:
        list[Path]: trial_state file paths.
    """
    return sorted(TRIALS_DIR.glob("gen_*/trial_*/trial_state.json"))


def _collect_run_statuses() -> list[dict]:
    """Expand trial_state.json files into flat per-run status payloads."""
    statuses: list[dict] = []
    for path in _iter_trial_state_files():
        data = _read_json(path)
        if not isinstance(data, dict):
            continue
        runs = data.get("runs", [])
        if not isinstance(runs, list):
            continue
        base_gen = int(data.get("gen", 0) or 0)
        base_trial = int(data.get("trial", 0) or 0)
        for idx, run in enumerate(runs, start=1):
            if not isinstance(run, dict):
                continue
            row = dict(run)
            row.setdefault("gen", base_gen)
            row.setdefault("trial", base_trial)
            row.setdefault("run", idx)
            statuses.append(row)
    return statuses


def _weighted_trial_score(
    aggregated_test_scores: list[float],
    test_names_in_order: list[str],
    weights: dict[str, int],
) -> float:
    """
    Compute the weighted trial score from per-test aggregate scores.

    Uses integer percentage weights from progress.json (summing to 100).
    Falls back to a plain mean if weights are absent or don't sum to a
    positive value.

    Inputs:
        aggregated_test_scores (list[float]): One aggregate score per test.
        test_names_in_order (list[str]): Test names matching each score.
        weights (dict[str, int]): Per-test weight percentages from progress.json.

    Returns:
        float: Weighted score.
    """
    if not aggregated_test_scores:
        return 0.0

    if not weights or len(test_names_in_order) != len(aggregated_test_scores):
        return sum(aggregated_test_scores) / len(aggregated_test_scores)

    total_weight = sum(weights.get(name, 0) for name in test_names_in_order)
    if total_weight <= 0:
        return sum(aggregated_test_scores) / len(aggregated_test_scores)

    return sum(
        score * weights.get(name, 0) / total_weight
        for score, name in zip(aggregated_test_scores, test_names_in_order)
    )


# ─────────────────────────────────────────────
# UI
# ─────────────────────────────────────────────


class MonitorApp:
    """
    Tkinter live monitor for optimization and run-level status.
    """

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("ShapeOPT Live Monitor")
        self.root.geometry("1040x760")
        self.root.configure(bg="white")

        self.run_widgets: dict[str, dict[str, object]] = {}
        self.trial_widgets: dict[int, dict[str, object]] = {}
        self.slot_state_cache: dict[str, dict] = {}
        self.last_progress: dict | None = None
        self.last_gen_current = 0
        self.layout_signature: tuple[int, int] | None = None
        self.trials_per_gen = DEFAULT_TRIALS_PER_GEN
        self.runs_per_trial = DEFAULT_RUNS_PER_TRIAL
        self.auto_focus_var = tk.BooleanVar(value=True)
        self.last_auto_focus_target: tuple[int, int] | None = None
        self._runs_wheel_bound = False

        top = ttk.Frame(root, padding=12)
        top.pack(fill="x")

        self.header = ttk.Label(
            top, text="Waiting for optimizer...", font=("Segoe UI", 12, "bold")
        )
        self.header.pack(anchor="w", pady=(0, 6))

        self.global_info = ttk.Label(top, text="Global: --")
        self.global_info.pack(anchor="w")

        self.best_info = ttk.Label(top, text="Best score so far: --")
        self.best_info.pack(anchor="w")

        self.eta_info = ttk.Label(top, text="Time: elapsed --   remaining --   ETA --")
        self.eta_info.pack(anchor="w")

        self.global_bar = ttk.Progressbar(
            top,
            orient="horizontal",
            mode="determinate",
            maximum=100,
            style="GlobalGreen.Horizontal.TProgressbar",
        )
        self.global_bar.pack(fill="x", pady=(2, 8))

        self.gen_info = ttk.Label(top, text="Generation: --")
        self.gen_info.pack(anchor="w")

        self.tests_info = ttk.Label(top, text="Tests: --")
        self.tests_info.pack(anchor="w")

        self.gen_bar = ttk.Progressbar(
            top,
            orient="horizontal",
            mode="determinate",
            maximum=100,
            style="GenGreen.Horizontal.TProgressbar",
        )
        self.gen_bar.pack(fill="x", pady=(2, 8))

        sep = ttk.Separator(root, orient="horizontal")
        sep.pack(fill="x", padx=12, pady=6)

        body = ttk.Frame(root, padding=(12, 4, 12, 12))
        body.pack(fill="both", expand=True)

        self.runs_title = ttk.Label(
            body, text="Active runs", font=("Segoe UI", 11, "bold")
        )
        self.runs_title.pack(anchor="w", pady=(0, 6))

        controls = ttk.Frame(body)
        controls.pack(fill="x", pady=(0, 6))

        self.auto_focus_toggle = ttk.Checkbutton(
            controls,
            text="Auto-focus earliest incomplete trial",
            variable=self.auto_focus_var,
        )
        self.auto_focus_toggle.pack(side="left")

        self.jump_button = ttk.Button(
            controls,
            text="Jump now",
            command=self._jump_to_earliest_incomplete,
        )
        self.jump_button.pack(side="left", padx=(10, 0))

        self.runs_container = ttk.Frame(body)
        self.runs_container.pack(fill="both", expand=True)

        self.runs_canvas = tk.Canvas(
            self.runs_container, bg="white", highlightthickness=0
        )
        self.runs_scrollbar = ttk.Scrollbar(
            self.runs_container, orient="vertical", command=self.runs_canvas.yview
        )
        self.runs_canvas.configure(yscrollcommand=self.runs_scrollbar.set)
        self.runs_scrollbar.pack(side="right", fill="y")
        self.runs_canvas.pack(side="left", fill="both", expand=True)

        self.runs_inner = ttk.Frame(self.runs_canvas)
        self.runs_inner_id = self.runs_canvas.create_window(
            (0, 0), window=self.runs_inner, anchor="nw"
        )
        self.runs_inner.bind("<Configure>", self._on_inner_configure)
        self.runs_canvas.bind("<Configure>", self._on_canvas_configure)
        self.runs_container.bind("<Enter>", self._bind_runs_mousewheel)
        self.runs_container.bind("<Leave>", self._unbind_runs_mousewheel)
        self.runs_canvas.bind("<Enter>", self._bind_runs_mousewheel)
        self.runs_canvas.bind("<Leave>", self._unbind_runs_mousewheel)
        self.runs_inner.bind("<Enter>", self._bind_runs_mousewheel)
        self.runs_inner.bind("<Leave>", self._unbind_runs_mousewheel)

        self.empty_label = ttk.Label(self.runs_inner, text="No active runs.")
        self.empty_label.pack_forget()

        self._build_trial_sections()

        self._tick()

    def _build_trial_sections(self) -> None:
        """
        Build a fixed compartment for every trial and run slot in the generation.

        Inputs:
            None

        Returns:
            None
        """
        for child in self.runs_inner.winfo_children():
            child.destroy()

        self.run_widgets.clear()
        self.trial_widgets.clear()
        self.slot_state_cache.clear()

        for trial in range(1, self.trials_per_gen + 1):
            trial_frame = ttk.Labelframe(
                self.runs_inner, text=f"Trial {trial:02d}", padding=10
            )
            trial_frame.pack(fill="x", pady=6)

            trial_summary = ttk.Label(
                trial_frame,
                text="Trial score: --   |   Run scores: --",
                foreground="#444",
            )
            trial_summary.pack(anchor="w", pady=(0, 4))

            self.trial_widgets[trial] = {
                "frame": trial_frame,
                "summary": trial_summary,
            }

            for run in range(1, self.runs_per_trial + 1):
                key = f"t{trial}_r{run}"
                row = ttk.Frame(trial_frame)
                row.pack(fill="x", pady=4)

                label = ttk.Label(row, width=20)
                label.pack(side="left")

                canvas = tk.Canvas(
                    row,
                    height=18,
                    width=RUN_BAR_WIDTH,
                    bg="#eef1f4",
                    highlightthickness=1,
                    highlightbackground="#c6ccd3",
                    bd=0,
                )
                canvas.pack(side="left", fill="x", expand=True, padx=8)
                fill_id = canvas.create_rectangle(0, 0, 0, 18, fill="#5a6370", width=0)

                detail = ttk.Label(row, width=42)
                detail.pack(side="left")

                self.run_widgets[key] = {
                    "label": label,
                    "canvas": canvas,
                    "fill_id": fill_id,
                    "detail": detail,
                }

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
        if event.num == 4:
            delta = -1
        elif event.num == 5:
            delta = 1
        else:
            delta = -1 if event.delta > 0 else 1
        self.runs_canvas.yview_scroll(delta, "units")
        return "break"

    def _sync_layout(self, progress: dict | None) -> None:
        trials_per_gen = self.trials_per_gen
        runs_per_trial = self.runs_per_trial

        if isinstance(progress, dict):
            raw_trials = progress.get("trials_per_gen")
            raw_runs = progress.get("runs_per_trial")
            if isinstance(raw_trials, int) and raw_trials > 0:
                trials_per_gen = raw_trials
            if isinstance(raw_runs, int) and raw_runs > 0:
                runs_per_trial = raw_runs

        signature = (trials_per_gen, runs_per_trial)
        if signature != self.layout_signature:
            self.layout_signature = signature
            self.trials_per_gen = trials_per_gen
            self.runs_per_trial = runs_per_trial
            self._build_trial_sections()

    def _update_top(self, progress: dict | None, statuses: list[dict]) -> None:
        if not progress:
            self.header.configure(text="Waiting for optimizer...")
            self.global_info.configure(text="Global: --")
            self.best_info.configure(text="Best score so far: --")
            self.gen_info.configure(text="Generation: --")
            self.tests_info.configure(text="Tests: --")
            self.eta_info.configure(text="Time: elapsed --   remaining --   ETA --")
            self.global_bar["value"] = 0
            self.gen_bar["value"] = 0
            return

        self.last_progress = progress

        gen_current = progress.get("gen_current", 0)
        gen_total = progress.get("gen_total", 0)
        trial_current = progress.get("trial_current", 0)
        trial_total = progress.get("trial_total", 0)
        global_pct = float(progress.get("pct", 0.0))

        trials_per_gen = (trial_total / gen_total) if gen_total else 0
        completed_trials_this_gen = trial_current - ((gen_current - 1) * trials_per_gen)
        completed_trials_this_gen = max(0.0, completed_trials_this_gen)

        if trials_per_gen > 0:
            gen_pct = 100.0 * min(1.0, completed_trials_this_gen / trials_per_gen)
        else:
            gen_pct = 0.0

        best = progress.get("best_score")
        avg = progress.get("avg_score")
        best_str = f"{best:.2f}" if isinstance(best, (int, float)) else "--"
        avg_str = f"{avg:.2f}" if isinstance(avg, (int, float)) else "--"

        # Show test names with their weights when available.
        test_weights: dict[str, int] = progress.get("test_weights") or {}
        run_plan = progress.get("run_plan", [])
        if isinstance(run_plan, list) and run_plan:
            unique_counts: dict[str, int] = {}
            for item in run_plan:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("test_name", "--") or "--")
                count = item.get("test_run_total", 1)
                if name not in unique_counts and isinstance(count, int):
                    unique_counts[name] = count
            tests_parts = []
            for name, count in unique_counts.items():
                w = test_weights.get(name)
                weight_str = f" w={w}%" if isinstance(w, (int, float)) else ""
                tests_parts.append(f"{name} x{count}{weight_str}")
            tests_text = ", ".join(tests_parts)
        else:
            test_names = progress.get("test_names", [])
            if isinstance(test_names, list) and test_names:
                tests_parts = []
                for name in test_names:
                    w = test_weights.get(name)
                    weight_str = f" w={w}%" if isinstance(w, (int, float)) else ""
                    tests_parts.append(f"{name}{weight_str}")
                tests_text = ", ".join(tests_parts)
            else:
                tests_text = "--"

        self.header.configure(text=f"Generation {gen_current}/{gen_total}")
        self.global_info.configure(
            text=(
                f"Global: {trial_current:.2f}/{trial_total} trials  "
                f"({global_pct:.1f}%)   best={best_str}   avg={avg_str}"
            )
        )
        self.best_info.configure(text=f"Best score so far: {best_str}")
        self.gen_info.configure(text=f"Generation progress: {gen_pct:.1f}%")
        self.tests_info.configure(text=f"Tests: {tests_text}")

        started_at = float(progress.get("started_at", 0.0) or 0.0)
        now = time.time()
        if started_at > 0:
            elapsed = max(0.0, now - started_at)
        else:
            elapsed = 0.0

        if global_pct > 0.01 and elapsed > 0:
            total_est = elapsed / (global_pct / 100.0)
            remaining = max(0.0, total_est - elapsed)
            eta_ts = now + remaining
            eta_str = datetime.fromtimestamp(eta_ts).strftime("%H:%M:%S")
            self.eta_info.configure(
                text=(
                    f"Time: elapsed {self._fmt_duration(elapsed)}   "
                    f"remaining {self._fmt_duration(remaining)}   ETA {eta_str}"
                )
            )
        else:
            self.eta_info.configure(
                text=f"Time: elapsed {self._fmt_duration(elapsed)}   remaining --   ETA --"
            )

        self.global_bar["value"] = global_pct
        self.gen_bar["value"] = gen_pct

    def _update_runs(self, progress: dict | None, statuses: list[dict]) -> None:
        if isinstance(progress, dict):
            current_gen = int(progress.get("gen_current", self.last_gen_current) or 0)
            if current_gen > 0:
                self.last_gen_current = current_gen
        else:
            current_gen = self.last_gen_current

        self._sync_layout(progress)

        # Extract weights from progress.json for use in the trial score display.
        test_weights: dict[str, int] = {}
        if isinstance(progress, dict):
            raw_weights = progress.get("test_weights")
            if isinstance(raw_weights, dict):
                test_weights = raw_weights

        status_lookup = {
            (int(s.get("trial", 0)), int(s.get("run", 0))): s
            for s in statuses
            if int(s.get("gen", 0)) == current_gen
        }

        trial_run_scores: dict[int, list[float | None]] = {
            trial: [] for trial in range(1, self.trials_per_gen + 1)
        }
        trial_test_scores: dict[int, dict[str, list[float | None]]] = {
            trial: {} for trial in range(1, self.trials_per_gen + 1)
        }
        trial_slot_states: dict[int, list[str]] = {
            trial: [] for trial in range(1, self.trials_per_gen + 1)
        }

        for trial in range(1, self.trials_per_gen + 1):
            for run in range(1, self.runs_per_trial + 1):
                key = f"t{trial}_r{run}"
                if key not in self.run_widgets:
                    continue

                entry = self.run_widgets[key]
                s = status_lookup.get((trial, run))

                if s is not None:
                    prev = self.slot_state_cache.get(key, {})
                    merged = dict(prev)
                    merged.update(s)
                    if (
                        merged.get("current_frame") in (None, "")
                        and prev.get("current_frame") is not None
                    ):
                        merged["current_frame"] = prev.get("current_frame")
                    if (
                        merged.get("total_frames") in (None, "")
                        and prev.get("total_frames") is not None
                    ):
                        merged["total_frames"] = prev.get("total_frames")
                    self.slot_state_cache[key] = merged
                    s = merged
                else:
                    s = self.slot_state_cache.get(
                        key,
                        {
                            "gen": current_gen,
                            "trial": trial,
                            "run": run,
                            "state": "not-started",
                            "current_frame": 0,
                            "total_frames": None,
                        },
                    )

                gen = s.get("gen", current_gen)
                test_name = str(s.get("test_name", "-") or "-")
                run_label = str(s.get("run_label", "") or "")
                test_run_index = s.get("test_run_index")
                test_run_total = s.get("test_run_total")
                state = s.get("state", "-")
                cur = s.get("current_frame", 0)
                tot = s.get("total_frames")
                color = self._color_for_run_state(s)
                score_value = self._score_from_status_or_file(
                    s, current_gen, trial, run
                )

                state_l = str(state).lower()
                failed_state = state_l in ("failed", "skipped", "error", "cancelled")
                trial_slot_states[trial].append(state_l)

                trial_run_scores[trial].append(score_value)
                trial_test_scores[trial].setdefault(test_name, []).append(score_value)

                if failed_state:
                    pct = 100.0
                    detail_text = f"{state}  frame {cur}/--  (failed)"
                elif isinstance(tot, int) and tot > 0:
                    pct = max(0.0, min(100.0, 100.0 * cur / tot))
                    detail_text = f"{state}  frame {cur}/{tot}  ({pct:.1f}%)"
                else:
                    pct = 0.0
                    detail_text = f"{state}  frame {cur}/--"

                if score_value is None:
                    score_str = "--"
                else:
                    score_str = f"{score_value:.3f}"
                if run_label:
                    label_text = run_label
                elif isinstance(test_run_index, int) and isinstance(
                    test_run_total, int
                ):
                    label_text = f"{test_name} {test_run_index}/{test_run_total}"
                else:
                    label_text = test_name
                detail_text = f"[{label_text}] {detail_text}   score={score_str}"

                label = entry["label"]
                canvas = entry["canvas"]
                fill_id = entry["fill_id"]
                detail = entry["detail"]

                label.configure(text=f"Gen {gen:04d}  Trial {trial:02d}  Run {run}")
                self._set_canvas_progress(canvas, fill_id, pct, color)
                detail.configure(text=detail_text)

        terminal_states = {"done", "failed", "skipped", "error", "cancelled"}
        for trial in range(1, self.trials_per_gen + 1):
            widget = self.trial_widgets.get(trial)
            if not widget:
                continue
            summary = widget["summary"]
            run_scores = trial_run_scores.get(trial, [])
            test_scores = trial_test_scores.get(trial, {})
            run_score_bits = []
            valid_scores = []
            for idx, score in enumerate(run_scores, start=1):
                if score is None:
                    run_score_bits.append(f"R{idx}=--")
                    continue
                run_score_bits.append(f"R{idx}={score:.3f}")
                if score not in (float("-inf"), -2.0):
                    valid_scores.append(score)

            test_score_bits = []
            aggregated_test_scores: list[float] = []
            test_names_in_order: list[str] = []
            for test_name, scores in test_scores.items():
                valid_test_scores = [
                    score for score in scores if score not in (None, float("-inf"))
                ]
                if not valid_test_scores:
                    test_score_bits.append(f"{test_name}=--")
                    continue
                test_score = sum(valid_test_scores) / len(valid_test_scores)
                aggregated_test_scores.append(test_score)
                test_names_in_order.append(test_name)
                w = test_weights.get(test_name)
                weight_str = f" (w={w}%)" if isinstance(w, (int, float)) else ""
                test_score_bits.append(f"{test_name}={test_score:.3f}{weight_str}")

            trial_score_text = "--"
            states = trial_slot_states.get(trial, [])
            if aggregated_test_scores and states:
                weighted = _weighted_trial_score(
                    aggregated_test_scores, test_names_in_order, test_weights
                )
                if all(s in terminal_states for s in states):
                    trial_score_text = f"{weighted:.3f}"
                else:
                    trial_score_text = f"{weighted:.3f} (partial)"
            elif valid_scores:
                trial_score_text = f"{(sum(valid_scores) / len(valid_scores)):.3f}"

            runs_text = "  ".join(run_score_bits) if run_score_bits else "--"
            tests_text = "  ".join(test_score_bits) if test_score_bits else "--"
            summary.configure(
                text=(
                    f"Trial score: {trial_score_text}   |   Test scores: {tests_text}"
                    f"   |   Run scores: {runs_text}"
                )
            )

        if self.auto_focus_var.get():
            self._auto_focus_earliest_incomplete(current_gen, trial_slot_states)

        if current_gen <= 0:
            self.header.configure(text="Waiting for optimizer...")

    def _read_run_score(self, gen: int, trial: int, run: int) -> float | None:
        trial_state_path = (
            TRIALS_DIR / f"gen_{gen:04d}" / f"trial_{trial:02d}" / "trial_state.json"
        )
        payload = _read_json(trial_state_path)
        if not isinstance(payload, dict):
            return None
        runs = payload.get("runs", [])
        if not isinstance(runs, list) or run <= 0 or run > len(runs):
            return None
        slot = runs[run - 1]
        if not isinstance(slot, dict):
            return None
        raw = slot.get("score")
        try:
            return float(raw)
        except Exception:
            return None

    def _score_from_status_or_file(
        self, status: dict, gen: int, trial: int, run: int
    ) -> float | None:
        raw_status_score = status.get("score")
        if isinstance(raw_status_score, (int, float)):
            return float(raw_status_score)
        return self._read_run_score(gen, trial, run)

    def _jump_to_earliest_incomplete(self) -> None:
        self._auto_focus_earliest_incomplete(self.last_gen_current, None, force=True)

    def _auto_focus_earliest_incomplete(
        self,
        gen: int,
        trial_slot_states: dict[int, list[str]] | None,
        force: bool = False,
    ) -> None:
        terminal_states = {"done", "failed", "skipped", "error", "cancelled"}

        target_trial = None
        for trial in range(1, self.trials_per_gen + 1):
            states = None
            if isinstance(trial_slot_states, dict):
                states = trial_slot_states.get(trial, [])
            if not states:
                inferred = []
                for run in range(1, self.runs_per_trial + 1):
                    key = f"t{trial}_r{run}"
                    s = self.slot_state_cache.get(key, {})
                    inferred.append(str(s.get("state", "not-started")).lower())
                states = inferred

            if not states or any(s not in terminal_states for s in states):
                target_trial = trial
                break

        if target_trial is None:
            target_trial = 1

        target_key = (gen, target_trial)
        if not force and target_key == self.last_auto_focus_target:
            return

        target_widget = self.trial_widgets.get(target_trial)
        if not target_widget:
            return

        frame = target_widget["frame"]
        try:
            self.root.update_idletasks()
            bbox = self.runs_canvas.bbox(self.runs_inner_id)
            if not bbox:
                return

            inner_top = bbox[1]
            inner_height = max(1, bbox[3] - bbox[1])
            canvas_h = max(1, self.runs_canvas.winfo_height())
            frame_top = inner_top + frame.winfo_y()
            desired_top = frame_top - AUTO_FOCUS_MARGIN_PX
            scrollable = max(1, inner_height - canvas_h)
            frac = max(0.0, min(1.0, (desired_top - inner_top) / scrollable))
            self.runs_canvas.yview_moveto(frac)
            self.last_auto_focus_target = target_key
        except Exception:
            return

    def _tick(self) -> None:
        progress = _read_json(PROGRESS_FILE)
        statuses = _collect_run_statuses()

        self._update_top(progress, statuses)
        self._update_runs(progress, statuses)
        self.root.after(POLL_MS, self._tick)

    @staticmethod
    def _fmt_duration(seconds: float) -> str:
        """
        Format seconds as HH:MM:SS.

        Inputs:
            seconds (float): Duration in seconds.

        Returns:
            str: HH:MM:SS formatted duration.
        """
        s = int(max(0, seconds))
        h = s // 3600
        m = (s % 3600) // 60
        sec = s % 60
        return f"{h:02d}:{m:02d}:{sec:02d}"

    @staticmethod
    def _color_for_run_state(status: dict) -> str:
        """
        Pick a fill color by run state/outcome.

        Inputs:
            status (dict): One run status payload.

        Returns:
            str: Hex color for the run fill.
        """
        state = str(status.get("state", "")).lower()
        reason = str(status.get("reason", "")).lower()

        if state in ("launching", "running"):
            return "#0270ff"
        if state in ("failed", "skipped", "error", "cancelled"):
            return "#ff0011"
        if state == "done":
            return "#fdcb26"
        if state == "not-started":
            return "#5a6370"
        return "#c9a227"

    @staticmethod
    def _set_canvas_progress(
        canvas: tk.Canvas, fill_id: int, pct: float, color: str
    ) -> None:
        """
        Update a canvas-based progress bar.

        Inputs:
            canvas (tk.Canvas): Canvas holding the fill rectangle.
            fill_id (int): Rectangle item id.
            pct (float): Progress percentage from 0 to 100.
            color (str): Fill color.

        Returns:
            None
        """
        width = max(1, int(canvas.winfo_width() or int(canvas.cget("width"))))
        height = max(1, int(canvas.winfo_height() or int(canvas.cget("height"))))
        fill_width = int(width * max(0.0, min(100.0, pct)) / 100.0)
        canvas.coords(fill_id, 0, 0, fill_width, height)
        canvas.itemconfigure(fill_id, fill=color)


def main() -> None:
    """
    Launch the Tkinter live monitor window.

    Inputs:
        None

    Returns:
        None
    """
    root = tk.Tk()
    style = ttk.Style(root)
    if "vista" in style.theme_names():
        style.theme_use("vista")
    elif "xpnative" in style.theme_names():
        style.theme_use("xpnative")
    elif "default" in style.theme_names():
        style.theme_use("default")

    style.configure(
        "GlobalGreen.Horizontal.TProgressbar",
        background="#2ea043",
        troughcolor="#e9e9e9",
    )
    style.configure(
        "GenGreen.Horizontal.TProgressbar",
        background="#2ea043",
        troughcolor="#e9e9e9",
    )

    app = MonitorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
