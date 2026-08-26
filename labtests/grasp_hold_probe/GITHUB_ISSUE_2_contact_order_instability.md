### Problem

**Description**

A minimal scene, one rigid cube dropped onto a fixed rigid floor under
gravity, nothing else, doesn't reliably give the same result across
independent launches of the exact same scene, same binary, same scene
file, single-threaded. Divergence rate varies batch to batch, seen between
20% and 60% of launch pairs, never 0%.

Two separate address-dependent bugs in `DirectSAPNarrowPhase` are
responsible. Both produce the same symptom. Contact-response objects for
the same physical contacts get created in a different relative order
between runs.

**Bug 1: hash-table iteration order determines collision-model discovery
order.**

`DirectSAPNarrowPhase.h` declares:

```cpp
std::unordered_set<core::CollisionModel *> m_broadPhaseCollisionModels;
std::unordered_set<core::CollisionModel *> m_addedCollisionModels;
```

`DirectSAPNarrowPhase.cpp`, `checkNewCollisionModels()`:

```cpp
void DirectSAPNarrowPhase::checkNewCollisionModels()
{
    SCOPED_TIMER_VARNAME(scopeTimer, "Direct SAP check new cm");
    for (auto *cm : m_broadPhaseCollisionModels)
    {
        auto *last = cm->getLast();
        assert(last != nullptr);
        const auto inserstionResult = m_addedCollisionModels.insert(last);
        if (inserstionResult.second) //insertion success
        {
            m_newCollisionModels.emplace_back(last);
        }
    }
    ...
}
```

`m_broadPhaseCollisionModels` is a plain `std::unordered_set`, keyed
directly on raw `CollisionModel*` pointers, no custom hash or comparator.
C++'s default hash for a pointer is derived from its address, so this
container's bucket layout, and the order a range-based `for` loop walks it
in, is address-dependent. That loop's order directly becomes
`m_newCollisionModels`'s order (an ordinary, order-preserving
`sofa::type::vector`), which is what `createBoxesFromCollisionModels()`
uses to assign each collision element's `boxID`, which determines the
sweep order the rest of `DirectSAPNarrowPhase` uses to discover pairs.
Everything downstream of this is confirmed address-independent (the sort
comparator and the active-box sweep list are both plain-integer-keyed on
`boxID`), but this first step isn't, so the address-dependence introduced
here propagates through the whole pipeline.

**Bug 2: raw pointer comparison as a same-class tie-break.**

`DirectSAPNarrowPhase.cpp`, `narrowCollisionDetectionFromSortedEndPoints()`:

```cpp
bool swapModels = false;
core::collision::ElementIntersector* finalintersector =
    intersectionMethod->findIntersector(cm0, cm1, swapModels);

if (!swapModels && cm0->getClass() == cm1->getClass() && cm0 > cm1)
    swapModels = true;
```

`cm0`/`cm1` are raw `core::CollisionModel*`. When two collision models
being tested are the same class (two `LineCollisionModel`s, two
`TriangleCollisionModel`s, etc.), there's no type-based ordering
preference from `findIntersector`, so this line breaks the tie by
comparing which one happens to live at a higher memory address. That
decision sets which of `(cm0, cm1)` / `(cm1, cm0)` gets passed into
`getDetectionOutputs()`, and `NarrowPhaseDetection::DetectionOutputMap`'s
key type is `std::pair<CollisionModel*, CollisionModel*>`, confirmed
non-symmetric under its own comparator, `(X,Y)` and `(Y,X)` are distinct
keys, not normalized to each other. So the same physical contact can
register under two different logical keys depending on launch, purely
from this comparison, independent of Bug 1.

Bug 2 alone can only relabel a same-class pair's own two sides, it can't
move any pair's position. The position changes actually measured
require discovery order itself, Bug 1, to differ between runs too.

**How this actually reaches the solver's constraint rows.**
`DetectionOutputMap` and `CollisionResponse::contactMap` are both sorted
maps (`map_ptr_stable_compare`), so it's worth asking why insertion order
into an already-sorted map would matter. It matters because the sort key
itself, each pointer's stable ID, is assigned in order of first
appearance; change the order pointers are first seen (Bug 1, Bug 2) and
their IDs change, which changes the map's own sorted order as a direct
result. Traced one step further to make sure that actually reaches row
numbering. `CollisionResponse::createNewContacts()` calls `contact->init()`
on each `Contact` while iterating `outputsMap` in that (now
order-dependent) sorted sequence, and `init()` is what attaches the object
into the scene graph, in that same order (matches what was independently
seen walking the live scene graph, see Logs). Global constraint row
numbers then get assigned by
`sofa::simulation::mechanicalvisitor::MechanicalBuildConstraintMatrix`, a
scene-graph visitor carrying a single `unsigned int& contactId` counter
through the whole traversal:

```cpp
// MechanicalBuildConstraintMatrix::fwdConstraintSet()
c->setConstraintId(contactId);
c->buildConstraintMatrix(cparams, res, contactId);
```

