"""Dash app factory and server launch for ShapeOPT dashboard."""

import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

try:
    from dash import Dash, dcc, html, callback, Input, Output, State, ALL
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    DASH_AVAILABLE = True
except ImportError:
    DASH_AVAILABLE = False

# ── Paths ──────────────────────────────────────────────────────
LAB_ROOT = Path(__file__).resolve().parents[1]
TRIALS_DIR = LAB_ROOT / "runtime" / "trials"
CENTERPARTS_DIR = LAB_ROOT.parent.parent / "data" / "meshes" / "centerparts"

from launcher.bootstrap import bootstrap_lab

# Ensure repo roots are on sys.path when running standalone
SCRIPT_DIR, _SRC_ROOT, _APP_ROOT, _LAB_ROOT = bootstrap_lab(__file__)
ANALYSIS_DIR = Path(__file__).resolve().parent
if str(ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(ANALYSIS_DIR))

# Suppress noisy server logs
os.environ.pop("WERKZEUG_RUN_MAIN", None)
os.environ.pop("WERKZEUG_SERVER_FD", None)
logging.getLogger("werkzeug").setLevel(logging.ERROR)
logging.getLogger("dash").setLevel(logging.ERROR)

# Import from new modules
from process.process_manager import (
    _proc_running,
    _start_proc,
    _stop_proc,
    _read_proc_log,
    _launch_sofa_scene,
    _write_session_config,
    GENERATE_SCRIPT,
    GENERATE_FINE_SCRIPT,
    INVERSE_SCENE,
    RECORDING_SCENE,
    OPTIMIZE_SCRIPT,
)
from data.cache import _load_data, _current_generation_records, _read_json
from ui.tabs import (
    build_config_tab,
    build_generate_tab,
    build_scenes_tab,
    build_optimise_tab,
    build_performance_tab,
    build_param_bounds_tab,
    build_progress_tab,
)
from ui.progress import (
    _build_progress_card,
    _build_progress_stats,
    _build_progress_grid,
    _get_trial_actual_state,
    _find_earliest_not_done,
    _build_trial_detail,
)
from plotting.performance import _build_performance_graph, _build_leaderboard_html
from plotting.bounds import _build_param_bounds_graph


