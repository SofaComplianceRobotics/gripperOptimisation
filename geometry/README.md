# geometry/

Parametric geometry engine. Defines the gripper's shape, assembles its parts, and exports the meshes that SOFA consumes. Everything else in the project either feeds parameters into this or reads the files it produces.

---

## Modules

**`params.py`** — `ModelParams` dataclass: the single source of truth for all tunable gripper parameters. Each field carries its complete description in metadata:
- `"opt": {type, min, max}` — search range read by the optimizer (min == max == 0 means frozen)
- `"check"` — validity rule enforced by `validate_params()` (`"positive"`, `"non_negative"`, `("ge", n)`, ranges), optionally gated with `"check_if"`

Also home to `param_specs()` (derives the optimizer/dashboard spec list from the metadata) and `validate_params()` (generic per-field checks + hand-written cross-field geometric constraints). Adding a parameter here makes it config-settable, searchable, displayed, and validated with no other edits.

**`gripper_geometry.py`** — builds the ring and leg attachments. **`gripper_pincers.py`** — builds the pincer pair (visual and collision variants). Each function returns a CadQuery solid.

**`gripper_parts.py`** — public re-export facade over the two builder modules.

**`geometry_helpers.py`** — low-level geometric primitives shared across part construction: spline profiles, annular sectors, vertical drop faces.

**`assembly.py`** — fuses ring, leg attachments, and pincers into the complete gripper solid.

**`export_pipeline.py`** — entry point for the full export. `run_export(params)` goes from a `ModelParams` to STL/VTK/JSON files on disk.

**`timing_config.py`** — central DT (timestep) constants for all SOFA scenes.

---

## Submodules

**`io/`**
- `export_mesh.py` — CadQuery → STL/VTK via Gmsh, including collision mesh variants
- `export_json.py` — serializes leg attachment poses and config to JSON for SOFA
- `paths.py` — resolves and creates versioned export directories

**`transforms/`**
- `quaternion.py` — quaternion math and frame rotations between CadQuery's Z-up convention and SOFA's Y-up frame

---

## Data flow

```
ModelParams  (validated, then)
    └── assembly.py         builds CadQuery solid
    └── export_pipeline.py  drives the export
            ├── io/export_mesh.py   → STL, VTK (via Gmsh)
            ├── io/export_json.py   → leg attachment JSON
            └── io/paths.py         → versioned output dir
```

Output file names come from `names.py` at the lab root — the contract shared with the optimizer and the SOFA scenes.
