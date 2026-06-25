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

Each run is scored by hold time exactly like `grasp_hold`. The trial score is
the sum across the three sizes (`score_aggregation: sum`). `MAX_SCORE` is
derived in `scoring.py` from the recording length plus overload time (minus the
pre-pickup gate), so a perfect hold across all three sizes normalizes to 1.0
regardless of how the scene timing is tuned.

---

## scene.py responsibilities

- Picks `cube_scale` for the current slot from `CUBE_SIZES` (slots are
  1-indexed; the optimizer launches slots 1..3).
- Cube mass, overload ramp and hold-time scoring all come from core, same as
  `grasp_hold`. Holding the cube to the end of the timeline is scored by hold
  time (a success).
