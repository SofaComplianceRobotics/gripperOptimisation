"""
minimal_repro.py: standalone, dependency-free SOFA scene reproducing the
run-to-run determinism bug. No project-specific imports: only stock SOFA
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
different runs of 10 launch pairs (vs. 100% when the same collision/
constraint setup is embedded in a larger scene with more mechanical bodies;
see the parent bug report for that fuller case and the root-cause analysis).
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
        tolerance=1e-3,       # loosened on purpose -- 1e-10/1500 makes this
        maxIterations=250,    # scene deterministic; see bug report for why.
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
