# dashboard/

The lab's own dashboard tabs, layered onto sofaopt's project dashboard.

sofaopt supplies the generic tabs (Config, Run, Monitor, Parameters,
Results, Archives) and the web server. This package adds three lab-specific
tabs and wires them in through `extra_tabs`.

Entry point: `python launcher/launch_web.py` → `dashboard.app.launch_dashboard`.

---

## Modules

**`app.py`** — the dashboard entry point. Defines `LAB_TABS` (the three
`DashboardTab` specs below) and `launch_dashboard()`, which calls
`sofaopt.dashboard.app.launch_dashboard` with `PROJECT` from
`sofaopt_project.py` and `extra_tabs=LAB_TABS`.

**`tabs/`** — layout builders, one `build_*_tab()` per tab, no callbacks.
- `generate.py` — Generate tab: buttons for the sim-mesh and fine-mesh
  generators, buttons to open the output STLs, and a log pane.
- `scenes.py` — Scenes tab: "watch a test" picker plus the inverse-kinematics
  and motor-recording scene launchers.
- `param_guide.py` — Parameter Guide tab: one collapsible entry per documented
  parameter with its description and a low/high render pair. Bounds are read
  live from the project's `ParamSpec` list; prose and images live in
  `PARAM_DOCS` and `dashboard/param_guide_images/`. Also registers the
  `/param-doc-image` route.

**`callbacks/`** — `@app.callback` registration only, no HTML. One
`register_*_callbacks(app)` per tab, called by `app.py` after the layout is
built.
- `generation.py` — Generate/fine/stop buttons, open-output buttons, log tail.
- `scenes.py` — scene launch buttons; writes `runtime/session_config.json`
  before launching the recorder, and drives `run_trajectory_recorder`.

**`process/process_manager.py`** — starts and stops the Generate-tab
subprocesses (the persistent `generation/worker.py`, the cold
`generate_all.py` fallback, the fine generator) and launches the interactive
SOFA scenes. Writes its logs to the top-level `logs/` directory. The
optimizer's Run/Stop is sofaopt's, not here.

---

## Tabs in the running dashboard

| Tab | Owner | What it does |
|---|---|---|
| Config | sofaopt | Edit `lab_config.jsonc` |
| **Generate** | lab | Run the geometry generators, open their output |
| **Scenes** | lab | Launch inverse / recording scenes, watch one test |
| Run | sofaopt | Pick tests + weights, start/stop the optimizer |
| Monitor | sofaopt | Live per-trial grid for the current generation |
| **Parameter Guide** | lab | Plain-language notes on each tunable parameter |
| Parameters | sofaopt | Where recent trials sit in each search range |
| Results | sofaopt | Leaderboard, score history, best-so-far |
| Archives | sofaopt | Past runs archived from `runtime/` |

The three lab tabs are inserted `before="run"`, so they sit right after
Config in the strip.
