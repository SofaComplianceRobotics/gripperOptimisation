# SOFA determinism bug — root cause found, fix pending

## The problem
`grasp_hold` (and any lab_shapeOPT scene) gives different physics results when
the identical scene is launched twice — breaks the optimizer's ability to
compare trial scores, since a "bad" score might just be bad luck, not a bad
gripper design.

## Root cause (confirmed, not guessed — see "How we know" below)
`SOFA/Sofa/Component/LinearSystem/src/sofa/component/linearsystem/MatrixLinearSystem.h`
(around line 81) defines:

```cpp
using PairMechanicalStates = sofa::type::fixed_array<core::behavior::BaseMechanicalState*, 2>;
```

and `MatrixLinearSystem.inl` (around line 381) builds the free-motion
(pre-collision) mass/stiffness/damping matrix assembly using:

```cpp
std::map<PairMechanicalStates, GroupOfComponentsAssociatedToAPairOfMechanicalStates> groups;
```

This is a plain `std::map` with the **default comparator** — it sorts by the
raw memory address of the `BaseMechanicalState*` pointers. Memory addresses
vary between process launches (ASLR) and even across scene rebuilds within
one process (heap allocator history — confirmed empirically, see below). So
the order mass/stiffness contributions get summed into the shared matrix
differs run to run, and floating-point addition isn't associative — a
different summation order gives a genuinely different (if tiny) numeric
result. In a contact-rich grasp near a slip/grip threshold, that tiny seed
amplifies into a visibly different outcome.

**SOFA already has the fix pattern elsewhere in its own codebase** — it just
wasn't applied here. `sofa/helper/map_ptr_stable_compare.h` defines
`map_ptr_stable_compare`, a `std::map` variant that assigns each pointer a
stable ID the first time it's seen (order of first appearance, not address),
and sorts by that instead. It's already used to protect
`NarrowPhaseDetection::DetectionOutputMap` and `CollisionResponse::ContactMap`
from this exact bug. `MatrixLinearSystem`'s `groups` map has no such
protection.

## The fix (not yet written/tested)
Change `MatrixLinearSystem`'s `groups` map (and the `m_matrixMappings`,
`mappedLocalMatrix`, `componentLocalMatrix` maps in the same header, which use
the same `PairMechanicalStates`/pointer-keyed pattern — check all of them) to
use `sofa::helper::map_ptr_stable_compare` instead of the default comparator.

Note: `map_ptr_stable_compare`'s existing specialization
(`sofa/helper/map_ptr_stable_compare.h`) is written for `std::pair<T*,T*>`
keys, but `PairMechanicalStates` is a `sofa::type::fixed_array<T*, 2>` — will
need either a `fixed_array<T*,2>` specialization added, or convert
`PairMechanicalStates`'s usage sites to `std::pair`. Check for other places in
the codebase already using `fixed_array<T*,2>` as a map key for prior art.

Files to touch: `MatrixLinearSystem.h`, `MatrixLinearSystem.inl` (both under
`Sofa/Component/LinearSystem/src/sofa/component/linearsystem/`), possibly
`sofa/helper/map_ptr_stable_compare.h` to add the `fixed_array` overload.

