"""
param_bounds_viewer.py — Shows where the latest gripper's parameters sit within their bounds.

For each actively optimized parameter, renders a read-only bar indicating the
current value's position between the optimizer's min and max bounds.
Color codes warn when a value is approaching or hitting a limit.
Auto-refreshes every 2 s so it tracks the running optimizer in real time.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk

# ─────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────
LAB_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = LAB_ROOT / "app" / "src"
TRIALS_DIR = LAB_ROOT / "runtime" / "trials"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

# ─────────────────────────────────────────────
# Load active param specs (min < max only)
# ─────────────────────────────────────────────

def _load_active_specs() -> list[dict]:
    """Import PARAM_SPECS from optimize_config and keep only active (non-frozen) entries."""
    try:
        from optimization.optimize_config import PARAM_SPECS  # type: ignore
        return [p for p in PARAM_SPECS if p["min"] < p["max"]]
    except Exception as e:
        print(f"[warn] Could not import optimize_config: {e}")
        return []


ACTIVE_SPECS: list[dict] = _load_active_specs()

# ─────────────────────────────────────────────
# Data helpers
# ─────────────────────────────────────────────

def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _find_latest_trial() -> tuple[Path | None, str]:
    """Return (lab_config.jsonc path, label) for the highest gen/trial completed so far."""
    best_gen = -1
    best_trial = -1
    best_path: Path | None = None
    best_label = ""

    for gen_dir in TRIALS_DIR.glob("gen_*"):
        try:
            gen_num = int(gen_dir.name.split("_")[1])
        except (IndexError, ValueError):
            continue
        for trial_dir in gen_dir.glob("trial_*"):
            try:
                trial_num = int(trial_dir.name.split("_")[1])
            except (IndexError, ValueError):
                continue
            config = trial_dir / "lab_config.jsonc"
            if not config.exists():
                continue
            if (gen_num, trial_num) > (best_gen, best_trial):
                best_gen = gen_num
                best_trial = trial_num
                best_path = config
                best_label = f"{gen_dir.name} / {trial_dir.name}"

    return best_path, best_label

# ─────────────────────────────────────────────
# Colors / layout constants
# ─────────────────────────────────────────────
BG       = "#1c1c1c"
ROW_ALT  = "#222222"
FG       = "#e8e8e8"
FG_DIM   = "#888888"
BAR_TRACK = "#2e2e2e"
COLOR_OK   = "#4caf50"
COLOR_WARN = "#ff9800"
COLOR_CRIT = "#f44336"
TICK_FG  = "#ffffff"
SEP_CLR  = "#3a3a3a"

WARN_EDGE = 0.15   # within 15 % of either end → orange
CRIT_EDGE = 0.05   # within  5 % of either end → red
BAR_H     = 14
POLL_MS   = 2000


def _frac(v: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 0.5
    return max(0.0, min(1.0, (v - lo) / (hi - lo)))


def _bar_color(frac: float) -> str:
    edge = min(frac, 1.0 - frac)
    if edge <= CRIT_EDGE:
        return COLOR_CRIT
    if edge <= WARN_EDGE:
        return COLOR_WARN
    return COLOR_OK

# ─────────────────────────────────────────────
# UI
# ─────────────────────────────────────────────


class BoundsViewer:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("ShapeOPT — Parameter Bounds")
        self.root.configure(bg=BG)
        self._rows: dict[str, dict] = {}
        self._build_ui()
        self._refresh()

    # ── Construction ────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # Header row
        hdr = tk.Frame(self.root, bg=BG)
        hdr.pack(fill="x", padx=16, pady=(14, 4))

        tk.Label(
            hdr, text="Parameter Bounds", font=("Segoe UI", 12, "bold"),
            bg=BG, fg=FG,
        ).pack(side="left")

        self._score_lbl = tk.Label(hdr, text="", font=("Segoe UI", 10), bg=BG, fg=COLOR_OK)
        self._score_lbl.pack(side="left", padx=10)

        self._source_lbl = tk.Label(hdr, text="—", font=("Segoe UI", 9), bg=BG, fg=FG_DIM)
        self._source_lbl.pack(side="right")

        tk.Frame(self.root, bg=SEP_CLR, height=1).pack(fill="x", padx=16, pady=(4, 0))

        # Column headers
        col_hdr = tk.Frame(self.root, bg=BG, padx=14, pady=4)
        col_hdr.pack(fill="x")
        tk.Label(col_hdr, text="parameter", font=("Segoe UI", 8), bg=BG, fg=FG_DIM,
                 width=30, anchor="w").pack(side="left")
        tk.Label(col_hdr, text="value", font=("Segoe UI", 8), bg=BG, fg=FG_DIM,
                 width=12, anchor="e").pack(side="right")

        tk.Frame(self.root, bg=SEP_CLR, height=1).pack(fill="x", padx=16, pady=(0, 2))

        # Scrollable body
        outer = tk.Frame(self.root, bg=BG)
        outer.pack(fill="both", expand=True)

        self._canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(outer, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._body = tk.Frame(self._canvas, bg=BG)
        self._win_id = self._canvas.create_window((0, 0), window=self._body, anchor="nw")

        self._body.bind(
            "<Configure>",
            lambda _e: self._canvas.configure(scrollregion=self._canvas.bbox("all")),
        )
        self._canvas.bind(
            "<Configure>",
            lambda e: self._canvas.itemconfig(self._win_id, width=e.width),
        )

        for i, spec in enumerate(ACTIVE_SPECS):
            self._make_row(spec, ROW_ALT if i % 2 else BG)

    def _make_row(self, spec: dict, bg: str) -> None:
        name = spec["name"]
        lo, hi = spec["min"], spec["max"]

        row = tk.Frame(self._body, bg=bg, padx=14, pady=6)
        row.pack(fill="x")

        # Name + current value
        top = tk.Frame(row, bg=bg)
        top.pack(fill="x")

        tk.Label(
            top, text=name, font=("Segoe UI Mono", 9, "bold"),
            bg=bg, fg=FG, anchor="w", width=30,
        ).pack(side="left")

        val_lbl = tk.Label(
            top, text="—", font=("Segoe UI Mono", 9),
            bg=bg, fg=FG, anchor="e", width=12,
        )
        val_lbl.pack(side="right")

        # Min label · bar · max label
        bot = tk.Frame(row, bg=bg)
        bot.pack(fill="x", pady=(3, 0))

        tk.Label(bot, text=f"{lo:g}", font=("Segoe UI", 8), bg=bg, fg=FG_DIM).pack(side="left")
        tk.Label(bot, text=f"{hi:g}", font=("Segoe UI", 8), bg=bg, fg=FG_DIM).pack(side="right")

        bar = tk.Canvas(bot, height=BAR_H, bg=BAR_TRACK, highlightthickness=0)
        bar.pack(fill="x", padx=5)

        self._rows[name] = {"val": val_lbl, "bar": bar, "lo": lo, "hi": hi, "frac": 0.0}

    # ── Drawing ─────────────────────────────────────────────────────

    def _draw_bar(self, name: str) -> None:
        row = self._rows[name]
        canvas: tk.Canvas = row["bar"]
        frac: float = row["frac"]

        canvas.delete("all")
        w = canvas.winfo_width()
        h = canvas.winfo_height()
        if w < 4:
            return

        fill_x = int(w * frac)
        color = _bar_color(frac)
        if fill_x > 0:
            canvas.create_rectangle(0, 0, fill_x, h, fill=color, outline="")

        # White tick at current position
        tx = max(1, min(w - 1, fill_x))
        canvas.create_line(tx, 0, tx, h, fill=TICK_FG, width=2)

    # ── Refresh loop ────────────────────────────────────────────────

    def _refresh(self) -> None:
        config_path, label = _find_latest_trial()

        if config_path is None:
            self._source_lbl.config(text="no data found")
            self.root.after(POLL_MS, self._refresh)
            return

        self._source_lbl.config(text=label)
        params = _read_json(config_path) or {}

        state = _read_json(config_path.parent / "trial_state.json") or {}
        score = state.get("final_score")
        self._score_lbl.config(
            text=f"score  {score:.1f}" if score is not None else ""
        )

        for name, row in self._rows.items():
            val = params.get(name)
            if val is None:
                row["val"].config(text="N/A")
                continue

            frac = _frac(float(val), row["lo"], row["hi"])
            row["frac"] = frac
            row["val"].config(text=f"{val:.5g}")
            self.root.after(20, lambda n=name: self._draw_bar(n))

        self.root.after(POLL_MS, self._refresh)


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────

def main() -> None:
    if not ACTIVE_SPECS:
        print("[error] No active parameter specs loaded — check optimize_config.py is reachable.")
        return

    root = tk.Tk()
    root.geometry("740x700")
    BoundsViewer(root)
    root.mainloop()


if __name__ == "__main__":
    main()
