### Problem

**Description**

`MatrixLinearSystem`'s free-motion (pre-collision) matrix assembly groups
mechanical-state pairs using a plain `std::map` keyed on raw pointer
addresses, with no protection against address (ASLR / heap-layout) variance
between runs:

- `MatrixLinearSystem.h`:
  `using PairMechanicalStates = sofa::type::fixed_array<core::behavior::BaseMechanicalState*, 2>;`
- `MatrixLinearSystem.inl` (`assembleSystem`):
  `std::map<PairMechanicalStates, GroupOfComponentsAssociatedToAPairOfMechanicalStates> groups;`

Because this uses the default comparator, `groups` is ordered by the raw
memory address of each `BaseMechanicalState` pointer. Addresses vary between
process launches (ASLR) and even between scene rebuilds within one already-
running process (heap allocation history — we measured this directly, see
below). Since the assembly loop
(`for (const auto& [pair, group] : groups) { ... }`) accumulates mass/
stiffness/damping contributions in this address-dependent order, and
floating-point addition is not associative, the exact same scene launched
twice can produce a genuinely different (if tiny) free-motion result. In a
contact-rich scene this snowballs into visibly different simulation outcomes.

SOFA already has a fix for exactly this class of bug elsewhere in the
codebase: `sofa::helper::map_ptr_stable_compare`
(`sofa/helper/map_ptr_stable_compare.h`) sorts by order-of-first-appearance
instead of address, and is already used to protect
`NarrowPhaseDetection::DetectionOutputMap` and `CollisionResponse::ContactMap`
from this exact issue. `MatrixLinearSystem`'s `groups` map (and possibly
`m_matrixMappings`, `mappedLocalMatrix`, `componentLocalMatrix` in the same
header, which use the same pointer-keyed pattern) has no such protection.

**Steps to reproduce**

We isolated this with a step-by-step measurement harness rather than a
minimal standalone scene — happy to share the scripts on request. The
method:

1. Build a scene with `FreeMotionAnimationLoop` + an iterative constraint
   solver (`NNCGConstraintSolver` in our case), with multiple deformable/
   mapped mechanical bodies (our scene: 4 beam-model legs + a deformable
   gripper, ~68 `MechanicalState` components, ~76 `Mapping` components).
2. Launch the identical scene twice — either as two separate process
   launches, or by rebuilding the scene graph twice inside one already-
   running process. Both show the effect.
3. Read each mechanical body's `free_position`/`free_velocity` Data (the
   literal free-motion solve output, read right after
   `Sofa.Simulation.animate()` each step, before collision detection could
   matter) and diff step-by-step between the two runs.

Result: bodies going through the FEM/mapping matrix assembly (legs, gripper)
diverge starting at step 0 — before any contact is even possible. A simple
unmapped rigid body in the same scene (not part of that assembly) stays
bit-identical until a later step, when contact with the already-diverged
bodies carries the difference into it.

We separately confirmed retightening the constraint solver's tolerance
(`tolerance=1e-3, maxIterations=250` → `tolerance=1e-10, maxIterations=1500`)
flips the divergence rate from 100% to 0% across 15 repeated trials of the
same scene — consistent with genuine floating-point rounding noise that an
under-converged solver preserves and a fully-converged one washes out, not a
logic bug in the solver itself (we read `NNCGConstraintSolver.cpp` /
`BlockGaussSeidelConstraintSolver.cpp` directly and found no other issue —
plain deterministic array code, no hash containers).

We also ruled out, with direct measurement rather than inference: narrow-
phase algorithm choice (`DirectSAPNarrowPhase` vs `BVHNarrowPhase` — identical
divergence rate), OpenMP/BLAS thread pinning, `BuiltConstraintSolver`'s own
`multithreading` flag (forcing it on/off made no difference to an otherwise-
clean run), cube-landing geometry/symmetry, friction, and
`UncoupledConstraintCorrection`.

**Expected behavior**

Launching the identical scene twice should produce identical (or at least
converged-equivalent) results, matching the guarantee
`NarrowPhaseDetection`/`CollisionResponse` already provide via
`map_ptr_stable_compare`.

---------------------------------------------

### Environment

**Context**

- System: Windows 11 Pro, 10.0.26200
- Version of SOFA: v25.12.00 binaries (emio-labs bundled distribution)
- State: Install directory

**Command called**

```txt
python -m sofaopt.scene.runner <scene.py>
```
(launched via our lab's `sofaopt` runner, which loads the scene module
directly in-process and calls `Sofa.Simulation.animate()` in a loop — see
`sofaopt/scene/runner.py`. Equivalent to `runSofa -l SofaPython3 <scene.py>`.)

**Env vars**

