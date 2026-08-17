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
process launches (ASLR) and even between scene rebuilds within one already
running process (heap allocation history, confirmed by direct measurement,
see Logs below). Since the assembly loop
(`for (const auto& [pair, group] : groups) { ... }`) accumulates mass,
stiffness, and damping contributions in this address-dependent order, and
floating-point addition is not associative, the exact same scene launched
twice can produce a different (if tiny) free-motion result. In a
contact-rich scene this can snowball into visibly different simulation
outcomes.

There already is a fix for this class of bug elsewhere in the codebase:
`sofa::helper::map_ptr_stable_compare`
(`sofa/helper/map_ptr_stable_compare.h`) sorts by order-of-first-appearance
instead of address, and is already used to protect
`NarrowPhaseDetection::DetectionOutputMap` and `CollisionResponse::ContactMap`
from this issue. `MatrixLinearSystem`'s `groups` map (and possibly
`m_matrixMappings`, `mappedLocalMatrix`, `componentLocalMatrix` in the same
header, which use the same pointer-keyed pattern) has no such protection.
This is presented as the confirmed source of divergence for the larger
multi-body scene described below, not (yet) confirmed as the source for the
smaller minimal-repro scene: see "Open question" under Logs.

Caveat on the code snippets above: this was run against the emio-labs binary
distribution of v25.12.00, with no `CMakeCache.txt` or build log available
to confirm the exact source it was built from, and no confirmation either
way on whether that distribution carries local patches to SOFA. The line
references above were read from the public `v25.12` tag on GitHub, not from
the running binary's actual source, and should be treated as "this is what
the tagged source looks like," not as a confirmed match to this specific
build.

**Steps to reproduce**

Minimal repro (attached as `minimal_repro.py`, no project-specific
dependencies, only stock SOFA components): a single rigid cube dropped onto
a fixed rigid floor under gravity.

```txt
runSofa -l SofaPython3 minimal_repro.py
```

Launch this exact scene independently multiple times and compare the cube's
`MechanicalObject.position` step by step. Measured divergence rate varies
batch to batch (seen between 20% and 60% of launch pairs across different
batches of 10), never 0%.

