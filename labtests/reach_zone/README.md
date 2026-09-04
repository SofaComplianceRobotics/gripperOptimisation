# labtests/reach_zone/

Inverse-mode workspace test: how much volume can the gripper+leg combo
actually reach?

`scene.py` sweeps a fixed stack of horizontal grids from `Y_MIN` to `Y_MAX`.
Within each grid it commands every `(x, z)` point of a fixed square once and
keeps the settled TCP position, on target or not. Stacking the grids traces a
real 3D reachable boundary; the score is the volume that boundary encloses.

---

## Files

**`scene.py`** — the sweep and `ReachZoneController`. Under the optimizer it
runs headless and writes the score, nothing else.

**`geometry.py`** — sweep constants, the reachable-mesh construction, and the
`zone_result.json` path. Shared with `view_scene.py`. `zone_result.json` is a
regenerated artifact (git-ignored), not a committed input.

**`view_scene.py`** — standalone viewer, **not** a registered test (no
`test.json` / `scoring.py`). On a manual launch, `scene.py` relaunches itself
headless to run the sweep at full speed, then hands off to this to show the
finished zone next to the robot at rest. All of that is skipped under the
optimizer — it's a viewing convenience, not part of the score.
