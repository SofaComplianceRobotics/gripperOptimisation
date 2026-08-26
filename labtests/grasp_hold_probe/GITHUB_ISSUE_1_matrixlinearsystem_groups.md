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
running process (heap allocation history). Since the assembly loop
(`for (const auto& [pair, group] : groups) { ... }`) accumulates mass,
stiffness, and damping contributions in this address-dependent order, and
floating-point addition is not associative, the exact same scene launched
twice can produce a different (if tiny) free-motion result. In a
contact-rich scene this can snowball into visibly different simulation
outcomes.

This is not inferred from reading the code alone: `groups`'s own iteration
order was captured directly, by enabling `printLog` on a scene's
`MatrixLinearSystem` instance and reading its own `msg_info()` output
(`makeLocalMatrixGroups`, the line beginning "Create a matrix to be mapped,
shared among the following components..."), across two independent launches
of the identical scene. Both launches produced the same set of entries,
confirmed as an exact multiset match, just at different positions. Full
dump under Logs.

The clearest evidence this originates in free-motion assembly, not
collision: bodies going through this matrix assembly (legs, gripper, on the
scene this was originally found in) diverge in `free_position` starting at
step 0, before any contact is even possible, while a simple unmapped rigid
body in the same scene stays bit-identical until a later step, once contact
with the already-diverged bodies carries the difference into it. Full
numbers under Logs.

There already is a fix for this class of bug elsewhere in the codebase:
`sofa::helper::map_ptr_stable_compare`
(`sofa/helper/map_ptr_stable_compare.h`) sorts by order-of-first-appearance
instead of address, and is already used to protect
`NarrowPhaseDetection::DetectionOutputMap` and `CollisionResponse::ContactMap`
from this issue. `MatrixLinearSystem`'s `groups` map (and possibly
`m_matrixMappings`, `mappedLocalMatrix`, `componentLocalMatrix` in the same
header, which use the same pointer-keyed pattern) has no such protection.

**Note for whoever picks this up:** applying the same fix here needs one
adjustment. `map_ptr_stable_compare`'s existing `ptr_stable_compare`
specialization is written for `std::pair<T*,T*>` keys, while
`PairMechanicalStates` (the key type used by `groups`) is a
`sofa::type::fixed_array<T*, 2>`, not a `std::pair`. Either a
`fixed_array<T*,2>` specialization needs adding to
`map_ptr_stable_compare.h`, or `PairMechanicalStates`'s usage sites need
converting to `std::pair`.

**Steps to reproduce**

Minimal repro attached: `matrixlinearsystem_groups_repro.py`. Six
independent rigid bodies, each rigidly mapped to a child point and then
nonlinearly multi-mapped (`DistanceMultiMapping`) into a scalar distance
against one shared body, each pulled by its own spring, creating real
cross-pairs in `groups` involving mapped states. Why that specific
structure (nonlinear mapping, not a plain linear one) is needed is explained
in a comment directly above the `DistanceMultiMapping` call in the script;
excerpt:

```python
        # DistanceMultiMapping: a genuinely nonlinear (orientation-dependent
        # Jacobian) multi-input mapping, so its geometric-stiffness
        # contribution to the shared Attach state is non-zero, which is
        # what makes groups' address-ordered iteration actually matter,
        # unlike a plain linear gather mapping, whose constant Jacobian
        # contributes zero geometric stiffness regardless of assembly order.
        diff.addObject(
            "DistanceMultiMapping",
            input=[mappedLeg.mo.getLinkPath(), attach.mo.getLinkPath()],
            output=diff.mo.getLinkPath(),
            indexPairs=[0, 0, 1, 0],
            computeDistance=True,
        )
```

```txt
runSofa -l SofaPython3 matrixlinearsystem_groups_repro.py
```

Launch independently multiple times and compare the shared body's
`free_position` after the first step. Divergence rate: 70-100% of
independent launch pairs diverge at step 0 across different batches of
10-15, with differences of order 1 or larger in position, not confined to
the last few decimal digits (the springs' equilibrium is sensitive to the
tiny assembly-order-dependent differences at the matrix level). Full
numbers under Logs.