# Auto-install Dash if needed
def install_dependencies():
    """Auto-install missing dependencies."""
    packages = ["dash"]
    for pkg in packages:
        try:
            __import__(pkg.replace("-", "_"))
        except ImportError:
            print(f"[info] Installing {pkg}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])


if not DASH_AVAILABLE:
    install_dependencies()
    from dash import Dash, dcc, html, callback, Input, Output, State, ALL
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots


# ─────────────────────────────────────────────────────────────
# Main Dash App
# ─────────────────────────────────────────────────────────────


def create_app() -> Dash:
    """Construct and return the Dash application instance for ShapeOPT."""
    from labtests.registry import get_test_catalog
    from data.cache import _read_json

    try:
        catalog = get_test_catalog()
    except Exception as exc:
        print(f"[warn] Could not load test catalog: {exc}")
        catalog = {}

    all_test_names_ordered = list(catalog.keys())

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
                        label="Config",
                        value="config",
                        children=build_config_tab(),
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

    # ── Config callbacks ──────────────────────────────────────

    @callback(
        Output("config-save-status", "children"),
        Input("config-save-btn", "n_clicks"),
        State("config-textarea", "value"),
        prevent_initial_call=True,
    )
    def save_config(_, text):
        from process.process_manager import CONFIG_FILE

        if not text:
            return "Nothing to save."
        try:
            clean = re.sub(r"//[^\n]*", "", text)
            data = json.loads(clean)
            CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return html.Span("Saved.", style={"color": "#2f9e44"})
        except json.JSONDecodeError as exc:
            return html.Span(f"Invalid JSON: {exc}", style={"color": "#e03131"})
        except Exception as exc:
            return html.Span(f"Error: {exc}", style={"color": "#e03131"})

    # ── Generate callbacks ────────────────────────────────────

    @callback(
        Output("gen-status", "children"),
        Input("gen-btn", "n_clicks"),
        Input("gen-fine-btn", "n_clicks"),
        Input("gen-stop-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def handle_generate(_, __, ___):
        from dash import ctx

        tid = ctx.triggered_id
        if tid == "gen-stop-btn":
            return _stop_proc("generate")
        elif tid == "gen-fine-btn":
            return _start_proc("generate", GENERATE_FINE_SCRIPT)
        else:
            return _start_proc("generate", GENERATE_SCRIPT)

    @callback(
        Output("gen-log", "children"),
        Input("gen-interval", "n_intervals"),
    )
    def update_gen_log(_):
        return _read_proc_log("generate")

    @callback(
        Output("gen-open-status", "children"),
        Input("gen-open-stl-btn", "n_clicks"),
        Input("gen-open-json-btn", "n_clicks"),
        Input("gen-open-fine-stl-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def handle_gen_open(_, __, ___):
        from dash import ctx

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

    # ── Scenes callbacks ──────────────────────────────────────

    @callback(
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
        from dash import ctx

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

    # ── Optimise callbacks (clientside — zero server round-trips) ─────────
    #
    # Architecture: opt-weights-store is the single source of truth.
    # All weight logic runs in the browser as JS → instant response on drag.

    app.clientside_callback(
        """
        function(slider_vals, check_vals, eq_clicks, norm_clicks, slider_ids, store) {
            var NO_UPDATE = window.dash_clientside.no_update;
            var ctx = window.dash_clientside.callback_context;
            if (!ctx || !ctx.triggered || ctx.triggered.length === 0) return NO_UPDATE;

            var prop_id = ctx.triggered[0].prop_id;
            var dot = prop_id.lastIndexOf('.');
            var id_part = prop_id.substring(0, dot);
            var tid;
            try { tid = JSON.parse(id_part); } catch(e) { tid = id_part; }

            store = store ? Object.assign({}, store) : {};
            var all_tests = slider_ids.map(function(s) { return s.test; });
            var selected_tests = [];
            slider_ids.forEach(function(s, i) {
                if (check_vals[i] && check_vals[i].length > 0) selected_tests.push(s.test);
            });

            function equal_split(n) {
                if (n === 0) return [];
                var base = Math.floor(100 / n), rem = 100 - base * n;
                return Array.from({length: n}, function(_, i) { return base + (i < rem ? 1 : 0); });
            }

            function normalize_selected() {
                var total = selected_tests.reduce(function(s,t){ return s+(store[t]||0); }, 0);
                all_tests.forEach(function(t){
                    if (selected_tests.indexOf(t) < 0) store[t] = 0;
                });
                if (total === 0) {
                    var w = equal_split(selected_tests.length);
                    selected_tests.forEach(function(t,i){ store[t] = w[i]; });
                } else {
                    var scaled = selected_tests.map(function(t){
                        return Math.round((store[t]||0) / total * 100);
                    });
                    var diff = 100 - scaled.reduce(function(a,b){return a+b;}, 0);
                    if (diff) scaled[0] += diff;
                    selected_tests.forEach(function(t,i){ store[t] = scaled[i]; });
                }
            }

            if (tid === 'opt-equal-btn') {
                if (selected_tests.length === 0) return NO_UPDATE;
                var w = equal_split(selected_tests.length);
                all_tests.forEach(function(t){ store[t] = 0; });
                selected_tests.forEach(function(t,i){ store[t] = w[i]; });
                return store;
            }

            if (tid === 'opt-normalize-btn') {
                if (selected_tests.length === 0) return NO_UPDATE;
                normalize_selected();
                return store;
            }

            if (tid && typeof tid === 'object' && tid.type === 'test-check') {
                if (selected_tests.length === 0) {
                    all_tests.forEach(function(t){ store[t] = 0; });
                    return store;
                }
                normalize_selected();
                return store;
            }

            if (tid && typeof tid === 'object' && tid.type === 'weight-slider') {
                var changed_test = tid.test;
                var changed_value = null;
                slider_ids.forEach(function(sid, i) {
                    if (sid.test === changed_test) changed_value = slider_vals[i];
                });
                if (changed_value === null) return NO_UPDATE;

                if (store[changed_test] === changed_value) return NO_UPDATE;
                if (selected_tests.indexOf(changed_test) < 0) return NO_UPDATE;

                var n_sel = selected_tests.length;
                if (n_sel === 1) { store[changed_test] = 100; return store; }

                var old_val = store[changed_test] || 0;
                var new_val = Math.max(0, Math.min(100, Math.round(changed_value)));
                var delta = new_val - old_val;
                if (delta === 0) return NO_UPDATE;

                store[changed_test] = new_val;
                var idx = selected_tests.indexOf(changed_test);
                var remaining = delta;

                for (var step = 1; step < n_sel; step++) {
                    var next_test = selected_tests[(idx + step) % n_sel];
                    var cur = store[next_test] || 0;
                    if (remaining > 0) {
                        var take = Math.min(remaining, cur);
                        store[next_test] = cur - take;
                        remaining -= take;
                    } else {
                        var give = Math.min(-remaining, 100 - cur);
                        store[next_test] = cur + give;
                        remaining += give;
                    }
                    if (remaining === 0) break;
                }
                if (remaining !== 0) store[changed_test] = new_val - remaining;

                all_tests.forEach(function(t) {
                    if (selected_tests.indexOf(t) < 0) store[t] = 0;
                });
                return store;
            }

            return NO_UPDATE;
        }
        """,
        Output("opt-weights-store", "data"),
        Input({"type": "weight-slider", "test": ALL}, "value"),
        Input({"type": "test-check", "test": ALL}, "value"),
        Input("opt-equal-btn", "n_clicks"),
        Input("opt-normalize-btn", "n_clicks"),
        State({"type": "weight-slider", "test": ALL}, "id"),
        State("opt-weights-store", "data"),
        prevent_initial_call=True,
    )

    app.clientside_callback(
        """
        function(store, slider_ids) {
            if (!store) return slider_ids.map(function() { return 0; });
            return slider_ids.map(function(sid) { return store[sid.test] || 0; });
        }
        """,
        Output({"type": "weight-slider", "test": ALL}, "value"),
        Input("opt-weights-store", "data"),
        State({"type": "weight-slider", "test": ALL}, "id"),
    )

    app.clientside_callback(
        """
        function(store, slider_ids, check_vals) {
            var palette = ["#4c8bf5","#e84393","#34a853","#fa7b17",
                           "#9c27b0","#00bcd4","#ff5722","#8bc34a"];
            store = store || {};
            var labels = [], values = [], colors = [];
            slider_ids.forEach(function(sid, i) {
                var w = store[sid.test] || 0;
                if (check_vals[i] && check_vals[i].length > 0 && w > 0) {
                    labels.push(sid.test);
                    values.push(w);
                    colors.push(palette[i % palette.length]);
                }
            });
            var layout = {
                margin: {l:10, r:10, t:30, b:10},
                showlegend: false,
                paper_bgcolor: 'rgba(0,0,0,0)'
            };
            if (labels.length === 0) {
                return {
                    data: [{type:'pie', labels:['none'], values:[1],
                            marker:{colors:['#dee2e6']}, textinfo:'none', hoverinfo:'none'}],
                    layout: layout
                };
            }
            return {
                data: [{
                    type: 'pie', labels: labels, values: values,
                    marker: {colors: colors}, textinfo: 'label+percent',
                    hovertemplate: '%{label}: %{value}%<extra></extra>', hole: 0.35
                }],
                layout: layout
            };
        }
        """,
        Output("opt-pie", "figure"),
        Input("opt-weights-store", "data"),
        State({"type": "weight-slider", "test": ALL}, "id"),
        State({"type": "test-check", "test": ALL}, "value"),
    )

    app.clientside_callback(
        """
        function(store, check_vals, slider_ids) {
            store = store || {};
            var selected_count = check_vals.filter(function(v) {
                return v && v.length > 0;
            }).length;
            var total = 0;
            slider_ids.forEach(function(sid, i) {
                if (check_vals[i] && check_vals[i].length > 0) total += (store[sid.test] || 0);
            });
            var mk = function(txt, cls) {
                return {type:'Span', namespace:'dash_html_components',
                        props:{children: txt, className: cls}};
            };
            if (selected_count === 0)
                return mk('Select at least one test.', 'text-warning');
            if (total !== 100)
                return mk('Selected weights sum to ' + total + '% — must equal 100%.',
                          'text-danger fw-semibold');
            return mk(selected_count + ' test(s) selected · weights OK (total 100%).',
                      'text-success fw-semibold');
        }
        """,
        Output("opt-weight-status", "children"),
        Input("opt-weights-store", "data"),
        Input({"type": "test-check", "test": ALL}, "value"),
        State({"type": "weight-slider", "test": ALL}, "id"),
    )

    @callback(
        Output("opt-status", "children"),
        Input("opt-start-btn", "n_clicks"),
        Input("opt-stop-btn", "n_clicks"),
        State({"type": "test-check", "test": ALL}, "value"),
        State({"type": "test-check", "test": ALL}, "id"),
        State({"type": "gate-check", "test": ALL}, "value"),
        State({"type": "gate-check", "test": ALL}, "id"),
        State("opt-weights-store", "data"),
        prevent_initial_call=True,
    )
    def handle_optimise(_, __, check_vals, check_ids, gate_vals, gate_ids, store):
        from dash import ctx

        if ctx.triggered_id == "opt-stop-btn":
            return _stop_proc("optimize")

        store = store or {}
        test_names: list[str] = []
        test_weights: dict[str, int] = {}
        for checks, cid in zip(check_vals, check_ids):
            if checks:
                name = cid["test"]
                test_names.append(name)
                test_weights[name] = int(store.get(name, 0))

        gated_names: list[str] = []
        for checks, cid in zip(gate_vals, gate_ids):
            if checks:
                name = cid["test"]
                if name in test_names:
                    gated_names.append(name)

        if not test_names:
            return "No tests selected."

        if len(gated_names) == len(test_names):
            return "At least one selected test must stay ungated so the gate can open."

        total = sum(test_weights.values())
        if total != 100:
            return f"Weights must sum to 100% (currently {total}%)."

        env = os.environ.copy()
        env["LAB_SHAPEOPT_TESTS"] = ",".join(test_names)
        env["LAB_SHAPEOPT_TEST_WEIGHTS"] = json.dumps(test_weights)
        if gated_names:
            env["LAB_SHAPEOPT_GATED_TESTS"] = ",".join(gated_names)
        return _start_proc("optimize", OPTIMIZE_SCRIPT, env)

    @callback(
        Output("opt-log", "children"),
        Input("opt-interval", "n_intervals"),
    )
    def update_opt_log(_):
        return _read_proc_log("optimize")

    # ── Performance callbacks ─────────────────────────────────

    @callback(
        Output("trial-detail-panel", "children"),
        Input("performance-graph", "clickData"),
    )
    def on_trial_click(click_data):
        if not click_data:
            return html.Div()
        try:
            point = click_data["points"][0]
            cd = point.get("customdata")
            if not cd or len(cd) < 3:
                return html.Div()
            gen_name, trial_name = cd[1], cd[2]
            if not gen_name or not trial_name:
                return html.Div()
            state = _read_json(TRIALS_DIR / gen_name / trial_name / "trial_state.json")
            if not state:
                return html.Div(
                    "No detail available for this trial.", className="text-muted"
                )
            return _build_trial_detail(state, gen_name, trial_name)
        except Exception as exc:
            return html.Div(f"Could not load trial: {exc}", className="text-muted")

    @callback(
        [
            Output("performance-graph", "figure"),
            Output("leaderboard-table", "children"),
        ],
        Input("tabs", "value"),
        Input("performance-interval", "n_intervals"),
    )
    def update_performance(tab, _):
        records, summaries = _load_data()
        if tab != "performance":
            return go.Figure(), html.Div()
        fig = _build_performance_graph(records, summaries)
        leaderboard = _build_leaderboard_html(records)
        return fig, leaderboard

    @callback(
        Output("param-bounds-graph", "figure"),
        Input("bounds-interval", "n_intervals"),
    )
    def update_bounds(_):
        return _build_param_bounds_graph(show_heatmap=True)

    @callback(
        [Output("progress-stats", "children"), Output("progress-grid", "children")],
        Input("progress-interval", "n_intervals"),
    )
    def update_progress(_):
        records, summaries = _load_data()
        current_records = _current_generation_records(records)
        stats = _build_progress_stats(current_records, records)
        grid = _build_progress_grid(current_records)
        return stats, grid

    @callback(
        Output("jump-running-target-store", "data"),
        Input("jump-running-trial", "n_clicks"),
        Input("progress-interval", "n_intervals"),
        State("jump-auto-enabled", "data"),
    )
    def update_jump_target(_clicks, _intervals, auto_enabled):
        try:
            from dash import ctx
        except Exception:
            ctx = None

        triggered = None
        if ctx is not None:
            triggered = getattr(ctx, "triggered_id", None)

        is_auto = triggered == "progress-interval"

        if is_auto and not bool(auto_enabled):
            return {"target_id": None, "auto": True}

        records, _summaries = _load_data()
        current_records = _current_generation_records(records)
        return {"target_id": _find_earliest_not_done(current_records), "auto": is_auto}

    app.clientside_callback(
        """
        function(target, auto_enabled) {
            if (!target || !target.target_id) {
                return window.dash_clientside.no_update;
            }
            if (target.auto && !auto_enabled) {
                return window.dash_clientside.no_update;
            }
            const el = document.getElementById(target.target_id);
            if (el) {
                el.scrollIntoView({behavior: 'smooth', block: 'center'});
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output("jump-running-target-output", "children"),
        Input("jump-running-target-store", "data"),
        State("jump-auto-enabled", "data"),
    )

    app.clientside_callback(
        """
        function(n_intervals, auto_enabled) {
            if (!window._ajScrollListenerReady) {
                window._ajUserScrolled = false;
                var mark = function() { window._ajUserScrolled = true; };
                window.addEventListener('wheel',     mark, {passive: true});
                window.addEventListener('touchmove', mark, {passive: true});
                window.addEventListener('keydown', function(e) {
                    if ([' ','ArrowUp','ArrowDown','PageUp','PageDown','Home','End'].includes(e.key)) {
                        window._ajUserScrolled = true;
                    }
                }, {passive: true});
                window._ajScrollListenerReady = true;
            }
            if (!auto_enabled) {
                window._ajUserScrolled = false;
                return window.dash_clientside.no_update;
            }
            if (window._ajUserScrolled) {
                window._ajUserScrolled = false;
                return false;
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output("jump-auto-enabled", "data", allow_duplicate=True),
        Input("progress-interval", "n_intervals"),
        State("jump-auto-enabled", "data"),
        prevent_initial_call=True,
    )

    app.clientside_callback(
        """
        function(n) {
            if (!n) { return window.dash_clientside.no_update; }
            window.scrollTo({top: 0, behavior: 'smooth'});
            return false;
        }
        """,
        Output("jump-auto-enabled", "data", allow_duplicate=True),
        Input("jump-top-button", "n_clicks"),
        prevent_initial_call=True,
    )

    app.clientside_callback(
        "function(n) { return window.dash_clientside.no_update; }",
        Output("jump-top-output", "children"),
        Input("jump-top-button", "n_clicks"),
    )

    app.clientside_callback(
        "function(n, cur) { if (!n) return window.dash_clientside.no_update; return !cur; }",
        Output("jump-auto-enabled", "data", allow_duplicate=True),
        Input("jump-auto-toggle", "n_clicks"),
        State("jump-auto-enabled", "data"),
        prevent_initial_call=True,
    )

    app.clientside_callback(
        'function(on) { return on ? "Auto-jump: On" : "Auto-jump: Off"; }',
        Output("jump-auto-toggle", "children"),
        Input("jump-auto-enabled", "data"),
    )

    return app


# ─────────────────────────────────────────────────────────────
# Launch
# ─────────────────────────────────────────────────────────────


def launch_dashboard(port: int = 8050, open_browser: bool = True) -> None:
    """Start the ShapeOPT dashboard web server and optionally open a browser.

    Args:
        port: Port to bind the web server to.
        open_browser: If True, open the dashboard in the default browser.
    """
    print(f"[info] Starting ShapeOPT on http://localhost:{port}")

    os.environ["WERKZEUG_RUN_MAIN"] = "false"
    os.environ.pop("WERKZEUG_SERVER_FD", None)

    app = create_app()
    launch_url = f"http://localhost:{port}/?v={int(time.time())}"

    if open_browser:

        def open_browser_delayed():
            time.sleep(2)
            webbrowser.open_new_tab(launch_url)

        thread = threading.Thread(target=open_browser_delayed, daemon=True)
        thread.start()

    app.run(debug=False, use_reloader=False, port=port, host="127.0.0.1")


if __name__ == "__main__":
    launch_dashboard()