Passed by reference, advanced by however many rows each component owns
before the visitor reaches the next one, so row numbers land strictly in
traversal order, the same order just shown to shift with discovery order.

Measured on `NNCGConstraintSolver` (a Gauss-Seidel-family iterative
solver) with `RuleBasedContactManager` / `FrictionContactConstraint`
responses. That's relevant because a Gauss-Seidel solve's result depends
on the order it visits rows in, especially under-converged (this scene
runs `tolerance=1e-3, maxIterations=250` on purpose), and the 13
simultaneous contacts from the cube landing flat form a statically
indeterminate system with no single correct answer to converge to
regardless of order, so a same-set, different-order permutation of rows
genuinely lands on a different final result rather than just a relabeling.

Best guess for what's actually randomizing the addresses between launches
is ASLR, that fits every symptom here (heap-allocated pointers, varies
between independent process launches, nothing else varies), but that
hasn't been independently confirmed yet (e.g. by disabling it and checking
whether the divergence rate drops to 0%), just haven't gotten to it. Same
for the fixes below, proposed, but not yet patched into a local build and
re-run against the repro to confirm the divergence actually goes away.

**Steps to reproduce**

The attached minimal repro is `minimal_repro.py`, plus its two mesh files,
`cube.obj` and `floor.obj` (SOFA's own bundled example meshes, copied
alongside the script so this reproduces the same way from a from-source
checkout without that `share/` tree wired in). No project-specific Python
code, only stock SOFA components, a single rigid cube dropped onto a fixed
rigid floor under gravity, `FreeMotionAnimationLoop` + `BruteForceBroadPhase`
+ `DirectSAPNarrowPhase` + `MinProximityIntersection` + `RuleBasedContactManager`
(`FrictionContactConstraint`, `mu=1.2`) + `NNCGConstraintSolver`
(`tolerance=1e-3, maxIterations=250`, loosened on purpose).

```txt
runSofa -l SofaPython3 minimal_repro.py
```

Launch independently multiple times and compare the cube's
`MechanicalObject.position` step by step. Divergence rate varies batch to
batch, seen between 20% and 60% of launch pairs across different batches of
10, never 0%. Full numbers under Logs.

**Expected behavior**

Launching the identical scene twice, single-threaded, deterministic
solver config, should give identical results, matching the guarantee
`NarrowPhaseDetection`/`CollisionResponse` already provide via
`map_ptr_stable_compare` for their own maps, a guarantee this scene shows
isn't actually being met since something upstream of those maps is
address-dependent. Scoped to single-threaded runs deliberately.
Multithreading was tested and ruled out as the cause (OpenMP/BLAS thread
pinning made no difference, forcing the constraint solver's own
`multithreading` flag on or off made no difference either)

---------------------------------------------

### Environment

**Context**

- System: Windows 11 Pro, 10.0.26200
- Version of SOFA: v25.12.00 binaries (emio-labs bundled distribution)
- Compiler/toolchain: MSVC, linker version 14.38 (VS 2022, v143 toolset),
  x64, confirmed from the shipped DLLs' PE headers, relevant since the
  hypothesis here rests on heap-address randomization, a property of the
  allocator/CRT that built these binaries.
- State: Install directory

---------------------------------------------

### Logs

**Minimal repro (attached)**

```txt
Divergence rate (5-15 repeated trials per batch, cube.MechanicalObject.position
compared step by step, same scene launched independently each time):

  bare cube + floor : 20-60% of independent launches diverge
                       (varies batch to batch)

free_position (the free-motion solve output, before any constraint
correction) vs. position (after correction), two independent launches:

  cube.position       : IDENTICAL through free fall, first diverges at the
                         exact step contact begins (never earlier)
  cube.free_position  : IDENTICAL through free fall AND through the contact
                         step itself, first diverges one step later (the
                         next free-motion solve, starting from a position
                         that already diverged)

W matrix at the solver's own input, two diverging launches, same sorted
multiset of values, different row/column positions, an exact permutation,
not corrupted, not approximately equal.
```

<details>
<summary>Contact-response creation order, named collision models to remove ambiguity (minimal repro, two independent launches)</summary>

```txt
Run A, contacts in creation order:
  FloorTriangle-CubePoint
  FloorLine-CubePoint
  CubeLine-FloorLine
  CubeLine-FloorPoint
  CubeTriangle-FloorPoint

Run B, contacts in creation order:
  FloorLine-CubePoint
  CubeLine-FloorLine
  CubeLine-FloorPoint
  FloorTriangle-CubePoint
  CubeTriangle-FloorPoint
```

Same 5 physical contacts, both runs, different relative order (compare
`FloorTriangle-CubePoint`, 1st in run A, 4th in run B). Traced by hand
against the real IDs `map_ptr_stable_compare` would assign in each run.
The internal orientation of the one same-class pair here
(`CubeLine-FloorLine`) doesn't change between these two runs, and holding
discovery order fixed, flipping a same-class pair's orientation alone
doesn't move any other pair's position. The position change actually
measured requires discovery order itself (Bug 1) to differ between runs.

</details>
