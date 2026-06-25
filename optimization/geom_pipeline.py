"""
geom_pipeline.py — Geometry generation, STL rendering, and preview handling.

Manages the full pipeline from trial parameters to visual STL and preview images.
"""

import shutil
import subprocess
import sys
from pathlib import Path

import pyvista as pv  # type: ignore

from names import GRIPPER_COLLISION_STL, GRIPPER_NAME
from optimization.config import (
    LAB_ROOT,
    CENTERPARTS_DIR,
    GENERATE_SCRIPT,
    GEOMETRY_EXPORT_TIMEOUT,
    PARAM_SPECS,
    PREVIEWS_DIR,
)
from optimization._scoring_io import write_jsonc

FLOAT_SUGGEST_STEP = 0.1


def _round_float(value: float) -> float:
    """Round a numeric value to 3 decimal places and return as float.

    Args:
        value: Numeric input to round.

    Returns:
        The value rounded to 3 decimal places.
    """
    return round(float(value), 3)


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


def params_from_trial(trial) -> dict:
    """Build a complete config dict from an Optuna trial using PARAM_SPECS.

    Parameters with min == max == 0 are fixed and always use their default.
    All other parameters are sampled from the trial. The returned dict is the
    full config passed to generate_gripper.py (ring + shape + mesh).

    Args:
        trial: Active Optuna trial to sample from.

    Returns:
        Complete parameter dict ready to write as lab_config.jsonc.
    """
    result = {}
    for spec in PARAM_SPECS:
        name = spec["name"]
        if spec["min"] == 0 and spec["max"] == 0:
            result[name] = spec["default"]
        elif spec["type"] == "float":
            value = trial.suggest_float(
                name,
                spec["min"],
                spec["max"],
                step=FLOAT_SUGGEST_STEP,
            )
            if name == "cylinder_plateau_C_deg":
                max_c = max(
                    0.0,
                    45.0
                    - max(
                        result.get("cylinder_plateau_A_deg", 0.0),
                        result.get("cylinder_plateau_B_deg", 0.0),
                    ),
                )
                value = min(value, max_c)
            result[name] = _round_float(value)
        elif spec["type"] == "int":
            result[name] = trial.suggest_int(name, int(spec["min"]), int(spec["max"]))
        elif spec["type"] == "bool":
            result[name] = trial.suggest_categorical(name, [False, True])
        else:
            result[name] = spec["default"]
    return result


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
            cwd=str(LAB_ROOT),
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

    collision_src = CENTERPARTS_DIR / GRIPPER_COLLISION_STL
    if not collision_src.exists():
        raise RuntimeError("Collision STL not found after generation.")
    collision_stl = CENTERPARTS_DIR / f"gripper_{trial_id}_collision.stl"
    collision_src.replace(collision_stl)

    visual_src = CENTERPARTS_DIR / f"{GRIPPER_NAME}.stl"
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
