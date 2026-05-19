# generation/

Entry points for turning a config file into gripper mesh files. Scripts here read `config/lab_config.jsonc`, build a `ModelParams`, and hand off to `core/export_pipeline.py`.

---

## Scripts

**`generate_gripper.py`** — Standard generation. Reads the active config and exports the simulation-resolution mesh (STL + VTK + leg attachment JSON). This is what the optimizer calls for every trial, and what the EmioLabs UI button triggers.

**`generate_gripper_fine.py`** — Same flow but outputs a much finer mesh intended for 3D printing. Writes `new_gripper_print.stl` separately so it doesn't overwrite the coarser simulation mesh. Run this manually when you want to print a design.

**`_gripper_common.py`** — Shared bootstrap used by both scripts above. Handles: JSONC config loading (strips `//` comments), `ModelParams` construction from the config dict, and `ensure_cadquery_runtime()` which installs CadQuery from `runtime/` if it isn't available in the active environment. Prefixed with `_` — not a public entry point.

---

## How config maps to geometry

`config/lab_config.jsonc` keys map directly to `ModelParams` fields defined in `core/params.py`. Any key in the config that matches a field name overrides the default. Unknown keys are ignored. The optimizer writes its own config values through this same path.
