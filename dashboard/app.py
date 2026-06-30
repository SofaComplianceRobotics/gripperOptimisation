"""Dash app factory and server launch for ShapeOPT dashboard."""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
import webbrowser

from launcher.bootstrap import bootstrap_lab

SCRIPT_DIR, _SRC_ROOT, _APP_ROOT, _LAB_ROOT = bootstrap_lab(__file__)

try:
    from dash import Dash, dcc, html
except ImportError as exc:
    raise ImportError(
        "The 'dash' package is required for the ShapeOPT dashboard. "
        f"Install it with: {sys.executable} -m pip install dash"
    ) from exc


os.environ.pop("WERKZEUG_RUN_MAIN", None)
os.environ.pop("WERKZEUG_SERVER_FD", None)
logging.getLogger("werkzeug").setLevel(logging.ERROR)
logging.getLogger("dash").setLevel(logging.ERROR)

from dashboard.callbacks.config import register_config_callbacks
from dashboard.callbacks.generation import register_generation_callbacks
from dashboard.callbacks.monitoring import register_monitoring_callbacks
from dashboard.callbacks.optimize import register_optimise_callbacks
from dashboard.callbacks.playground import register_playground_callbacks
from dashboard.callbacks.scenes import register_scene_callbacks
from dashboard.ui.tabs import (
    build_config_tab,
    build_generate_tab,
    build_optimise_tab,
    build_param_bounds_tab,
    build_performance_tab,
    build_playground_tab,
    build_progress_tab,
    build_scenes_tab,
)
from dashboard.ui.tabs.styles import (
    BODY_STYLE,
    HEADER_BAR_STYLE,
    HEADER_INNER_STYLE,
    HEADER_SUBTITLE_STYLE,
    HEADER_TITLE_STYLE,
    PAGE_STYLE,
    TAB_CONTENT_STYLE,
    TAB_SELECTED_STYLE,
    TAB_STYLE,
    TABS_STYLE,
)


def create_app() -> Dash:
    """Construct and return the Dash application instance for ShapeOPT."""
    from labtests.registry import get_test_catalog

    try:
        catalog = get_test_catalog()
    except Exception as exc:
        print(f"[warn] Could not load test catalog: {exc}")
        catalog = {}

    app = Dash(
        __name__,
        title="ShapeOPT",
        update_title=None,
        external_stylesheets=[
            "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"
        ],
    )

    tab_defs = [
        ("Config", "config", build_config_tab()),
        ("Generate", "generate", build_generate_tab()),
        ("Scenes", "scenes", build_scenes_tab(catalog)),
        ("Optimise", "optimise", build_optimise_tab(catalog)),
        ("Performance", "performance", build_performance_tab()),
        ("Progress", "progress", build_progress_tab()),
        ("Parameter Bounds", "bounds", build_param_bounds_tab()),
        ("Playground", "playground", build_playground_tab()),
    ]

    app.layout = html.Div(
        [
            html.Header(
                html.Div(
                    [
                        html.Span("ShapeOPT", style=HEADER_TITLE_STYLE),
                        html.Span(
                            "Configure · Generate · Optimise · Analyse",
                            style=HEADER_SUBTITLE_STYLE,
                        ),
                    ],
                    style=HEADER_INNER_STYLE,
                ),
                style=HEADER_BAR_STYLE,
            ),
            html.Div(
                dcc.Tabs(
                    id="tabs",
                    value="config",
                    style=TABS_STYLE,
                    children=[
                        dcc.Tab(
                            label=label,
                            value=value,
                            children=html.Div(children, style=TAB_CONTENT_STYLE),
                            style=TAB_STYLE,
                            selected_style=TAB_SELECTED_STYLE,
                        )
                        for label, value, children in tab_defs
                    ],
                ),
                style=BODY_STYLE,
            ),
        ],
        style=PAGE_STYLE,
    )

    register_config_callbacks(app)
    register_generation_callbacks(app, catalog)
    register_scene_callbacks(app, catalog)
    register_optimise_callbacks(app)
    register_monitoring_callbacks(app)
    register_playground_callbacks(app)

    return app


def launch_dashboard(port: int = 8050, open_browser: bool = True) -> None:
    """Start the ShapeOPT dashboard web server and optionally open a browser."""
    print(f"[info] Starting ShapeOPT on http://localhost:{port}")

    os.environ["WERKZEUG_RUN_MAIN"] = "false"
    os.environ.pop("WERKZEUG_SERVER_FD", None)

    app = create_app()
    launch_url = f"http://localhost:{port}/?v={int(time.time())}"

    if open_browser:

        def open_browser_delayed() -> None:
            time.sleep(2)
            webbrowser.open_new_tab(launch_url)

        thread = threading.Thread(target=open_browser_delayed, daemon=True)
        thread.start()

    app.run(debug=False, use_reloader=False, port=port, host="127.0.0.1")


if __name__ == "__main__":
    launch_dashboard()