## How we know (empirical evidence, in order found)
1. Built a harness (`determinism_probe.py` in this folder) that launches the
   same scene twice (same-process and cross-process) and diffs the cube's
   position trace step by step. Confirmed real, reproducible divergence —
   not a fluke — across many repeated trials (divergence *rate*, not a single
   pass/fail, since a single trial isn't statistically trustworthy).
2. Divergence rate scales with system complexity: ~20% for bare cube+floor,
   ~60% for legs-only, 100% for the full robot. Pointed at something
   proportional to system size.
3. Retightening `NNCGConstraintSolver` from the lab's loosened
   `tolerance=1e-3, maxIterations=250` (in `labtests/core/base_scene.py`)
   back to `tolerance=1e-10, maxIterations=1500` dropped divergence from
   100% to 0% (0/15 repeated trials). This proved the issue is *floating-point
   rounding noise that an under-converged solver preserves and a fully
   converged one washes out* — not a logic bug in the solver itself (confirmed
   separately by reading `NNCGConstraintSolver.cpp` / `BlockGaussSeidelConstraintSolver.cpp`
   — clean, deterministic, plain-array code, no hash containers).
3b. This is ALSO the practical stopgap fix already validated as working —
    see "Interim workaround" below.
4. Ruled out with real tests (not just source reading): narrow-phase
   algorithm choice (DirectSAP vs BVH — identical divergence rate),
   OpenMP/BLAS thread pinning (no change), SOFA's own internal parallel
   compliance-matrix build (`BuiltConstraintSolver`'s `multithreading` flag —
   forcing it on/off made no difference), cube-landing geometry (tilting the
   cube 25° to avoid a flush/flat landing made no difference), friction
   (mu=0 made no difference), and the `UncoupledConstraintCorrection` swap.
5. Labeled the actual contact-response objects created each step (they're
   named after the colliding collision-model pair) and directly compared two
   runs: **same set of contacts, different order**, confirmed by name, not
   inferred (`lcp_dump_runner.py`'s `_dump_contact_identities`).
6. Dumped the actual constraint solver's `W` matrix / `dfree` / `force`
   arrays via SOFA's own built-in `printLog` + `msg_info()` output (enable
   `printLog=True` on the `ConstraintSolver` — no custom instrumentation
   needed, `GenericConstraintSolver::solveSystem()` already calls `printLCP()`
   when not muted). Found a literal sign-flipped / entirely-different 3×3
   compliance block at the same matrix index between two runs
   (`lcp_diff.py`).
7. **The key test**: captured `free_position` (the literal output of the
   free-motion/mass-matrix solve, computed *before* collision detection runs
   each step) for the cube, a leg, and the gripper center part, across two
   independent runs (`freemotion_probe.py`). Result: leg and gripper
   `free_position` differ starting at **step 0** — before any contact is
   physically possible. The cube (a simple unmapped rigid body, not part of
   the FEM/mapping matrix assembly) stays bit-identical until step 3-4, when
   contact with the already-diverged gripper/legs carries the difference
   into it. This is what pinned the bug to the free-motion matrix assembly
   specifically, not collision detection (which was the leading suspect for
   most of the investigation and turned out to be a red herring — several
   collision-detection theories were tested and refuted along the way).
8. Traced `assembleSystem()` → found the `groups` map → confirmed via
   `count_mechstates.py`-style scene walk that the robot has 68 distinct
   MechanicalState components and 76 Mapping components (legs are
   beam/FEM models with `RigidDistanceMapping`, `SubsetMultiMapping`,
   `SkinningMapping`, `ArticulatedSystemMapping` — plenty of state pairs
   for an address-sort to reorder), consistent with the empirical evidence.
9. One dead-end worth knowing about so it isn't retried: hypothesized the
   *comparator itself* (`ptr_stable_compare`, which assigns IDs lazily
   during comparisons, a side-effecting comparator — unusual for a
   `std::map`) might be unreliable. Wrote a standalone C++ reproduction of
   that exact class (`stable_compare_test.cpp`) and ran it as 10 independent
   processes — identical output every time. That hypothesis is disproven;
   the stable-ID pattern itself is sound, it's simply *missing* from
   `MatrixLinearSystem`, not broken where it's already applied.

## Interim workaround (already validated, safe to use now)
In `labtests/core/base_scene.py` (~line 118), the `NNCGConstraintSolver` is
deliberately loosened to `tolerance=1e-3, maxIterations=250` "to keep the sim
interactive." Reverting to `tolerance=1e-10, maxIterations=1500` fixes
determinism (0/15 in repeated tests) at the cost of slower solves. Not yet
validated on the real `grasp_hold` scene with actual gripper motion (only
tested on frozen/isolated configs) or measured for wall-clock cost impact —
do that before relying on it for a real optimization run.

## Environment for the rebuild
- SOFA source: `https://github.com/sofa-framework/sofa`, tag `v25.12`
  (matches the installed binary's version — verify before assuming exact
  parity, the running build may have been patched from a slightly different
  point).
- Currently-running SOFA build (the one to eventually replace/patch):
  `C:\Users\Cesar\AppData\Local\Programs\emio-labs\resources\sofa`
  — Python 3.10 bindings, bundled interpreter at
  `...\sofa\bin\python\python.exe` (ABI-sensitive — a rebuild must target
  Python 3.10 or nothing downstream will load it; confirmed this the hard
  way earlier in the investigation).
- Plugins this lab actually needs (from `add_required_plugins` /
  `utils/header.py`): BeamAdapter, SoftRobots, SoftRobots.Inverse,
  MultiThreading, STLIB, ArticulatedSystemPlugin, plus the core
  `Sofa.Component.*` modules.
- Compiler: MSVC via Visual Studio Community, found at
  `C:\Program Files\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat`
  (confirmed working — used to compile `stable_compare_test.cpp` during this
  investigation).
- CMake: `C:\Program Files\CMake\bin\cmake.exe` (confirmed present).
- The *exact* CMake configuration emio-labs used to produce their bundled
  build is unknown — will likely need to be reverse-engineered from the
  installed plugin list / DLLs rather than assumed.

## Test harness in this folder (already built, ready to reuse)
- `scene.py` — throwaway debug copy of `grasp_hold`'s scene, with `PROBE_*`
  env-var toggles for stripping components (gripper, legs, playback,
  narrow-phase algorithm, solver tolerance, cube tilt, constraint-correction
  type, LCP/broadphase logging). Read the module docstring at the top for
  the full toggle list.
- `determinism_probe.py` — runs the scene N times (same-process and
  cross-process pairs) and reports a divergence *rate*, not a single
  pass/fail (single trials are not statistically trustworthy — confirmed
  this the hard way too). `PROBE_REPEATS` env var controls N (default 5).
- `freemotion_probe.py` — the test that found the actual root cause: diffs
  `free_position`/`free_velocity`/`position`/`velocity` for the cube, a leg,
  and the gripper across two runs.
- `lcp_dump_runner.py` / `lcp_diff.py` — enable `PROBE_DUMP_LCP=1` and/or
  `PROBE_DUMP_BROADPHASE=1` on the scene, capture SOFA's own solver/broad-phase
  debug output, parse and diff the actual `W`/`dfree`/`force` values and
  contact identities between two runs.

**To validate the eventual fix**: point `EMIOLABS_SOFA_ROOT` in these scripts
at the newly-built SOFA, rerun `determinism_probe.py` with
`PROBE_SKIP_PLAYBACK=1 PROBE_REPEATS=15` (the config that reliably showed
100% divergence before the tolerance workaround) — this time *without* the
tolerance workaround (`PROBE_SOLVER_TIGHT` unset, i.e. still using the loose
`1e-3/250` tolerance) — and confirm it now reads 0/15. That isolates the
matrix-assembly fix from the tolerance workaround and is the real proof the
source fix works.
