# config/

Gripper parameter files. The optimizer and generation scripts both read `lab_config.jsonc` as the active configuration.

---

## Files

**`lab_config.jsonc`** — the live config. This is the file that matters.

Read by `generation/_gripper_common.py` to build a `ModelParams` and generate a mesh. Written by the optimizer for each trial with the candidate parameter values. Supports `//` line comments (JSONC format) — these are stripped before JSON parsing.

**`lab_config_working.jsonc`** — a manually saved working baseline.

Not read by any script automatically. Use it as a known-good backup: copy it to `lab_config.jsonc` to restore a baseline before starting a new optimization run, or as a reference when the optimizer has overwritten the active config.

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
