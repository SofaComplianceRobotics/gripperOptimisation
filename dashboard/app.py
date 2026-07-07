"""ShapeOPT dashboard: sofaopt's project dashboard plus the lab's own tabs.

The generic tabs (Config, Optimise, Performance, Progress, Parameter Bounds,
Playground) come from sofaopt. The lab contributes two tabs of its own:

- Generate — run the gripper geometry generators and open their outputs;
- Scenes — the lab's scene launchers (inverse kinematics, motor recording,
  watch-a-test), which replace sofaopt's generic Scenes tab.
"""

from __future__ import annotations

from launcher.bootstrap import bootstrap_lab

bootstrap_lab(__file__)

from sofaopt import DashboardTab
from sofaopt.dashboard import context
from sofaopt.dashboard.app import launch_dashboard as _launch_sofaopt_dashboard

from sofaopt_project import PROJECT
from dashboard.callbacks.generation import register_generation_callbacks
from dashboard.callbacks.scenes import register_scene_callbacks
from dashboard.ui.tabs.generate import build_generate_tab
from dashboard.ui.tabs.scenes import build_scenes_tab

LAB_TABS = (
    DashboardTab(
        label="Generate",
        value="generate",
        build=build_generate_tab,
        register=register_generation_callbacks,
        before="optimise",
    ),
    DashboardTab(
        label="Scenes",
        value="scenes",
        build=lambda: build_scenes_tab(context.catalog()),
        register=lambda app: register_scene_callbacks(app, context.catalog()),
        before="optimise",
    ),
)


def launch_dashboard(port: int = 8050, open_browser: bool = True) -> None:
    """Start the ShapeOPT dashboard web server and optionally open a browser."""
    _launch_sofaopt_dashboard(
        PROJECT,
        port=port,
        open_browser=open_browser,
        extra_tabs=LAB_TABS,
        hide_tabs=("scenes",),
    )


if __name__ == "__main__":
    launch_dashboard()
