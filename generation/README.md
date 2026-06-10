# generation/

Entry points for turning a config file into gripper mesh files. Scripts here read `config/lab_config.jsonc`, build a `ModelParams`, and hand off to `geometry/export_pipeline.py`.

---

## Scripts

**`generate_gripper.py`** — Standard generation. Reads the active config and exports the simulation-resolution mesh (STL + VTK + leg attachment JSON). This is what the optimizer calls for every trial, and what the EmioLabs UI button triggers.

**`generate_gripper_fine.py`** — Same flow but outputs a much finer mesh intended for 3D printing. Writes the print STL under a separate name (see `names.py`) so it never overwrites the coarser simulation mesh. Run this manually when you want to print a design.

**`_gripper_common.py`** — Shared bootstrap used by both scripts above:
- `load_jsonc()` — JSONC loading; strips `//` comments without touching `//` inside string values
- `params_from_config()` — generic config→`ModelParams` mapping (see below)
- `ensure_cadquery_runtime()` — verifies CadQuery is importable (current env or `runtime/modules/site-packages`), with an actionable error if not

Prefixed with `_` — not a public entry point.

---

## How config maps to geometry

Every `ModelParams` field name found in the config is applied, coerced to the type of the field's default. Unknown keys are ignored; missing keys keep their defaults. Exceptions: `export_dir`/`export_stem` are never read from config (output naming is a code-level contract in `names.py`), and `mesh_enabled`/`mesh_show_viewer` are always forced for batch generation. The optimizer writes its own per-trial config through this same path.
