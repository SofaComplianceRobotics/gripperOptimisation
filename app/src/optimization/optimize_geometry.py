"""
optimize_geometry.py — Geometry generation, STL rendering, and preview handling.

Manages the full pipeline from trial parameters to visual STL and preview images.
"""

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pyvista as pv

from optimize_config import (
    APP_ROOT,
    CENTERPARTS_DIR,
    GENERATE_SCRIPT,
    GEOMETRY_EXPORT_TIMEOUT,
    HARD_FAIL_SCORE,
    MESH_FIXED,
    PREVIEWS_DIR,
    RING_FIXED,
)


class GeometryExportTimeoutError(RuntimeError):
    """Raised when generate_gripper.py times out."""

    pass


class GeometryExportFailureError(RuntimeError):
    """Raised when generate_gripper.py returns non-zero exit code."""

    pass


def resolve_failed_preview_image(candidates: tuple[Path, ...]) -> Path:
    """Resolve the placeholder image used for failed or empty generations.

    Args:
        candidates: Candidate placeholder image paths.

    Returns:
        Existing placeholder PNG path.

    Raises:
        FileNotFoundError: If no placeholder image exists.
    """
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "Missing failed preview placeholder image. Expected "
        "failed_generation.png in the lab root."
    )


def write_jsonc(path: Path, data: dict) -> None:
    """Write a dict as plain JSON to a .jsonc file.

    Args:
        path: Destination file path.
        data: Data to serialize.
    """
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def params_from_trial(trial) -> dict:
    """Sample one set of gripper shape parameters from an Optuna trial.

    Args:
        trial: Active Optuna trial to sample from.

    Returns:
        Sampled shape parameter values.
    """
    from optimize_config import PINCER_ROUND_ENDS

    return {
        # Pincer profile
        "pincer_profile_width": trial.suggest_float("pincer_profile_width", 2.0, 8.0),
        "pincer_profile_height": trial.suggest_float(
            "pincer_profile_height", 6.0, 16.0
        ),
        "pincer_path_scale": 0.4,
        "pincer_tilt_y_deg": 90.0,
        "pincer_round_ends": PINCER_ROUND_ENDS,
        # Spline first handle (anchor is fixed at 0,0)
        "p0_hout_dist": trial.suggest_float("p0_hout_dist", 0.0, 80.0),
        "p0_hout_angle_deg": trial.suggest_float("p0_hout_angle_deg", -90, 90),
        # Spline endpoint
        "p1_dist": trial.suggest_float("p1_dist", 70.0, 90.0),
        "p1_angle_deg": trial.suggest_float("p1_angle_deg", -90.0, 45.0),
        # Spline last handle
        "p1_hin_dist": trial.suggest_float("p1_hin_dist", 0.0, 80.0),
        "p1_hin_angle_deg": trial.suggest_float("p1_hin_angle_deg", -10.0, 260.0),
        # Leg tilt
        "leg_attachement_tilt_angle": trial.suggest_float(
            "leg_attachement_tilt_angle", -30.0, 30.0
        ),
    }


