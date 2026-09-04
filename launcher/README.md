# launcher/

Entry-point scripts that bootstrap the runtime environment and start the lab.

---

## Scripts

**`launch_web.py`** — the single entry point, called from the EmioLabs
platform button and from the terminal. Before handing off to the dashboard it:

- Resolves the **one** SOFA build — the emio-labs one — via
  `resolve_sofa_runtime(prefer_env=False)`, and exports every path the
  subprocesses need (`SOFA_ROOT`, `RUNSOFA_EXE`, `SOFA_PYTHON_PATH`,
  `SOFA_PYTHON_EXE`, `SOFA_SITE_PACKAGES`, `EMIOLABS_RUNSOFA_EXE`) pointing at
  it. `prefer_env=False` means a stale machine-wide `SOFA_ROOT` / `RUNSOFA_EXE`
  is ignored, so the optimizer's headless runs and the interactive scenes are
  guaranteed the same physics build (only `EMIOLABS_SOFA_ROOT` overrides).
- Clears `PYTHONHOME` / `PYTHONSTARTUP` / `PYTHONUSERBASE` / `PYTHONEXECUTABLE`,
  which EmioLabs injects and which would otherwise leak into the SOFA
  subprocesses and break their interpreter.

Then calls `dashboard.app.launch_dashboard(port=8050, open_browser=True)`.

**`install_deps.py`** — the lab's "install dependencies" `#python-button`.
EmioLabs runs it with the bundled Python already first on PATH, so
`sys.executable` is already correct. Installs sofaopt and the pinned
geometry/dashboard stack; idempotent, safe to re-run after a `git pull`.

**`bootstrap.py`** — two helpers used everywhere:
- `bootstrap_lab(script_file)` → `(script_dir, src_root, app_root, lab_root)`.
  Walks up from `__file__` until it finds a directory holding both
  `config/lab_config.jsonc` and `runtime/`, then puts `lab_root` and
  `modules/site-packages` on `sys.path`. Every scene file and launcher starts
  with it.
- `resolve_sofa_runtime()` — locates the runSofa executable and SOFA root for
  the current machine.

```python
from launcher.bootstrap import bootstrap_lab
SCRIPT_DIR, SRC_ROOT, APP_ROOT, LAB_ROOT = bootstrap_lab(__file__)
```

---

## Usage

```bash
python launcher/launch_web.py
```

Or from the EmioLabs platform — the lab page button points at this script.
