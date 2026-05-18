"""Shared SOFA plugin registration for direct-mode (playback) scenes."""


def add_required_plugins(simulation_node) -> None:
    """Register all SOFA plugins required for direct-mode simulation.

    Args:
        simulation_node: SOFA simulation node to attach a Config child to.
    """
    plugins = [
        "Sofa.Component.AnimationLoop",
        "Sofa.Component.Collision.Detection.Algorithm",
        "Sofa.Component.Collision.Detection.Intersection",
        "Sofa.Component.Collision.Geometry",
        "Sofa.Component.Collision.Response.Contact",
        "Sofa.Component.Constraint.Lagrangian.Correction",
        "Sofa.Component.Constraint.Lagrangian.Solver",
        "Sofa.Component.IO.Mesh",
        "Sofa.Component.LinearSolver.Iterative",
        "Sofa.Component.Mapping.NonLinear",
        "Sofa.Component.Mass",
        "Sofa.Component.ODESolver.Backward",
        "Sofa.Component.StateContainer",
        "Sofa.Component.Topology.Container.Constant",
        "Sofa.Component.Visual",
        "Sofa.GL.Component.Rendering3D",
    ]
    config = simulation_node.addChild("Config")
    for name in plugins:
        config.addObject("RequiredPlugin", name=name, printLog=False)