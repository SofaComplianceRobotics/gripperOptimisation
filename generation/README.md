# generation/

Turns `config/lab_config.jsonc` into gripper and leg mesh files. Each script
reads the active config, builds a `ModelParams` / `LegParams`, and hands off
to `geometry/`.

---

## Entry points

**`generate_gripper.py`** — standard gripper generation. Exports the
simulation-resolution mesh (STL + VTK + leg-attachment JSON) into
`runtime/exports/` and the per-finger collision STLs into the centerparts
mesh dir. This is what every optimizer trial runs.

**`generate_leg.py`** — generates one leg: beam positions (`.txt`) + visual
mesh (`.stl`) into `assets/data/meshes/legs/`, in the format the EmioLabs
`parts.leg.Leg` prefab expects.

**`generate_all.py`** — the dashboard "Generate" button. Runs
`generate_gripper.py` and `generate_leg.py` concurrently (disjoint outputs)
so one click produces both parts. Prints each script's output under a
`--- <script> ---` header; writes no files of its own.

**`generate_gripper_fine.py`** — same as `generate_gripper.py` but a much
finer mesh for 3D printing, written under a separate name (`names.py`) so it
never overwrites the simulation mesh. Run it by hand when you want to print a
design.

**`preview.py`** — build the gripper and/or leg from the current config (with
optional `--set key=value` overrides) and render a PNG under
`runtime/previews/`. A quick visual check, no simulation.

```bash
python generation/preview.py                 # gripper + leg, side by side
python generation/preview.py --part gripper
python generation/preview.py --part leg --set leg_p1_dist=140
```

`sofaopt_project.py` imports this module's `render_mesh_grid` for its
per-trial thumbnails, so a manual preview and a trial thumbnail match.

---

## Internal

**`worker.py`** — a persistent version of `generate_all.py` kept alive by the
dashboard so repeated Generate clicks skip the ~1.3 s of Python start-up and
`import cadquery`. Same outputs; the dashboard falls back to the cold
`generate_all.py` subprocess if the worker misbehaves.

**`_gripper_common.py`** — shared bootstrap (prefixed `_`, not an entry point):
- `load_jsonc()` — JSONC load; strips `//` comments without touching `//`
  inside strings
- `params_from_config(cfg, base, fine=False)` — generic config → dataclass
  mapping
- `ensure_cadquery_runtime()` — verify CadQuery is importable (active env or
  `modules/site-packages`), with an actionable error if not

---

## How config maps to geometry

Every `ModelParams` / `LegParams` field named in the config is applied,
coerced to the type of the field's default. Unknown keys are ignored; missing
keys keep their defaults. Exceptions: `export_dir` / `export_stem` are never
read from config (output naming is a code-level contract in `names.py`), and
the `mesh_enabled` / `mesh_show_viewer` flags are forced for batch
generation. The optimizer writes its own per-trial config through this same
path.
