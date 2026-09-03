"""
Scene: reach_zone

Inverse-mode workspace test.
Sweeps a fixed stack of horizontal grids from Y_MIN to Y_MAX: within each
grid, every (x, z) point in the fixed square GRID_MIN..GRID_MAX is
commanded once and the settled TCP position kept, whether or not it landed
exactly on target. Stacking grids across the vertical range is what traces
a real 3D reachable boundary instead of one flat slice. Score is the
volume enclosed by that boundary.

On a manual launch (no optimizer trial attached), the Scenes tab opens this
through runSofa's interactive GUI (-g imgui), which renders every frame --
far slower than the sweep needs, since nothing about it needs watching live.
So a manual launch immediately relaunches itself under -g batch (the same
headless mode the optimizer uses, no window, no per-frame render cost) and
exits the interactive process right away. The headless run does the actual
sweep at full speed; once it finishes, it saves the result and hands off to
view_scene.py -- a fresh, static, interactive SOFA window with the swept
robot pose gone and just the reachable zone shown next to the robot at
rest. Net effect: the only thing shown live is the finished shape. All of
this is skipped entirely when running under the optimizer -- it's a
viewing convenience, not part of the score, and popping GUI windows or
spawning extra processes mid-optimization would be actively wrong.

What this file owns:
  - _sweep_plan (the per-grid probe generator over the fixed Y stack)
  - ReachZoneController (drives _sweep_plan frame by frame, then scores)
  - _launch_runsofa / _relaunch_headless / _relaunch_as_view_scene
    (manual-launch-only process handoffs: interactive -> headless sweep ->
    interactive viewer)
  - createScene() wiring

Sweep constants, mesh construction, and the result file live in
geometry.py, shared with view_scene.py.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


sys.path.insert(0, str(next(c for c in Path(__file__).parents if (c / "labtests").is_dir())))
from launcher.bootstrap import bootstrap_lab

SCRIPT_DIR, SRC_ROOT, APP_ROOT, LAB_ROOT = bootstrap_lab(__file__)

from sofaopt.scene import open_trial  # noqa: E402

from labtests.reach_zone import geometry  # noqa: E402

TRIAL = open_trial()

# Set on the relaunched headless process's environment so it runs the sweep
# for real instead of relaunching itself again.
HEADLESS_ENV_KEY = "SHAPEOPT_REACH_ZONE_HEADLESS"


def _grid_points():
    """The fixed, ascending (x, z) grid probed at every height, from
    GRID_MIN to GRID_MAX in GRID_STEP steps along each axis."""
    n_steps = round((geometry.GRID_MAX - geometry.GRID_MIN) / geometry.GRID_STEP)
    coords = [geometry.GRID_MIN + i * geometry.GRID_STEP for i in range(n_steps + 1)]
    return [(x, z) for x in coords for z in coords]


def _sweep_level(y, level_index):
    """Probe every (x, z) grid point at height y, once each, directly.

    Yields (target_xyz, hold_frames, status) -- status is a plain dict for
    ReachZoneController to report via writer.write_status -- and expects
    the settled (x, y, z) achieved by that target sent back via .send().
    Returns the list of achieved points for this level, one per grid point:
    whatever position the solver actually settled at when aiming for that
    target, whether or not it landed exactly on it -- a target beyond the
    true reach still gives a valid boundary point (however far it actually
    got), same as a target well within reach gives back the target itself.
    """
    achieved_points = []
    for grid_index, (x, z) in enumerate(_grid_points()):
        target = (x, y, z)
        status = {
            "state": "running",
            "level_index": level_index,
            "y": y,
            "grid_index": grid_index,
            "target": [x, y, z],
        }
        achieved = yield (target, geometry.HOLD_FRAMES, status)
        achieved_points.append(achieved)
    return achieved_points


def _y_levels():
    """The fixed, ascending stack of grid heights from Y_MIN to Y_MAX."""
    n_steps = round((geometry.Y_MAX - geometry.Y_MIN) / geometry.Y_STEP)
    return [geometry.Y_MIN + i * geometry.Y_STEP for i in range(n_steps + 1)]


def _sweep_plan():
    """Probe every grid point at every level in the fixed Y_MIN..Y_MAX stack.

    Returns levels: a list of (y, achieved_points) pairs, one per height in
    _y_levels(), already sorted ascending by y.
    """
    levels = []
    for level_index, y in enumerate(_y_levels()):
        points = yield from _sweep_level(y, level_index)
        levels.append((y, points))
    return levels


def _launch_runsofa(scene_path: Path, gui_mode: str, extra_env: dict | None = None) -> bool:
    """Spawn a fresh runSofa process on `scene_path`. Returns True on success."""
    import subprocess

    from launcher.bootstrap import resolve_sofa_runtime

    try:
        runsofa = resolve_sofa_runtime()["runsofa_exe"]
        env = dict(os.environ)
        if extra_env:
            env.update(extra_env)
        subprocess.Popen([runsofa, "-l", "SofaPython3", "-g", gui_mode, str(scene_path)], env=env)
        return True
    except Exception as exc:
        print(f"[reach_zone] could not launch runSofa -g {gui_mode} on {scene_path.name}: {exc}")
        return False


def _relaunch_headless() -> bool:
    """Relaunch this same scene under -g batch (headless, full speed) instead
    of the slow interactive GUI a manual launch starts in. Returns True if
    the relaunch was spawned -- the caller must exit immediately after, since
    two processes must never both run the sweep.
    """
    return _launch_runsofa(SCRIPT_DIR / "scene.py", "batch", {HEADLESS_ENV_KEY: "1"})


def _relaunch_as_view_scene() -> None:
    """Close this scene and open view_scene.py showing the saved reach zone.

    Manual-launch only. Spawns a fresh runSofa GUI window pointed at the
    static viewer scene, then hard-exits this process. os._exit (not
    sys.exit) because SOFA's Python bindings aren't safe to clean up through
    normal interpreter shutdown once a scene has run -- the same reason
    sofaopt.scene.runner and ScoreWriter._stop() both hard-exit instead.
    """
    _launch_runsofa(SCRIPT_DIR / "view_scene.py", "imgui")
    os._exit(0)


def createScene(rootnode):
    """Build the reach_zone inverse-mode scene with the adaptive ring-stack sweep."""
    if not TRIAL.is_optimizing and os.environ.get(HEADLESS_ENV_KEY) != "1":
        if _relaunch_headless():
            os._exit(0)
        # Relaunch failed (e.g. runSofa path unresolvable) -- fall through
        # and run the sweep here instead of losing the run entirely.

    import Sofa.Core  # type: ignore

    from labtests.core.base_scene import build_base_scene
    from labtests.core.modules.effector_target import setup as setup_effector
    from parts.controllers.assemblycontroller import AssemblyController  # type: ignore

    nodes = build_base_scene(rootnode, inverse=True)
    if nodes is None:
        return

    # AssemblyController is needed by ReachZoneController to know when assembly is done.
    nodes.emio.addObject(AssemblyController(nodes.emio))

    effector_handles = setup_effector(
        nodes,
        nodes.emio,
        initial_target_pos=[0, geometry.CENTER_Y, 0, 0, 0, 0, 1],
    )

    writer = TRIAL.attach(rootnode)

    assembly_controller = nodes.emio.getObject("AssemblyController")
    tcp_mo = nodes.modelling.TCP.getMechanicalState()

    class ReachZoneController(Sofa.Core.Controller):
        """Pump _sweep_plan one probe at a time; score the resulting ring stack once it's done."""

        def __init__(self, *args, **kwargs):
            Sofa.Core.Controller.__init__(self, *args, **kwargs)
            self.plan = _sweep_plan()
            self.current_target = None
            self.current_status = None
            self.hold_total = 1
            self.hold_frame = 0
            self.recent_positions: list[tuple[float, float, float]] = []
            self.levels = None
            self._pump(None)

        def _pump(self, achieved):
            try:
                target, hold_frames, status = self.plan.send(achieved)
            except StopIteration as stop:
                self.levels = stop.value
                return
            self.current_target = target
            self.current_status = status
            self.hold_total = hold_frames
            self.hold_frame = 0
            self.recent_positions = []

        def onAnimateBeginEvent(self, event):
            if not assembly_controller.done:
                return

            if self.levels is not None:
                if not writer.finished:
                    if len(self.levels) < 2:
                        writer.prune("reach sweep produced fewer than 2 usable levels")
                        return
                    vertices, triangles = geometry.build_zone_solid(self.levels)
                    volume = geometry.mesh_volume(vertices, triangles)
                    score = volume / 1000.0  # mm^3 -> cm^3
                    manual = not TRIAL.is_optimizing
                    if manual:
                        geometry.save_result(LAB_ROOT, self.levels, volume)
                    writer.write_score(
                        score,
                        f"reach zone volume={volume:.1f}mm^3 ({score:.2f}cm^3) "
                        f"from {len(self.levels)} levels",
                    )
                    if manual:
                        _relaunch_as_view_scene()
                return

            x, y, z = self.current_target
            effector_handles.target_mo.position.value = [[x, y, z, 0, 0, 0, 1]]

            self.hold_frame += 1
            if self.hold_frame > self.hold_total - geometry.AVERAGE_LAST_N_FRAMES:
                tcp_pos = tcp_mo.position.value[0]
                self.recent_positions.append((float(tcp_pos[0]), float(tcp_pos[1]), float(tcp_pos[2])))
            if self.hold_frame >= self.hold_total:
                achieved = tuple(sum(c) / len(self.recent_positions) for c in zip(*self.recent_positions))
                writer.write_status({**self.current_status, "achieved": list(achieved)})
                self._pump(achieved)

    nodes.simulation.addObject(ReachZoneController(name="ReachZoneController"))

    return rootnode
