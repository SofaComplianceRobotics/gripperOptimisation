"""Dash app factory and server launch for ShapeOPT dashboard."""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path

from launcher.bootstrap import bootstrap_lab

SCRIPT_DIR, _SRC_ROOT, _APP_ROOT, _LAB_ROOT = bootstrap_lab(__file__)
ANALYSIS_DIR = Path(__file__).resolve().parent
if str(ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(ANALYSIS_DIR))

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

from callbacks.config import register_config_callbacks
from callbacks.generation import register_generation_callbacks
from callbacks.monitoring import register_monitoring_callbacks
from callbacks.optimize import register_optimise_callbacks
from callbacks.scenes import register_scene_callbacks
from ui.tabs import (
    build_config_tab,
    build_generate_tab,
    build_optimise_tab,
    build_param_bounds_tab,
    build_performance_tab,
    build_progress_tab,
    build_scenes_tab,
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
        external_stylesheets=[
            "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css"
        ],
    )

    app.layout = html.Div(
        [
            html.Div(
                [
                    html.H1("ShapeOPT", className="text-center mb-1 mt-1"),
                    html.P(
                        "Configure · Generate · Optimise · Analyse",
                        className="text-center text-muted mb-2",
                    ),
                ]
            ),
            dcc.Tabs(
                id="tabs",
                value="config",
                children=[
                    dcc.Tab(
                        label="Config", value="config", children=build_config_tab()
                    ),
                    dcc.Tab(
                        label="Generate",
                        value="generate",
                        children=build_generate_tab(),
                    ),
                    dcc.Tab(
                        label="Scenes",
                        value="scenes",
                        children=build_scenes_tab(catalog),
                    ),
                    dcc.Tab(
                        label="Optimise",
                        value="optimise",
                        children=build_optimise_tab(catalog),
                    ),
                    dcc.Tab(
                        label="Performance",
                        value="performance",
                        children=build_performance_tab(),
                    ),
                    dcc.Tab(
                        label="Progress",
                        value="progress",
                        children=build_progress_tab(),
                    ),
                    dcc.Tab(
                        label="Parameter Bounds",
                        value="bounds",
                        children=build_param_bounds_tab(),
                    ),
                ],
            ),
        ],
        className="py-3",
    )

    register_config_callbacks(app)
    register_generation_callbacks(app, catalog)
    register_scene_callbacks(app, catalog)
    register_optimise_callbacks(app)
    register_monitoring_callbacks(app)

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