```bash
python -c "exec( \"import os, sys\nprint('#################')\nprint('--- sys.version ---')\nprint(sys.version)\nprint('--- PATH ---')\ntry:\n  print(os.environ['PATH'])\nexcept Exception:\n  pass\nprint('--- SOFA_ROOT ---')\ntry:\n  print(os.environ['SOFA_ROOT'])\nexcept Exception:\n  pass\nprint('--- PYTHONPATH ---')\ntry:\n  print(os.environ['PYTHONPATH'])\nexcept Exception:\n  pass\nprint('--- sys.path ---')\ntry:\n   print(str(sys.path))\nexcept Exception:\n   pass\nprint('#################')\" )"
```

```txt
#################
--- sys.version ---
3.10.14 (main, Jul 25 2024, 21:51:48) [MSC v.1929 64 bit (AMD64)]
--- PATH ---
<SOFA_ROOT>\plugins\SofaPython3\bin;<SOFA_ROOT>\bin;<standard Windows/user PATH entries>
--- SOFA_ROOT ---
C:\Users\Cesar\AppData\Local\Programs\emio-labs\resources\sofa
--- PYTHONPATH ---
C:\Users\Cesar\AppData\Local\Programs\emio-labs\resources\sofa/plugins/SofaPython3/lib/python3/site-packages;C:\Users\Cesar\AppData\Local\Programs\emio-labs\resources\sofa/plugins/STLIB/lib/python3/site-packages;<our lab's assets root>;<sofaopt src root>
--- sys.path ---
['', 'C:\\Users\\Cesar\\AppData\\Local\\Programs\\emio-labs\\resources\\sofa\\plugins\\SofaPython3\\lib\\python3\\site-packages', 'C:\\Users\\Cesar\\AppData\\Local\\Programs\\emio-labs\\resources\\sofa\\plugins\\STLIB\\lib\\python3\\site-packages', '<assets root>', '<sofaopt src root>', 'C:\\Users\\Cesar\\AppData\\Local\\Programs\\emio-labs\\resources\\sofa\\bin\\python\\python310.zip', 'C:\\Users\\Cesar\\AppData\\Local\\Programs\\emio-labs\\resources\\sofa\\bin\\python\\DLLs', 'C:\\Users\\Cesar\\AppData\\Local\\Programs\\emio-labs\\resources\\sofa\\bin\\python\\lib', 'C:\\Users\\Cesar\\AppData\\Local\\Programs\\emio-labs\\resources\\sofa\\bin\\python', 'C:\\Users\\Cesar\\AppData\\Roaming\\Python\\Python310\\site-packages', 'C:\\Users\\Cesar\\AppData\\Local\\Programs\\emio-labs\\resources\\sofa\\bin\\python\\lib\\site-packages', 'C:\\Users\\Cesar\\AppData\\Local\\Programs\\emio-labs\\resources\\sofa\\bin\\python\\lib\\site-packages\\cmeel.prefix\\lib\\python3.10\\site-packages']
#################
```
*(PATH abbreviated above — full value is standard Windows/dev-tool entries
with no bearing on the bug; redacted local folder names replaced with
`<...>` for the same reason.)*

---------------------------------------------

### Logs

**Full output**

```txt
Divergence rate (5-15 repeated trials per configuration, same scene launched
independently each time, identical cube position trace compared step by
step):

  bare cube + floor (no robot)        : ~20% of independent launches diverge
  4 legs present (static), no gripper : ~60%
  full robot present (static)         : 100%
  full robot, solver tolerance=1e-10,
    maxIterations=1500 (vs default
    1e-3 / 250)                       : 0% (15/15 identical)

Direct evidence the divergence originates in free-motion assembly, not
collision: comparing free_position (captured immediately after
Sofa.Simulation.animate() each step) between two independent launches of
the identical scene —

  cube.free_position     : IDENTICAL through step 3, first diverges step 4
  leg0_beam.free_position : first diverges step 0
  gripper_center.free_position : first diverges step 0

(the cube is a simple unmapped rigid body, not part of MatrixLinearSystem's
`groups`-based assembly; the leg and gripper are FEM/beam bodies that are.
Step 0 is before the cube has even started falling — no contact is possible
at that point.)

Direct evidence at the contact-response level (labeled by collision-model
pair name, comparing two independent launches at the same simulation step):

  Run A, finger 1 contacts (in creation order):
    LineCollisionModel-gripperCollisionLines
    LineCollisionModel-gripperCollisionPoints
    TriangleCollisionModel-gripperCollisionPoints

  Run B, finger 1 contacts (in creation order):
    TriangleCollisionModel-gripperCollisionPoints
    LineCollisionModel-gripperCollisionPoints
    gripperCollisionLines-LineCollisionModel

Same three physical contacts, both runs — different order, and even the
pair-name direction of one contact flips (LineCollisionModel-
gripperCollisionLines vs gripperCollisionLines-LineCollisionModel),
indicating the underlying pointer order differs between runs at that level
too.
```

**Content of build_dir/CMakeCache.txt**

N/A — running from the emio-labs binary distribution, not a local build; no
`CMakeCache.txt` available. Happy to provide the plugin/DLL manifest instead
if useful.
