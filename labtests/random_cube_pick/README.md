# labtests/random_cube_pick/

Variant of `grasp_hold`: same motor recording, same controller, but the cube size and mass change across runs and scores are based on a binary-search weight ladder rather than raw hold time.

---

## How scoring works

Three runs per trial, one cube size per run:

| Slot | Cube scale |
|---|---|
| 1 | 8 × 8 × 8 mm |
| 2 | 10 × 10 × 10 mm |
| 3 | 20 × 20 × 20 mm |

Each slot independently searches for the heaviest cube the gripper can pick up using a binary-search ladder over a configurable weight range (default 0.02 – 0.2 kg, 0.05 kg steps → 5 levels). A successful pickup advances the lower bound; a failure retreats the upper bound. Once the ladder converges, the slot's score is the ladder boundary index (1–10 points). Total max score: 30 points.

---

## Carryover across generations

After each generation the best discovered ladder index per slot is saved to `runtime/random_cube_pick_seed_weights.json`. The next generation warm-starts the binary search from those indices instead of the midpoint. This means the search narrows faster as the optimizer progresses — early generations explore broadly, later generations refine.

**`carryover.py`** — `load_seed_indices(lab_root)` / `save_seed_indices(lab_root, indices)`. Reads and writes `seed_weights.json`.

---

## weight_search/ subpackage

All ladder math is isolated here so `scene.py` stays thin.

| Module | What it does |
|---|---|
| `common.py` | `CubeSearchSpec` dataclass, `DEFAULT_WEIGHT_*` constants, `_CUBE_SIZE_CYCLE`, scoring helpers |
| `ladder.py` | `_build_weight_levels()`, `_choose_index()` (binary search midpoint), `build_search_snapshot()` (dashboard display) |
| `state.py` | Per-slot state resolution — reads raw JSON state and returns structured slot progress |
| `persistence.py` | File I/O for `random_cube_pick_weight_search.json` |
| `api.py` | Public surface: `select_cube_spec()`, `record_cube_result()`, `build_search_snapshot()` — these are the only functions `scene.py` imports |

---

## scene.py responsibilities

- Picks `cube_scale` and `cube_mass` for the current slot via `select_cube_spec()`
- Overrides `_initial_cube_mass()` to fix the mass (no ramp — keeps the probe fair)
- Overrides `_update_overload_mass()` to hold mass constant
- Overrides `_finish_run()` to call `record_cube_result()` and either continue to the next run or stop when the ladder converges