```python
"""
minimal_repro.py: standalone, dependency-free SOFA scene reproducing the
run-to-run determinism bug. No project-specific imports, only stock SOFA
components. A rigid cube drops onto a fixed rigid floor under gravity;
launching this exact scene twice (same process or two separate processes)
does not always produce identical results.

Usage:
    runSofa -l SofaPython3 minimal_repro.py
or headless:
    python -c "import Sofa.Core, Sofa.Simulation; import minimal_repro as m; \
        r = Sofa.Core.Node('root'); m.createScene(r); Sofa.Simulation.initRoot(r); \
        [Sofa.Simulation.animate(r, r.dt.value) for _ in range(10)]"

Observed divergence rate across independent launches of this exact scene:
variable batch to batch, seen as low as 20% and as high as 60% across
different runs of 10 launch pairs (vs. 100% when the same collision and
constraint setup is embedded in a larger scene with more mechanical bodies;
see the rest of this report for that fuller case and the root-cause
analysis).
"""

from __future__ import annotations


def createScene(rootNode):
    rootNode.gravity = [0.0, -9810.0, 0.0]
    rootNode.dt = 0.01

    plugins = [
        "Sofa.Component.AnimationLoop",
        "Sofa.Component.Collision.Detection.Algorithm",
        "Sofa.Component.Collision.Detection.Intersection",
        "Sofa.Component.Collision.Geometry",
        "Sofa.Component.Collision.Response.Contact",
        "Sofa.Component.Constraint.Lagrangian.Correction",
        "Sofa.Component.Constraint.Lagrangian.Solver",
        "Sofa.Component.Constraint.Projective",
        "Sofa.Component.IO.Mesh",
        "Sofa.Component.LinearSolver.Direct",
        "Sofa.Component.Mapping.NonLinear",
        "Sofa.Component.Mass",
        "Sofa.Component.ODESolver.Backward",
        "Sofa.Component.StateContainer",
        "Sofa.Component.Topology.Container.Constant",
    ]
    confignode = rootNode.addChild("Config")
    for p in plugins:
        confignode.addObject("RequiredPlugin", name=p, printLog=False)

    # Collision pipeline
    rootNode.addObject("CollisionPipeline")
    rootNode.addObject("FreeMotionAnimationLoop", parallelODESolving=False)
    rootNode.addObject("BruteForceBroadPhase")
    rootNode.addObject("DirectSAPNarrowPhase")
    rootNode.addObject(
        "MinProximityIntersection", alarmDistance=5.0, contactDistance=1.0
    )
    rootNode.addObject(
        "RuleBasedContactManager",
        responseParams="mu=1.2",
        response="FrictionContactConstraint",
    )
    rootNode.addObject(
        "NNCGConstraintSolver",
        name="ConstraintSolver",
        tolerance=1e-3,       # loosened on purpose, 1e-10/1500 makes this
        maxIterations=250,    # scene deterministic, see report for why.
        multithreading=False,
    )

    simulation = rootNode.addChild("Simulation")
    simulation.addObject("EulerImplicitSolver", rayleighStiffness=0.01, rayleighMass=0.0)
    simulation.addObject("SparseLDLSolver", name="solver", template="CompressedRowSparseMatrixd")
    simulation.addObject("GenericConstraintCorrection", linearSolver=simulation.solver.getLinkPath())

    # --- Cube: rigid body, 8x8x8, mass 0.02 ---
    cube_scale = [8.0, 8.0, 8.0]
    side = 2.0 * cube_scale[0]
    inertia_diag = (side ** 2 + side ** 2) / 12.0 * 5.0  # x5: anti-tip resistance, matches original scene
    cube_inertia = [inertia_diag, 0.0, 0.0, 0.0, inertia_diag, 0.0, 0.0, 0.0, inertia_diag]

    cube_spawn_y = -205.5  # floor top (approx -215.5) + clearance
    cube = simulation.addChild("Cube")
    cube.addObject(
        "MechanicalObject",
        template="Rigid3",
        position=[[0.0, cube_spawn_y, 0.0, 0.0, 0.0, 0.0, 1.0]],
    )
    cube.addObject("UniformMass", vertexMass=[0.02, 1.0, cube_inertia])
    collision = cube.addChild("collision")
    collision.addObject("MeshOBJLoader", name="loader", filename="mesh/cube.obj", triangulate="true", scale3d=cube_scale)
    collision.addObject("MeshTopology", src="@loader")
    collision.addObject("MechanicalObject")
    collision.addObject("TriangleCollisionModel", group=2, moving=True, simulated=True)
    collision.addObject("LineCollisionModel", group=2, moving=True, simulated=True)
    collision.addObject("PointCollisionModel", group=2, moving=True, simulated=True)
    collision.addObject("RigidMapping")

    # --- Floor: fixed rigid body, 2x1x2 ---
    floor_scale = [2.0, 1.0, 2.0]
    floor = simulation.addChild("floor")
    floor.addObject(
        "MechanicalObject", name="mstate", template="Rigid3",
        translation2=[0.0, -220.0, 0.0], rotation2=[0.0, 0.0, 0.0],
    )
    floor.addObject("UniformMass", vertexMass=[0.10, 1.0, [1.0, 0, 0, 0, 1.0, 0, 0, 0, 1.0]])
    floor.addObject("FixedConstraint", indices="0")
    floor_collis = floor.addChild("collision")
    floor_collis.addObject("MeshOBJLoader", name="loader", filename="mesh/floor.obj", triangulate="true", scale3d=floor_scale)
    floor_collis.addObject("MeshTopology", src="@loader")
    floor_collis.addObject("MechanicalObject")
    floor_collis.addObject("TriangleCollisionModel", moving=False, simulated=False, group=3)
    floor_collis.addObject("LineCollisionModel", moving=False, simulated=False, group=3)
    floor_collis.addObject("PointCollisionModel", moving=False, simulated=False, group=3)
    floor_collis.addObject("RigidMapping")

    return rootNode
```

