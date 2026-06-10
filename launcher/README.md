# launcher/

Entry-point scripts that bootstrap the runtime environment and start the lab.

---

## Scripts

**`launch_web.py`** — the single entry point called from the EmioLabs platform button and from the terminal.

Sets up the two SOFA environments before handing off to the dashboard:
- **EmioLabs SOFA** (`EMIOLABS_RUNSOFA_EXE`) — the platform-bundled build used for interactive scenes with ImGui and hardware connection.
- **Custom headless SOFA** (`RUNSOFA_EXE`, `SOFA_ROOT`) — a separate batch-mode build used for optimization runs (Python 3.12, no GUI).

Clears `PYTHONHOME` / `PYTHONSTARTUP` / `PYTHONUSERBASE` / `PYTHONEXECUTABLE` that EmioLabs injects, which would otherwise leak into SOFA subprocesses and break their Python interpreter.

Calls `dashboard.app.launch_dashboard(port=8050, open_browser=True)`.

**`bootstrap.py`** — `bootstrap_lab(script_file)` → `(script_dir, src_root, app_root, lab_root)`

Used by every scene file and launcher script to locate the lab root and ensure imports work regardless of how SOFA or the platform launched the script. Walks up from `__file__` until it finds a directory containing both `config/lab_config.jsonc` and `runtime/`. Adds `lab_root` and `runtime/modules/site-packages` to `sys.path`.

```python
from launcher.bootstrap import bootstrap_lab
SCRIPT_DIR, SRC_ROOT, APP_ROOT, LAB_ROOT = bootstrap_lab(__file__)
```

---

## Usage

```bash
python launcher/launch_web.py
```

Or from the EmioLabs platform — the page button points directly at this script.