def generate_stl_for_trial(trial_dir: Path, config: dict) -> tuple[Path, Path]:
    """Write lab_config.jsonc, run generate_gripper.py, and return the output STL paths.

    new_gripper.stl stays in CENTERPARTS_DIR so SOFA can find it by its hardcoded
    name; a copy goes into trial_dir for the preview render. The collision STL is
    renamed to a trial-specific name to avoid conflicts across parallel SOFA instances.

    Args:
        trial_dir: Directory for this trial's files.
        config: Full config to write as lab_config.jsonc.

    Returns:
        Tuple of (collision STL in CENTERPARTS_DIR, visual STL copy in trial_dir).

    Raises:
        GeometryExportTimeoutError: If generate_gripper.py times out.
        GeometryExportFailureError: If generate_gripper.py fails.
        RuntimeError: If output STL files are not found.
    """
    config_path = trial_dir / "lab_config.jsonc"
    write_jsonc(config_path, config)

    try:
        result = subprocess.run(
            [sys.executable, GENERATE_SCRIPT, "--config", str(config_path)],
            cwd=str(APP_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GEOMETRY_EXPORT_TIMEOUT,
        )
    except subprocess.TimeoutExpired as e:
        stdout_tail = (e.stdout or "")[-1500:]
        stderr_tail = (e.stderr or "")[-1500:]
        raise GeometryExportTimeoutError(
            "generate_gripper.py timed out "
            f"after {GEOMETRY_EXPORT_TIMEOUT:.1f}s.\n"
            f"stdout (tail):\n{stdout_tail}\n"
            f"stderr (tail):\n{stderr_tail}"
        ) from e

    if result.returncode != 0:
        stdout_tail = (result.stdout or "")[-2000:]
        stderr_tail = (result.stderr or "")[-2000:]
        raise GeometryExportFailureError(
            "generate_gripper.py failed "
            f"(returncode={result.returncode}).\n"
            f"stdout (tail):\n{stdout_tail}\n"
            f"stderr (tail):\n{stderr_tail}"
        )

    trial_id = f"{trial_dir.parent.name}_{trial_dir.name}"

    collision_src = CENTERPARTS_DIR / "new_gripper_collision.stl"
    if not collision_src.exists():
        raise RuntimeError("Collision STL not found after generation.")
    collision_stl = CENTERPARTS_DIR / f"gripper_{trial_id}_collision.stl"
    collision_src.replace(collision_stl)

    visual_src = CENTERPARTS_DIR / "new_gripper.stl"
    if not visual_src.exists():
        raise RuntimeError("Visual STL not found after generation.")
    visual_stl_copy = trial_dir / "visual.stl"
    shutil.copy2(visual_src, visual_stl_copy)

    return collision_stl, visual_stl_copy


def render_stl_preview(
    visual_stl: Path,
    trial_dir: Path,
    gen_index: int,
    trial_index: int,
    failed_preview: Path | None = None,
) -> None:
    """Render an offscreen PNG preview from the visual STL and delete the STL.

    Saves the screenshot to the trial directory and the flat previews folder.

    Args:
        visual_stl: Path to the full-resolution visual STL to render.
        trial_dir: Trial directory where preview.png will be saved.
        gen_index: Generation number, used to name the flat preview file.
        trial_index: Trial number within the generation.
        failed_preview: Fallback preview image if render fails.
    """
    plotter = None
    try:
        mesh = pv.read(str(visual_stl))

        if mesh.n_cells == 0 or mesh.n_points == 0:
            raise ValueError("visual mesh is empty")

        plotter = pv.Plotter(off_screen=True, window_size=(800, 600))
        plotter.add_mesh(mesh, color="#4a90d9", pbr=True, metallic=0.1, roughness=0.4)
        plotter.add_light(pv.Light(position=(200, 200, 400), intensity=0.8))
        plotter.camera_position = [
            (300, -30, 0),  # where the camera sits
            (0, -30, 0),  # what it looks at (center of model)
            (0, 1, 0),  # which direction is "up"
        ]
        plotter.camera.zoom(1.2)
        plotter.background_color = "white"

        local_path = trial_dir / "preview.png"
        plotter.screenshot(str(local_path))

        visual_stl.unlink()

        flat_name = f"gen_{gen_index:04d}_trial_{trial_index:02d}.png"
        shutil.copy2(local_path, PREVIEWS_DIR / flat_name)

        print(f"[preview] Saved {flat_name}")
    except Exception as e:
        print(f"[warn] Preview render failed for {visual_stl.name}: {e}")
        if failed_preview is not None:
            try:
                local_path = trial_dir / "preview.png"
                shutil.copy2(failed_preview, local_path)
                flat_name = f"gen_{gen_index:04d}_trial_{trial_index:02d}.png"
                shutil.copy2(local_path, PREVIEWS_DIR / flat_name)
                print(
                    f"[preview] Saved failed placeholder for gen_{gen_index:04d} "
                    f"trial_{trial_index:02d}"
                )
            except Exception as fallback_err:
                print(
                    f"[warn] Failed preview fallback could not be published: {fallback_err}"
                )
    finally:
        if plotter is not None:
            plotter.close()
        if visual_stl.exists():
            visual_stl.unlink()
