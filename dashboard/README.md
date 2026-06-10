# dashboard/

Dash web control panel for the lab: edit the config, trigger generation, launch scenes, start/stop the optimizer, and monitor results live.

Entry point: `python launcher/launch_web.py` (which calls `dashboard.app.launch_dashboard`).

---

## Top-level modules

**`app.py`** — Dash app factory and launch. Builds the layout (header, tab strip, tab cards), registers all callbacks, opens the browser, and starts the server.

**`analyze_config.py`** — Constants shared across the dashboard: paths, `TOP_X` (leaderboard size), rolling window size, live refresh interval, score aggregation mode.

**`analyze_io.py`** — Loads `trial_state.json` files from `runtime/trials/` and aggregates them into trial records. Core data pipeline for all views.

---

## Subpackages

**`data/`** — Data loading and caching layer.
- `cache.py` — Caches trial records, generation summaries, and `trial_state.json` reads to avoid redundant disk I/O on each refresh.

**`plotting/`** — Plotly figure construction.
- `colors.py` — The color palette (UI accent and plot series colors live here).
- `compute.py` — Rolling averages, best-so-far curves, score math.
- `traces.py` — Builds Plotly traces (lines, bars, scatter) from computed data.
- `performance.py` — Assembles the full performance figure (score history + per-test contribution bars).
- `bounds.py` — Parameter-bounds figure, driven by `geometry.params.param_specs()`.

**`process/`** — Subprocess management.
- `process_manager.py` — Starts and stops the generation/optimization subprocesses and launches SOFA scenes from the UI.

**`callbacks/`** — `@app.callback` registration only, no HTML. One `register_*_callbacks(app)` function per tab. `app.py` calls these after building the layout.

**`ui/`** — Dash layout builders only, no callbacks.
- `ui/tabs/` — One `build_*_tab()` function per tab. Each tab has a matching file in `callbacks/` that wires its interactivity.
- `ui/tabs/styles.py` — Shared style constants (app shell, tab strip, log panes).
- `ui/progress/` — Progress view: helpers that read trial state and builders that turn it into Dash HTML.

---

## Dashboard tabs

| Tab | What it shows |
|---|---|
| Config | Edit `lab_config.jsonc` and save to disk |
| Generate | Trigger gripper generation, show output log |
| Scenes | Launch SOFA scenes (inverse, recording, watch-a-test) |
| Optimise | Pick tests/weights, start/stop the optimization loop, live log |
| Performance | Score history, rolling avg, best-so-far, per-test contribution bars |
| Progress | Live per-trial grid for the current generation |
| Parameter Bounds | Where recent trials sit inside each parameter's search range |
