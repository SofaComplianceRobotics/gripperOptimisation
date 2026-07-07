"""Generate tab — 3D model generation controls."""

from dash import dcc, html

from sofaopt.dashboard.ui.tabs.styles import LOG_STYLE


def build_generate_tab() -> html.Div:
    """Build and return the Generate tab layout for the dashboard.

    Returns:
        A Dash HTML `Div` containing generation controls and logs.
    """
    return html.Div(
        [
            html.H3("Generate 3D Model", className="mb-2"),
            html.P(
                "Generate STL/VTK/JSON files from the current lab_config.jsonc.",
                className="text-muted mb-3",
            ),
            html.Div(
                [
                    html.Button(
                        "Generate (sim mesh)",
                        id="gen-btn",
                        n_clicks=0,
                        className="btn btn-primary me-2",
                    ),
                    html.Button(
                        "Generate Fine (print mesh)",
                        id="gen-fine-btn",
                        n_clicks=0,
                        className="btn btn-secondary me-2",
                    ),
                    html.Button(
                        "Stop",
                        id="gen-stop-btn",
                        n_clicks=0,
                        className="btn btn-danger",
                    ),
                ],
                className="mb-3",
            ),
            html.Div(id="gen-status", className="mb-2 fw-semibold"),
            html.Pre(id="gen-log", style=LOG_STYLE),
            dcc.Interval(id="gen-interval", interval=800, n_intervals=0),
            html.Hr(className="mt-3"),
            html.H6("Open generated files", className="mb-2 text-muted"),
            html.Div(
                [
                    html.Div(
                        [
                            html.Small("Sim mesh", className="d-block text-muted mb-1"),
                            html.Button(
                                "Open STL",
                                id="gen-open-stl-btn",
                                n_clicks=0,
                                className="btn btn-outline-secondary btn-sm me-2",
                            ),
                            html.Button(
                                "Open JSON",
                                id="gen-open-json-btn",
                                n_clicks=0,
                                className="btn btn-outline-secondary btn-sm",
                            ),
                        ],
                        className="me-4",
                    ),
                    html.Div(
                        [
                            html.Small(
                                "Print mesh", className="d-block text-muted mb-1"
                            ),
                            html.Button(
                                "Open STL",
                                id="gen-open-fine-stl-btn",
                                n_clicks=0,
                                className="btn btn-outline-secondary btn-sm",
                            ),
                        ],
                    ),
                ],
                className="d-flex align-items-start mb-2",
            ),
            html.Div(id="gen-open-status", className="small text-muted"),
        ],
        className="p-3",
    )
