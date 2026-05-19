# core/

Parametric geometry engine. Defines the gripper's shape, assembles its parts, and exports the meshes that SOFA consumes. Everything else in the project either feeds parameters into this or reads the files it produces.

---

## Modules

**`params.py`** — `ModelParams` dataclass. The single source of truth for all tunable gripper parameters (~25 fields: ring dimensions, leg geometry, pincer spline points, tilt angles, etc.). Each field carries `opt` metadata (type, min, max) that the optimizer reads to build its search space. Immutable (frozen dataclass) so it can be passed around safely.

**`gripper_parts.py`** — Builds the individual geometric components: the mounting ring, leg attachments, and pincer pairs. Each function returns a CadQuery solid. These are the raw pieces that `assembly.py` combines.

**`geometry_helpers.py`** — Low-level geometric primitives shared across part construction: spline profiles, annular sectors, vertical drop faces, etc.

**`assembly.py`** — Takes the parts from `gripper_parts.py` and fuses them into a single complete gripper model ready for export.

**`export_pipeline.py`** — Entry point for the full export. Calls assembly, then runs the mesh export chain. Call `run_export(params)` to go from a `ModelParams` to files on disk.

**`timing_config.py`** — Central DT (timestep) constants for all SOFA scenes. Three values: `DT_INVERSE` (manual/recording), `DT_DIRECT` (optimization runs), `DT_CONTACT` (brief contact-settling phase after cube spawn). Change here, all scenes update.

---

## Submodules

**`io/`**
- `export_mesh.py` — CadQuery → STL/VTK via Gmsh, including collision mesh variants
- `export_json.py` — Serializes leg attachment poses and config to JSON for SOFA
- `paths.py` — Resolves and creates versioned export directories

**`transforms/`**
- `quaternion.py` — Quaternion math and frame rotations between CadQuery's Z-up convention and SOFA's coordinate frame

---

## Data flow

```
ModelParams
    └── assembly.py         builds CadQuery solid
    └── export_pipeline.py  drives the export
            ├── io/export_mesh.py   → STL, VTK (via Gmsh)
            ├── io/export_json.py   → leg_attachments.json
            └── io/paths.py         → versioned output dir
```