Further evidence, from a larger scene (4 beam-model legs + a deformable
gripper, about 68 `MechanicalState` components and 76 `Mapping` components,
using `FreeMotionAnimationLoop` + `NNCGConstraintSolver`) where the same
symptom reaches 100% of launches:

1. Launch the identical scene twice, either as two separate process
   launches or by rebuilding the scene graph twice inside one already
   running process. Both show the effect.
2. Read each mechanical body's `free_position`/`free_velocity` Data (the
   literal free-motion solve output, read right after
   `Sofa.Simulation.animate()` each step, before collision detection could
   matter) and diff step by step between the two runs.

Result: bodies going through the FEM/mapping matrix assembly (legs, gripper)
diverge starting at step 0, before any contact is even possible. A simple
unmapped rigid body in the same scene (not part of that assembly) stays
bit-identical until a later step, when contact with the already-diverged
bodies carries the difference into it. Full numbers under Logs.

Separately, on that larger scene, retightening the constraint solver's
tolerance (`tolerance=1e-3, maxIterations=250` to `tolerance=1e-10,
maxIterations=1500`) was confirmed to flip the divergence rate from 100% to
0% across 15 repeated trials, consistent with floating-point rounding noise
that an under-converged solver preserves and a fully converged one washes
out.

**Expected behavior**

Launching the identical scene twice, on a single-threaded, deterministic
constraint-solver configuration, should produce identical results, matching
the guarantee `NarrowPhaseDetection`/`CollisionResponse` already provide via
`map_ptr_stable_compare`. This is scoped to single-threaded runs
deliberately: multithreading was tested and ruled out as the cause here
(OpenMP/BLAS thread pinning made no difference, and forcing
`BuiltConstraintSolver`'s own `multithreading` flag on or off made no
difference to an otherwise-clean run), so this is not a report asking for
bit-exact determinism under threading, which is a separate and harder
guarantee.

---------------------------------------------

### Environment

**Context**

- System: Windows 11 Pro, 10.0.26200
- Version of SOFA: v25.12.00 binaries (emio-labs bundled distribution,
  patch status against upstream unconfirmed, see caveat above)
- State: Install directory

**Command called**

