"""Dashboard callbacks for scene launch controls."""

from __future__ import annotations

from pathlib import Path

from dash import Input, Output, State, ctx

from names import GRIPPER_COLLISION_FINGER_STLS, LEG_WORKING_NAME, LEGS_DIRNAME
from dashboard.process.process_manager import (
    INVERSE_SCENE,
    RECORDING_SCENE,
    _launch_sofa_scene,
    _write_session_config,
)
from sofaopt_project import run_trajectory_recorder


LAB_ROOT = Path(__file__).resolve().parents[2]
LEGS_DIR = LAB_ROOT.parent.parent / "data" / "meshes" / LEGS_DIRNAME
WATCH_RECORDING_FILE = LAB_ROOT / "runtime" / "watch_recording.json"


def _generated_leg_name() -> str | None:
    """Return the lab's last-generated leg name (from the Generate button), if present.

    Both files (beam positions + visual mesh) must exist — see parts.leg.Leg.
    None means callers should leave OPT_LEG_NAME unset, falling back to the
    stock blueleg baked into base_scene.py.
    """
    if (LEGS_DIR / f"{LEG_WORKING_NAME}.stl").exists() and (
        LEGS_DIR / f"{LEG_WORKING_NAME}.txt"
    ).exists():
        return LEG_WORKING_NAME
    return None


def register_scene_callbacks(app, catalog: dict) -> None:
    """Register scene tab callbacks: inverse, recording, and watch scene launchers."""

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
        """Launch the selected SOFA scene with the appropriate configuration.

        Watch mode injects the test's scene file and env vars (test name,
        weights, run slot, STL path) so the scene runs as if called by the
        optimizer, allowing manual inspection of any labtest.

        Args:
            _: Inverse scene button click count.
            __: Recording scene button click count.
            ___: Watch scene button click count.
            recording_test: Test name selected in the recording dropdown.
            watch_test: Test name selected in the watch dropdown.
            watch_slot: Run slot index for the watch scene (0-indexed).

        Returns:
            Status message string from the scene launcher.
        """
        tid = ctx.triggered_id
        if tid == "scene-inverse-btn":
            leg_name = _generated_leg_name()
            extra_env = {"OPT_LEG_NAME": leg_name} if leg_name else None
            return _launch_sofa_scene(INVERSE_SCENE, extra_env=extra_env)
        if tid == "scene-recording-btn" and recording_test:
            _write_session_config(recording_test)
            leg_name = _generated_leg_name()
            extra_env = {"OPT_LEG_NAME": leg_name} if leg_name else None
            return _launch_sofa_scene(RECORDING_SCENE, extra_env=extra_env)
        if tid == "scene-watch-btn" and watch_test and watch_test in catalog:
            test_spec = catalog[watch_test]
            extra_env = {
                "OPT_TEST_NAME": watch_test,
                "OPT_RUN_SLOT": str(watch_slot or "1"),
            }
            default_finger_stls = [
                LAB_ROOT / "runtime" / "exports" / name
                for name in GRIPPER_COLLISION_FINGER_STLS
            ]
            if all(p.exists() for p in default_finger_stls):
                extra_env["OPT_MESH_FINGER1"] = str(default_finger_stls[0])
                extra_env["OPT_MESH_FINGER2"] = str(default_finger_stls[1])
            # Same idea for the leg: use the lab's own last-generated leg
            # (from the Generate button) instead of silently falling back to
            # the stock blueleg baked into base_scene.py.
            leg_name = _generated_leg_name()
            if leg_name:
                extra_env["OPT_LEG_NAME"] = leg_name

            # Record a fresh motor trajectory for this same gripper/leg before
            # watching the test, instead of replaying the fixed reference
            # recording — otherwise Watch never exercises the geometry it's
            # about to test.
            try:
                frame_count = run_trajectory_recorder(WATCH_RECORDING_FILE, leg_name)
                extra_env["OPT_MOTOR_RECORDING"] = str(WATCH_RECORDING_FILE)
                recording_status = f"Recorded {frame_count} motor frames for this geometry. "
            except Exception as exc:
                recording_status = (
                    f"Trajectory recording failed ({exc}); using the reference "
                    "recording instead. "
                )

            return recording_status + _launch_sofa_scene(
                test_spec.scene_file, extra_env=extra_env
            )
        return ""