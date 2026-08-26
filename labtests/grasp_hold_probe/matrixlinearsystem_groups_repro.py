"""
matrixlinearsystem_groups_repro.py: standalone, dependency-free SOFA scene
reproducing MatrixLinearSystem's groups address-ordering bug.

Six independent rigid "leg" bodies, each rigidly mapped to a child point and
then nonlinearly multi-mapped into a scalar distance against one shared "Attach"
rigid body, each pulled by its own RestShapeSpringsForceField.
This creates real cross-pairs in MatrixLinearSystem's groups map,
with the mapped/nonlinear structure needed for groups' own
address-ordered iteration to actually affect the assembled result, not just
exist inertly.

Launching this scene independently multiple times does not always
produce identical results. Observed divergence rate: 70-100% of independent
launches diverge in the Attach body's free_position at step 0, before any
dynamics beyond the first free-motion solve have happened, across
different batches of 10. Divergence magnitude is not subtle: differences of
order 1 or more in position were observed directly, not just in the last few
decimal digits, since the springs' equilibrium is sensitive to the tiny
assembly-order-dependent differences at the matrix level.

Usage:
    runSofa -l SofaPython3 matrixlinearsystem_groups_repro.py
or headless:
    python -c "import Sofa.Core, Sofa.Simulation; import matrixlinearsystem_groups_repro as m; \
        r = Sofa.Core.Node('root'); m.createScene(r); Sofa.Simulation.initRoot(r); \
        Sofa.Simulation.animate(r, r.dt.value); \
        print(r.Simulation.Attach.mo.free_position.value.tolist())"

Launch that twice and diff the printed free_position.
"""

from __future__ import annotations

import math

N_LEGS = 6
LEG_MASSES = [1.0 + 0.37 * ((i * 7) % 5) for i in range(N_LEGS)]
LEG_INERTIA = [
    [0.7 + 0.1 * i, 0.01 * i, 0.0, 0.01 * i, 0.9 - 0.05 * i, 0.02, 0.0, 0.02, 0.8 + 0.03 * i]
    for i in range(N_LEGS)
]
LEG_TILT_DEG = [((-1) ** i) * (5.0 + 3.0 * i) for i in range(N_LEGS)]


def _tilt_quat(deg, axis):
    half = math.radians(deg) / 2.0
    s = math.sin(half)
    n = math.sqrt(sum(a * a for a in axis))
    ax = [a / n for a in axis]
    return [ax[0] * s, ax[1] * s, ax[2] * s, math.cos(half)]


def createScene(rootNode):
    rootNode.gravity = [0.0, -9810.0, 0.0]
    rootNode.dt = 0.01

    plugins = [
        "Sofa.Component.AnimationLoop",
        "Sofa.Component.Constraint.Lagrangian.Correction",
        "Sofa.Component.Constraint.Lagrangian.Solver",
        "Sofa.Component.LinearSolver.Direct",
        "Sofa.Component.Mapping.NonLinear",
        "Sofa.Component.Mapping.Linear",
        "Sofa.Component.Mass",
        "Sofa.Component.ODESolver.Backward",
        "Sofa.Component.StateContainer",
        "Sofa.Component.SolidMechanics.Spring",
        "Sofa.Component.Topology.Container.Dynamic",
    ]
    confignode = rootNode.addChild("Config")
    for p in plugins:
        confignode.addObject("RequiredPlugin", name=p, printLog=False)

    rootNode.addObject("FreeMotionAnimationLoop")
    rootNode.addObject(
        "NNCGConstraintSolver", name="ConstraintSolver",
        tolerance=1e-3, maxIterations=250, multithreading=False,
    )

    simulation = rootNode.addChild("Simulation")
    simulation.addObject("EulerImplicitSolver", rayleighStiffness=0.01, rayleighMass=0.0)
    simulation.addObject("SparseLDLSolver", name="solver", template="CompressedRowSparseMatrixd")
    simulation.addObject("GenericConstraintCorrection", linearSolver=simulation.solver.getLinkPath())

    # shared attachment body: every leg's own nonlinear mapping independently
    # contributes to this state's rows in the assembled matrix
    attach = simulation.addChild("Attach")
    attach.addObject("MechanicalObject", name="mo", template="Rigid3", position=[[0, 20, 0, 0, 0, 0, 1]])
    attach.addObject("UniformMass", vertexMass=[0.73, 1.0, [0.7, 0.01, 0.0, 0.01, 0.9, -0.01, 0.0, -0.01, 0.6]])

    for i in range(N_LEGS):
        leg = simulation.addChild(f"Leg{i}")
        angle = i * (360.0 / N_LEGS)
        x = 8.0 * math.cos(math.radians(angle))
        z = 8.0 * math.sin(math.radians(angle))
        leg.addObject(
            "MechanicalObject", name="mo", template="Rigid3",
            position=[[x, i * 0.7, z] + _tilt_quat(LEG_TILT_DEG[i], (1, 0.3, 0.2))],
        )
        leg.addObject("UniformMass", vertexMass=[LEG_MASSES[i], 1.0, LEG_INERTIA[i]])

        mappedLeg = leg.addChild("Mapped")
        mappedLeg.addObject(
            "MechanicalObject", name="mo", template="Rigid3",
            position=[[0.5, 0.2, -0.3, 0, 0, 0, 1]],
        )
        mappedLeg.addObject("RigidMapping")

        # DistanceMultiMapping: a genuinely nonlinear (orientation-dependent
        # Jacobian) multi-input mapping, so its geometric-stiffness
        # contribution to the shared Attach state is non-zero, which is
        # what makes groups' address-ordered iteration actually matter,
        # unlike a plain linear gather mapping, whose constant Jacobian
        # contributes zero geometric stiffness regardless of assembly order.
        diff = mappedLeg.addChild(f"Difference{i}")
        diff.addObject("MechanicalObject", name="mo", template="Vec1", position=[[0.0]])
        diff.addObject("EdgeSetTopologyContainer", edges=[[0, 1]])
        diff.addObject(
            "DistanceMultiMapping",
            input=[mappedLeg.mo.getLinkPath(), attach.mo.getLinkPath()],
            output=diff.mo.getLinkPath(),
            indexPairs=[0, 0, 1, 0],
            computeDistance=True,
        )
        diff.addObject(
            "RestShapeSpringsForceField",
            stiffness=800.0 + 50.0 * i,
            points=[0],
        )

    return rootNode