```txt
runSofa -l SofaPython3 <scene.py>
```
(also reproduced via a plain Python script that loads the scene module
directly and calls `Sofa.Simulation.animate()` in a loop, same effect, not
SOFA-specific tooling.)

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
<install path>\emio-labs\resources\sofa
--- PYTHONPATH ---
<SOFA_ROOT>/plugins/SofaPython3/lib/python3/site-packages;<SOFA_ROOT>/plugins/STLIB/lib/python3/site-packages;<lab project root>
--- sys.path ---
['', '<SOFA_ROOT>/plugins/SofaPython3/lib/python3/site-packages', '<SOFA_ROOT>/plugins/STLIB/lib/python3/site-packages', '<lab project root>', '<SOFA_ROOT>/bin/python/python310.zip', '<SOFA_ROOT>/bin/python/DLLs', '<SOFA_ROOT>/bin/python/lib', '<SOFA_ROOT>/bin/python', '<user Python310 site-packages>', '<SOFA_ROOT>/bin/python/lib/site-packages', '<SOFA_ROOT>/bin/python/lib/site-packages/cmeel.prefix/lib/python3.10/site-packages']
#################
```
*(PATH abbreviated above; full value is standard Windows/dev-tool entries
with no bearing on the bug. Local install paths and usernames replaced with
`<...>` placeholders for privacy.)*

---------------------------------------------

### Logs

**Open question**

The minimal cube+floor repro (~20-60% divergence, see above) is not fully
explained by the `MatrixLinearSystem.groups` root cause described in
Description. That scene has two rigid bodies with no shared force field or
mapping between them, so there is very little for the `groups` map to
reorder (at most a couple of trivial self-pairs). The larger scene's
`free_position` evidence below explains why *that* scene's legs and gripper
diverge from step 0, but does not explain why the much simpler cube+floor
scene diverges at all. This may be a smaller-scale instance of the same
address-dependence somewhere else in the collision/constraint path (an
earlier hypothesis, since set aside without being fully disproved, was
`DirectSAPNarrowPhase`'s internal `std::unordered_set<CollisionModel*>`
bookkeeping used to track already-boxed models, separate from its
stable-ID-protected output map) or a second, distinct source not yet
identified. Flagging this openly rather than presenting a single root cause
as fully closed.

**Note on the contact-order evidence below**

The contact-creation-order evidence (same physical contacts, different
order, different launches) was captured on the larger scene, at a
simulation step *after* `free_position` had already been shown to diverge
for the legs/gripper at step 0. The most likely reading is that this is a
downstream, physically real consequence: already-slightly-different body
positions feeding the narrow phase produce different near-tie
geometric outcomes (which specific mesh elements register as touching, and
when), not a failure of `map_ptr_stable_compare` itself. It is included as
supporting evidence that the divergence is real and propagates through the
pipeline, not as a claim that `NarrowPhaseDetection`/`CollisionResponse`'s
existing protection is broken. That said, this has not been proven either
way, since a second, still-unprotected ordering issue at the collision layer
would produce the same symptom.

**Full output**

```txt
Divergence rate (5-15 repeated trials per configuration, same scene launched
independently each time, identical cube position trace compared step by
step):

  bare cube + floor (minimal repro)   : 20-60% of independent launches diverge
                                         (varies batch to batch)
  4 legs present (static), no gripper : ~60%
  full robot present (static)         : 100%
  full robot, solver tolerance=1e-10,
    maxIterations=1500 (vs default
    1e-3 / 250)                       : 0% (15/15 identical)

Direct evidence the divergence originates in free-motion assembly, not
collision, on the larger scene: comparing free_position (captured
immediately after Sofa.Simulation.animate() each step) between two
independent launches of the identical scene:

  cube.free_position     : IDENTICAL through step 3, first diverges step 4
  leg0_beam.free_position : first diverges step 0
  gripper_center.free_position : first diverges step 0

(the cube is a simple unmapped rigid body, not part of MatrixLinearSystem's
`groups`-based assembly; the leg and gripper are FEM/beam bodies that are.
Step 0 is before the cube has even started falling, no contact is possible
at that point.)

Contact-response-level evidence (labeled by collision-model pair name,
comparing two independent launches at the same simulation step, on the
larger scene, at a step after free_position had already diverged; see "Note
on the contact-order evidence" above):

  Run A, finger 1 contacts (in creation order):
    LineCollisionModel-gripperCollisionLines
    LineCollisionModel-gripperCollisionPoints
    TriangleCollisionModel-gripperCollisionPoints

  Run B, finger 1 contacts (in creation order):
    TriangleCollisionModel-gripperCollisionPoints
    LineCollisionModel-gripperCollisionPoints
    gripperCollisionLines-LineCollisionModel

Same three physical contacts, both runs, different order, and even the
pair-name direction of one contact flips (LineCollisionModel-
gripperCollisionLines vs gripperCollisionLines-LineCollisionModel).
```

**Content of build_dir/CMakeCache.txt**

N/A, running from the emio-labs binary distribution, not a local build; no
`CMakeCache.txt` available. Plugin/DLL manifest available on request.

---------------------------------------------

### Note for whoever picks this up

`map_ptr_stable_compare`'s existing `ptr_stable_compare` specialization is
written for `std::pair<T*,T*>` keys. `PairMechanicalStates` (the key type
used by `groups`) is a `sofa::type::fixed_array<T*, 2>`, not a `std::pair`.
Applying the same fix here will need either a `fixed_array<T*,2>`
specialization added to `map_ptr_stable_compare.h`, or converting
`PairMechanicalStates`'s usage sites to `std::pair`.
