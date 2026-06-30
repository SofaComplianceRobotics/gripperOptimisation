"""Dashboard callbacks for generation controls."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from dash import Input, Output, ctx

from names import CENTERPARTS_DIRNAME, GRIPPER_NAME, GRIPPER_PRINT_NAME
from dashboard.process.process_manager import (
    GENERATE_FINE_SCRIPT,
    GENERATE_SCRIPT,
    _read_proc_log,
    _start_proc,
    _stop_proc,
)


LAB_ROOT = Path(__file__).resolve().parents[2]
CENTERPARTS_DIR = LAB_ROOT.parent.parent / "data" / "meshes" / CENTERPARTS_DIRNAME


def _open_in_os(path: Path) -> None:
    """Open a file with the OS default application on any platform."""
    if sys.platform == "win32":
        os.startfile(str(path))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def register_generation_callbacks(app, _catalog: dict) -> None:
    """Register generation tab callbacks: run/stop buttons and file open actions."""

    @app.callback(
        Output("gen-status", "children"),
        Input("gen-btn", "n_clicks"),
        Input("gen-fine-btn", "n_clicks"),
        Input("gen-stop-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def handle_generate(_, __, ___):
        """Start standard generation, fine generation, or stop the subprocess.

        Dispatches on ``ctx.triggered_id`` rather than click counts so all
        three buttons share one callback without ambiguity.

        Args:
            _: Standard generate button click count.
            __: Fine generate button click count.
            ___: Stop button click count.

        Returns:
            Status message string from the subprocess manager.
        """
        tid = ctx.triggered_id
        if tid == "gen-stop-btn":
            return _stop_proc("generate")
        if tid == "gen-fine-btn":
            return _start_proc("generate", GENERATE_FINE_SCRIPT)
        return _start_proc("generate", GENERATE_SCRIPT)

    @app.callback(
        Output("gen-log", "children"),
        Input("gen-interval", "n_intervals"),
    )
    def update_gen_log(_):
        """Poll and return the current generate subprocess log.

        Args:
            _: Interval tick (unused).

        Returns:
            Log contents as a string.
        """
        return _read_proc_log("generate")

    @app.callback(
        Output("gen-open-status", "children"),
        Input("gen-open-stl-btn", "n_clicks"),
        Input("gen-open-json-btn", "n_clicks"),
        Input("gen-open-fine-stl-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def handle_gen_open(_, __, ___):
        """Open a generated output file in the OS default viewer.

        Args:
            _: Open STL button click count.
            __: Open JSON button click count.
            ___: Open fine STL button click count.

        Returns:
            Status message string describing the outcome.
        """
        file_map = {
            "gen-open-stl-btn": CENTERPARTS_DIR / f"{GRIPPER_NAME}.stl",
            "gen-open-json-btn": CENTERPARTS_DIR / f"{GRIPPER_NAME}.json",
            "gen-open-fine-stl-btn": CENTERPARTS_DIR / f"{GRIPPER_PRINT_NAME}.stl",
        }
        path = file_map.get(ctx.triggered_id)
        if path is None:
            return ""
        if not path.exists():
            return f"{path.name} not found — generate first."
        try:
            _open_in_os(path)
            return f"Opened {path.name}."
        except Exception as exc:
            return f"Could not open {path.name}: {exc}"