Further corroboration comes from the actual larger scene (4 beam-model legs
+ a deformable gripper) this bug was originally found in. That scene is not
attached and requires the full lab codebase to run, so it is not the primary
repro, but its numbers (including the step-0-vs-step-4 divergence pattern
described above, a tolerance-sensitivity check, and a direct dump of
`groups`' own iteration order) are under Logs.

**Expected behavior**

Launching the identical scene twice, on a single-threaded, deterministic
constraint-solver configuration, should produce identical results, matching
the guarantee `NarrowPhaseDetection`/`CollisionResponse` already provide via
`map_ptr_stable_compare`. This is scoped to single-threaded runs
deliberately: multithreading was tested and ruled out as the cause here
(OpenMP/BLAS thread pinning made no difference, and forcing
`NNCGConstraintSolver`'s ancestor class `BuiltConstraintSolver` (via
`BlockGaussSeidelConstraintSolver`)'s own `multithreading` flag on or off
made no difference to an otherwise-clean run), so this is not a report
asking for bit-exact determinism under threading.

---------------------------------------------

### Environment

**Context**

- System: Windows 11 Pro, 10.0.26200
- Version of SOFA: v25.12.00 binaries (emio-labs bundled distribution)
- State: Install directory

<details>
<summary>Env vars (Python version, PATH, PYTHONPATH, sys.path)</summary>

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
`<...>` placeholders)*

Not yet reproduced on a stock, from-source SOFA v25.12 build, only on this
vendor-bundled binary distribution. `MatrixLinearSystem.h`/`.inl` are core
SOFA files with no reason to expect vendor patching, and the mechanism
described here matches the public v25.12 source read directly from
`sofa-framework/sofa`, but this has not been independently confirmed against
a plain source build.

</details>

---------------------------------------------

### Logs

**Minimal repro (attached)**

```txt
Divergence rate (10-20 repeated trials, Attach body's free_position
compared after step 0):

  6 independent legs + 1 shared Attach body : 70-100%
                                               (12/15 and 7/10 measured)
```

<details>
<summary>Internal lab scene (not attached, corroboration only, requires the full lab codebase)</summary>

```txt
Divergence rate (5-15 repeated trials per configuration):

  full robot present (static)                                    : 100%
  full robot, tolerance=1e-10, maxIterations=1500 (vs default
    1e-3 / 250)                                                   : 0%
                                                        (15/15 identical)

free_position, two independent launches of the identical scene:

  cube.free_position            : IDENTICAL through step 3, diverges step 4
  leg0_beam.free_position       : diverges step 0
  gripper_center.free_position  : diverges step 0

Contact-independence check (cube reachable vs. spawned unreachably far
away; same total DOF count and groups population either way):

  cube reachable    : 10/10 pairs diverged at step 0
  cube unreachable  : 10/10 pairs diverged at step 0

groups' own iteration order (MatrixLinearSystem.printLog, real msg_info()
output), two independent launches, first 2 animation steps: 69 log lines in
both launches, exact same multiset of (mechanical-state,
contributing-components) entries, 38 of 69 positions differ. Excerpt (full
dump available on request):

    [0]  A: state=.../Motor0/Parts/MechanicalObject
           components=[masses .../Motor0/Parts/UniformMass,
                       force fields .../Motor0/Parts/UniformMass,
                       mappings .../Motor0/Parts/LegAttach/RigidMapping]
         B: identical at [0]

    [40] A: state=.../Leg2/.../ExtremityGroup/MechanicalObject
           components=[mappings .../Leg2/.../SubsetMultiMapping]
         B: state=.../Motor3/Parts/MechanicalObject
           components=[masses .../Motor3/Parts/UniformMass,
                       force fields .../Motor3/Parts/UniformMass,
                       mappings .../Motor3/Parts/LegAttach/RigidMapping]
         <<< DIFFERS

    [65] A: state=.../CenterPart/LegsAttach/MechanicalObject
           components=[mappings .../Leg0/.../RigidDistanceMapping,
                       .../Leg1/.../RigidDistanceMapping,
                       .../Leg2/.../RigidDistanceMapping,
                       .../Leg3/.../RigidDistanceMapping]
         B: state=.../Leg0/Leg0RigidBase/MechanicalObject
           components=[mappings .../Leg0/Leg0RigidBase/Difference0/RigidDistanceMapping]
         <<< DIFFERS (also shows all four legs' RigidDistanceMapping
             contributions landing in one shared group in run A, at
             CenterPart/LegsAttach, the actual cross-pair state combining
             all four legs)
```

</details>

<details>
<summary>Content of build_dir/CMakeCache.txt</summary>

N/A, running from the emio-labs binary distribution, not a local build; no
`CMakeCache.txt` available. Plugin/DLL manifest available on request.

</details>
