"""Dashboard callbacks for optimisation controls."""

from __future__ import annotations

import json
import os

from dash import ALL, Input, Output, State, ctx

from dashboard.process.process_manager import (
    OPTIMIZE_SCRIPT,
    _read_proc_log,
    _start_proc,
    _stop_proc,
)


def register_optimise_callbacks(app) -> None:
    """Register optimise tab callbacks: weight store, sliders, pie chart, and run/stop."""

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

    @app.callback(
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
        """Validate selections and launch or stop the optimization subprocess.

        Builds ``OPT_SELECTED_TESTS``, ``OPT_TEST_WEIGHTS``, and
        ``OPT_GATED_TESTS`` env vars from the current UI state before
        handing off to the process manager.

        Args:
            _: Start button click count (unused directly; ``ctx.triggered_id`` used).
            __: Stop button click count (unused directly).
            check_vals: List of checklist values per test (truthy = selected).
            check_ids: List of dicts with ``"test"`` key, one per test row.
            gate_vals: List of checklist values for gate toggles.
            gate_ids: List of dicts with ``"test"`` key for gate checkboxes.
            store: Dict mapping test name → weight int from the weights store.

        Returns:
            Status message string describing the outcome or a validation error.
        """
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
        env["OPT_SELECTED_TESTS"] = ",".join(test_names)
        env["OPT_TEST_WEIGHTS"] = json.dumps(test_weights)
        if gated_names:
            env["OPT_GATED_TESTS"] = ",".join(gated_names)
        return _start_proc("optimize", OPTIMIZE_SCRIPT, env)

    @app.callback(
        Output("opt-log", "children"),
        Input("opt-interval", "n_intervals"),
    )
    def update_opt_log(_):
        """Poll and return the current optimization subprocess log.

        Args:
            _: Interval tick (unused).

        Returns:
            Log contents as a string.
        """
        return _read_proc_log("optimize")