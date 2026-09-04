# config/

Gripper parameter files.

---

## Files

**`lab_config.jsonc`** — the live, hand-edited config: the one gripper you'd
build right now.

The `generation/` scripts read it (via `_gripper_common.load_jsonc`) when run
with no `--config` argument — i.e. from the dashboard Generate button, the
Config tab, or a bare `python generation/generate_gripper.py`. Supports `//`
line comments (JSONC); they're stripped before parsing.

The optimizer does **not** use this file. Each trial gets its own
`params.json` (written by sofaopt into the trial directory) and the
generation scripts are pointed at that with `--config`.

**`lab_config.optimization.json`** — the search-space selection: a
`{"optimized_params": [...]}` list of the `ModelParams` / `LegParams` field
names the optimizer is allowed to vary. `sofaopt_project.py` reads it and,
for every searchable field *not* in the list, collapses its range to a single
point (`low == high`) so sofaopt freezes it at its **`params.py` /
`leg_params.py` default** (not its `lab_config.jsonc` value — the two files
are unrelated). Bool params stay searchable regardless. Edit it from the
dashboard's Parameters tab, or by hand.

This file has nothing to do with `lab_config.jsonc`. It is not touched during
a run, and the optimizer does not seed from it — CMA-ES centres its search on
the dataclass defaults.

---

## Format

Keys map directly to `ModelParams` fields defined in `geometry/params.py`. Any field name works (except output naming, which is fixed in `names.py`). Unknown keys are silently ignored. Missing keys use the dataclass defaults.

```jsonc
{
  // Ring geometry
  "cylinder_radius": 27.2,
  "cylinder_hole_thickness": 3.4,

  // Pincer spline control points
  "p1_dist": 45,
  "p1_angle_deg": -33.8,

  // Mesh resolution
  "mesh_collision_size": 90.0
}
```

To see all available keys, their search ranges, and their validity rules, refer to `geometry/params.py` — each field carries `opt` and `check` metadata.
