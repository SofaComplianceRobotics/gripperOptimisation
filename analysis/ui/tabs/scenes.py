"""Scenes tab — SOFA scene launching."""

from dash import dcc, html


def build_scenes_tab(catalog: dict) -> html.Div:
    """Build and return the Scenes tab layout.

    Args:
        catalog: Mapping of test names to their scene specifications.

    Returns:
        A Dash HTML `Div` for launching SOFA scenes and recordings.
    """
    test_options = [
        {"label": spec.label, "value": name} for name, spec in catalog.items()
    ]
    default_test = next(iter(catalog), "")

    return html.Div(
        [
            html.H3("SOFA Scenes", className="mb-3"),
            html.Div(
                [
                    html.H5("Inverse Control"),
                    html.P(
                        "Interactive inverse-mode scene — drag the end-effector target to control the gripper.",
                        className="text-muted",
                    ),
                    html.Button(
                        "Launch Inverse Scene",
                        id="scene-inverse-btn",
                        n_clicks=0,
                        className="btn btn-primary",
                    ),
                ],
                className="p-3 mb-3 border rounded",
            ),
            html.Div(
                [
                    html.H5("Motor Recording"),
                    html.P(
                        "Record motor trajectories for a test target. The target is saved before launching.",
                        className="text-muted",
                    ),
                    html.Div(
                        [
                            html.Label("Target test:", className="me-2 fw-semibold"),
                            dcc.Dropdown(
                                id="scene-recording-test",
                                options=test_options,
                                value=default_test,
                                clearable=False,
                                style={"width": "300px"},
                            ),
                        ],
                        className="d-flex align-items-center mb-3",
                    ),
                    html.Button(
                        "Set Target & Launch Recording Scene",
                        id="scene-recording-btn",
                        n_clicks=0,
                        className="btn btn-primary",
                    ),
                ],
                className="p-3 border rounded",
            ),
            html.Div(id="scene-status", className="mt-3 fw-semibold"),
        ],
        className="p-3",
    )
