# labtests/random_cube_pick/

Variant of `grasp_hold`: identical motor recording, controller, scoring and
overload behaviour, but the cube size changes per run slot.

---

## How scoring works

Three runs per trial, one cube size per run, each lifted once at the standard
`grasp_hold` cube weight (`cube_mass_start`):

| Slot | Cube scale |
|---|---|
| 1 | 8 × 8 × 8 mm |
| 2 | 10 × 10 × 10 mm |
| 3 | 12 × 12 × 12 mm |

Each run is scored by hold time exactly like `grasp_hold` (max 8.06 per run).
The trial score is the sum across the three sizes (`score_aggregation: sum`),
for a maximum of 24.18 points.

---

## scene.py responsibilities

- Picks `cube_scale` for the current slot from `CUBE_SIZES` (slots are
  1-indexed; the optimizer launches slots 1..3).
- Cube mass, overload ramp and hold-time scoring all come from core, same as
  `grasp_hold`.
- Overrides `_on_horizon_complete()` only: holding the cube to the end of the
  timeline is scored by hold time (a success), not pruned. The base prunes at
  the horizon because `grasp_hold` expects its overload ramp to force a drop
  first; here the gripper can simply hold the cube the whole way.
