"""Dashboard callbacks for generation controls."""

from __future__ import annotations

import os
from pathlib import Path

from dash import Input, Output, ctx

from process.process_manager import (
    GENERATE_FINE_SCRIPT,
    GENERATE_SCRIPT,
    _read_proc_log,
    _start_proc,
    _stop_proc,
)


LAB_ROOT = Path(__file__).resolve().parents[2]
CENTERPARTS_DIR = LAB_ROOT.parent.parent / "data" / "meshes" / "centerparts"


def register_generation_callbacks(app, _catalog: dict) -> None:
    @app.callback(
        Output("gen-status", "children"),
        Input("gen-btn", "n_clicks"),
        Input("gen-fine-btn", "n_clicks"),
        Input("gen-stop-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def handle_generate(_, __, ___):
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
        return _read_proc_log("generate")

    @app.callback(
        Output("gen-open-status", "children"),
        Input("gen-open-stl-btn", "n_clicks"),
        Input("gen-open-json-btn", "n_clicks"),
        Input("gen-open-fine-stl-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def handle_gen_open(_, __, ___):
        file_map = {
            "gen-open-stl-btn": CENTERPARTS_DIR / "new_gripper.stl",
            "gen-open-json-btn": CENTERPARTS_DIR / "new_gripper.json",
            "gen-open-fine-stl-btn": CENTERPARTS_DIR / "new_gripper_print.stl",
        }
        path = file_map.get(ctx.triggered_id)
        if path is None:
            return ""
        if not path.exists():
            return f"{path.name} not found — generate first."
        try:
            os.startfile(str(path))
            return f"Opened {path.name}."
        except Exception as exc:
            return f"Could not open {path.name}: {exc}"