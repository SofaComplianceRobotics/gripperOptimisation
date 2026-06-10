"""Config tab — Configuration editor."""

from dash import dcc, html


def build_config_tab() -> html.Div:
    """Build and return the Config tab layout for the dashboard.

    Returns:
        A Dash HTML `Div` containing configuration editor and save controls.
    """
    from dashboard.process.process_manager import _load_config_text

    return html.Div(
        [
            html.H3("Gripper Configuration", className="mb-2"),
            html.P(
                "Edit lab_config.jsonc parameters. Click Save to write to disk.",
                className="text-muted mb-3",
            ),
            dcc.Textarea(
                id="config-textarea",
                value=_load_config_text(),
                style={
                    "width": "100%",
                    "height": "520px",
                    "fontFamily": "monospace",
                    "fontSize": "0.88rem",
                    "border": "1px solid #ced4da",
                    "borderRadius": "6px",
                    "padding": "10px",
                },
            ),
            html.Div(
                [
                    html.Button(
                        "Save",
                        id="config-save-btn",
                        n_clicks=0,
                        className="btn btn-primary me-3",
                    ),
                    html.Span(id="config-save-status", className="align-middle"),
                ],
                className="mt-2 d-flex align-items-center",
            ),
        ],
        className="p-3",
    )
