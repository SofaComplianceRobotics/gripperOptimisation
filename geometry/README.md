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

**`quaternion.py`** — quaternion math and frame rotations between CadQuery's Z-up convention and SOFA's Y-up frame.

**`leg_params.py`** — `LegParams` dataclass: tunable shape of the Emio leg as a single-span Bezier spline (4 searchable params, all `leg_`-prefixed to avoid colliding with `ModelParams`'s identically-shaped pincer spline fields): a start point (fixed, end of the motor-wrap arc) with a tunable outgoing handle length, and a free end point (polar from the start, matching `params.py`'s pincer spline convention and reusing its `p1_dist`/`p1_angle_deg`/`p1_hin_dist` names) with a tunable incoming handle length. The start point's outgoing handle and the end point's incoming handle keep their *angle* fixed vertical (only length is tunable) so the joins with the fixed motor-wrap arc and the fixed straight tip run stay smooth; the end point's *position* is otherwise fully free — not pinned to the gripper's stock lateral offset. The cross-section is fixed at the stock 10×5 the gripper pocket was designed for. The default parameter set reproduces the stock blueleg exactly — a straight leg. Same metadata convention as `params.py` (`"opt"` for search bounds, `"check"` for validation), its own `param_specs()`/`validate_params()`. One leg shape is generated per trial and reused for all four attachments — there's no separate leg test; the shared grasp/tilt/cube-pick tests score the assembled gripper+legs together (see `sofaopt_project.py`'s `prepare_trial` hook).

**`leg_geometry.py`** — `build_leg(LegParams) -> LegCenterline`: follows the platform's own leg recipe (see the lab_design lab): a fixed quarter-wrap around the motor pulley (hardware constants `PULLEY_RADIUS`/`STRAIGHT_OFFSET` measured off the stock blueleg), a tunable single-span spline built directly from `LegParams`'s polar points/handles, and a fixed straight vertical tip run continuing from wherever the spline's end point lands. Exposes `get_beams()` (Rigid3 frames, same convention as `blueleg.txt`) and `export_stl()`/`export_positions()` (the `<name>.stl`/`<name>.txt` pair `parts.leg.Leg` expects in `data/meshes/legs/`). The STL fuses `data/attachmotor.brep` — the exact motor clip (snap bumps included) extracted from the platform's `leg-cad.FCStd` — so every generated leg physically attaches to a motor. Requires `beziers` and `scipy`; STL export additionally needs cadquery/OCP.

**`data/attachmotor.brep`** — static motor-attachment clip solid, extracted once from `assets/data/meshes/legs/leg-cad.FCStd` (the `attachmotor` body), already positioned in the leg frame.

---

## io/ subpackage

- `export_mesh.py` — CadQuery → STL/VTK via Gmsh, including collision mesh variants
- `export_json.py` — serializes leg attachment poses and config to JSON for SOFA
- `paths.py` — resolves and creates versioned export directories

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
