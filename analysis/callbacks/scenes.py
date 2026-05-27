"""Dashboard callbacks for scene launch controls."""

from __future__ import annotations

import json
from pathlib import Path

from dash import Input, Output, State, ctx

from process.process_manager import (
    INVERSE_SCENE,
    RECORDING_SCENE,
    _launch_sofa_scene,
    _write_session_config,
)


LAB_ROOT = Path(__file__).resolve().parents[2]


def register_scene_callbacks(app, catalog: dict) -> None:
    @app.callback(
        Output("scene-status", "children"),
        Input("scene-inverse-btn", "n_clicks"),
        Input("scene-recording-btn", "n_clicks"),
        Input("scene-watch-btn", "n_clicks"),
        State("scene-recording-test", "value"),
        State("scene-watch-test", "value"),
        State("scene-watch-slot", "value"),
        prevent_initial_call=True,
    )
    def handle_scene(_, __, ___, recording_test, watch_test, watch_slot):
        tid = ctx.triggered_id
        if tid == "scene-inverse-btn":
            return _launch_sofa_scene(INVERSE_SCENE)
        if tid == "scene-recording-btn" and recording_test:
            _write_session_config(recording_test)
            return _launch_sofa_scene(RECORDING_SCENE)
        if tid == "scene-watch-btn" and watch_test and watch_test in catalog:
            test_spec = catalog[watch_test]
            extra_env = {
                "LAB_SHAPEOPT_TEST": watch_test,
                "LAB_SHAPEOPT_TESTS": watch_test,
                "LAB_SHAPEOPT_TEST_WEIGHTS": json.dumps({watch_test: 100}),
                "OPTUNA_RUN_SLOT": str(watch_slot or "0"),
            }
            default_stl = LAB_ROOT / "runtime" / "exports" / "new_gripper_collision.stl"
            if default_stl.exists():
                extra_env["OPTUNA_STL_PATH"] = str(default_stl)
            return _launch_sofa_scene(test_spec.scene_file, extra_env=extra_env)
        return ""