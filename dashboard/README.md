# analysis/

Dash web dashboard for monitoring and reviewing optimization results. Shows live progress, score history, trial leaderboard, per-trial breakdowns, and config inspection.

Entry point: `python analysis/app.py`

---

## Top-level modules

**`app.py`** — Dash app factory and launch. Builds the full layout, registers all callbacks, opens the browser, and starts the Flask dev server. This is what `launcher/launch_web.py` calls.

**`analyze_config.py`** — Constants shared across the analysis package: paths, `TOP_X` (leaderboard size), rolling window size, live refresh interval, score aggregation mode.

**`analyze_io.py`** — Loads `trial_state.json` files from `runtime/trials/` and aggregates them into trial records. Core data pipeline for all views.

**`analyze_leaderboard.py`** — Ranks trials by score, computes per-generation failure stats. Used for the leaderboard tab and CLI output.

**`analyze_plotting.py`** — Entry point for the performance chart. Calls into `plotting/` to build the Plotly figure shown in the dashboard.

---

## Subpackages

**`data/`** — Data loading and caching layer.
- `cache.py` — Caches trial records, generation summaries, and `trial_state.json` reads to avoid redundant disk I/O on each refresh.

**`plotting/`** — Plotly figure construction.
- `compute.py` — Rolling averages, best-so-far curves, score math.
- `traces.py` — Builds Plotly traces (lines, bars, scatter) from computed data.
- `performance.py` — Assembles the full performance figure (score history + per-test contribution bars).
- `colors.py` / `bounds.py` — Color palette and axis bounds helpers.

**`process/`** — Subprocess management.
- `process_manager.py` — Starts and stops the generation and optimization subprocesses from the dashboard UI (the "Run" buttons).

**`callbacks/`** — `@app.callback` registration only, no HTML. One `register_*_callbacks(app)` function per tab. `app.py` calls these after building the layout.

**`ui/`** — Dash layout builders only, no callbacks.
- `ui/tabs/` — One `build_*_tab()` function per tab. Each tab has a matching file in `callbacks/` that wires its interactivity.
- `ui/tabs/styles.py` — Shared inline CSS constants.
- `ui/progress/` — Progress bar component: helpers that read `progress.json` and builders that turn it into Dash HTML.

---

## Dashboard tabs

| Tab | What it shows |
|---|---|
| Performance | Score history over trials, rolling avg, best-so-far, per-test contribution bars |
| Progress | Live progress bar, current gen/trial, estimated time remaining |
| Config | Current `lab_config.jsonc` parameters |
| Generate | Trigger gripper generation, show output log |
| Optimise | Start/stop the optimization loop, show live log |
| Scenes | Launch SOFA scenes directly |
