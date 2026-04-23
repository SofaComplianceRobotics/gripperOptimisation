"""
Benchmark SOFA Concurrency - Test optimal number of concurrent simulations.

Tests running 1, 2, 3... up to 10 concurrent SOFA simulations.
For each concurrency level, launches N concurrent instances, waits for all to complete,
and measures total wall-clock time. Calculates average time per simulation and theoretical
throughput in simulations per hour.

Uses the exact same subprocess pattern as optimize.py: headless batch mode, detached processes.
"""

import subprocess
import sys
import time
import json
import os
import tempfile
from pathlib import Path
from dataclasses import dataclass
from typing import List
import hashlib


# ─────────────────────────────────────────────
# Paths & Setup
# ─────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
SRC_ROOT = SCRIPT_DIR.parent
APP_ROOT = SRC_ROOT.parent
LAB_ROOT = APP_ROOT.parent
RUNTIME_DIR = LAB_ROOT / "runtime"
EXPORTS_DIR = RUNTIME_DIR / "exports"
SITE_PACKAGES = RUNTIME_DIR / "modules" / "site-packages"
LAB_CONFIG = LAB_ROOT / "lab_config.jsonc"
REQUIREMENTS = APP_ROOT / "requirements.txt"
REQ_HASH_FILE = RUNTIME_DIR / "modules" / ".requirements.sha256"
ASSETS_ROOT = str(LAB_ROOT.parent.parent)

# SOFA executable path (search common locations like optimize.py does)
SOFA_ROOT = os.environ.get(
    "SOFA_ROOT", r"C:\Users\Cesar\AppData\Local\Programs\emio-labs\resources\sofa"
)
RUNSOFA_EXE = os.environ.get("RUNSOFA_EXE", "")
if not RUNSOFA_EXE:
    runsofa_candidates = [
        os.path.join(SOFA_ROOT, "bin", "runSofa.exe"),
        os.path.join(SOFA_ROOT, "bin", "Release", "runSofa.exe"),
        os.path.join(SOFA_ROOT, "bin", "RelWithDebInfo", "runSofa.exe"),
        os.path.join(SOFA_ROOT, "build", "bin", "Release", "runSofa.exe"),
    ]
    RUNSOFA_EXE = next(
        (p for p in runsofa_candidates if os.path.isfile(p)), runsofa_candidates[0]
    )

# Add src to path for imports
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from labtests.registry import get_test_spec
from labtests.ui import prompt_for_tests


# ─────────────────────────────────────────────
# Data Structures
# ─────────────────────────────────────────────
@dataclass
class BenchmarkResult:
    """Result for one concurrency level."""

    concurrency: int
    elapsed_time: float  # Total wall-clock time for this batch
    sims_per_hour: float  # Theoretical maximum simulations per hour
    efficiency_ratio: float  # Sims per hour per concurrent slot


# ─────────────────────────────────────────────
# Environment Setup (like optimize.py)
# ─────────────────────────────────────────────
def build_env() -> dict:
    """
    Build environment for SOFA subprocess, similar to optimize.py.

    Returns:
        dict: Environment variables dict ready to pass to subprocess calls.
    """
    env = os.environ.copy()

    # Avoid leaking host Python settings into SOFA
    for key in (
        "PYTHONHOME",
        "PYTHONSTARTUP",
        "PYTHONUSERBASE",
        "PYTHONEXECUTABLE",
        "__PYVENV_LAUNCHER__",
    ):
        env.pop(key, None)

    env["SOFA_ROOT"] = SOFA_ROOT

    # Build explicit PATH for SOFA subprocesses
    path_chunks = [
        os.path.join(SOFA_ROOT, "bin", "Release"),
        os.path.join(SOFA_ROOT, "bin", "RelWithDebInfo"),
        os.path.join(SOFA_ROOT, "bin"),
        env.get("PATH", ""),
    ]
    env["PATH"] = ";".join([p for p in path_chunks if p])

    sofa_site_packages = os.path.join(SOFA_ROOT, "lib", "python3", "site-packages")
    env["PYTHONPATH"] = ";".join(
        [
            sofa_site_packages,
            os.path.join(SOFA_ROOT, "plugins", "STLIB"),
            ASSETS_ROOT,
        ]
    )

    return env


# ─────────────────────────────────────────────
# Requirements Check
# ─────────────────────────────────────────────
def _requirements_hash(path: Path) -> str:
    """Compute SHA-256 hash of requirements.txt."""
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ensure_dependencies() -> None:
    """Reinstall dependencies if requirements.txt changed."""
    if not SITE_PACKAGES.exists():
        print("[deps] Installing dependencies...", file=sys.stderr, flush=True)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "-r",
                str(REQUIREMENTS),
                "-t",
                str(SITE_PACKAGES),
                "--prefer-binary",
                "--quiet",
            ],
            check=True,
        )
        REQ_HASH_FILE.parent.mkdir(parents=True, exist_ok=True)
        REQ_HASH_FILE.write_text(_requirements_hash(REQUIREMENTS))
        return

    current_hash = _requirements_hash(REQUIREMENTS)
    stored_hash = REQ_HASH_FILE.read_text() if REQ_HASH_FILE.exists() else ""

    if current_hash != stored_hash:
        print(
            "[deps] requirements.txt changed, updating...", file=sys.stderr, flush=True
        )
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "-r",
                str(REQUIREMENTS),
                "-t",
                str(SITE_PACKAGES),
                "--prefer-binary",
                "--quiet",
            ],
            check=True,
        )
        REQ_HASH_FILE.write_text(current_hash)


# ─────────────────────────────────────────────
# Gripper Mesh Resolution
# ─────────────────────────────────────────────
def _get_current_gripper_mesh() -> Path:
    """
    Get path to current gripper mesh.
    Prefers exported mesh if available, otherwise uses default collision mesh.
    """
    exported_mesh = EXPORTS_DIR / "new_gripper_collision.stl"
    if exported_mesh.exists():
        return exported_mesh

    # Fallback: assume mesh was exported to default location
    fallback_mesh = (
        LAB_ROOT / "data" / "meshes" / "centerparts" / "new_gripper_collision.stl"
    )
    if fallback_mesh.exists():
        return fallback_mesh

    raise FileNotFoundError(
        f"No gripper mesh found. Expected: {exported_mesh} or {fallback_mesh}. "
        "Please run generate_gripper.py first."
    )


# ─────────────────────────────────────────────
# SOFA Simulation Launch
# ─────────────────────────────────────────────
def _launch_sofa_batch(
    gripper_mesh: Path,
    concurrency: int,
    trial_dir: Path,
    env: dict,
    scene_file: Path,
    num_runs: int = 3,
) -> tuple[float, int]:
    """
    Launch N concurrent SOFA simulations, wait for all to complete, measure wall-clock time.

    Inputs:
        gripper_mesh (Path): Path to STL file
        concurrency (int): Number of concurrent instances to launch
        trial_dir (Path): Temporary directory for run files
        env (dict): Base environment dict
        num_runs (int): How many batches to repeat (then average)

    Returns:
        tuple[float, int]: (Total elapsed time for all runs, number of successful completions)
    """
    total_elapsed = 0.0
    total_successful = 0

    for batch_idx in range(num_runs):
        print(
            f"\n  Batch {batch_idx + 1}/{num_runs}: Launching {concurrency} concurrent instances..."
        )

        # Launch N concurrent processes
        processes: List[subprocess.Popen] = []
        score_paths = []

        for proc_idx in range(concurrency):
            trial_state_file = (
                trial_dir / f"trial_state_batch{batch_idx}_proc{proc_idx}.json"
            )
            score_paths.append(trial_state_file)

            proc_env = env.copy()
            proc_env["OPTUNA_STL_PATH"] = str(gripper_mesh)
            proc_env["OPTUNA_TRIAL_STATE_PATH"] = str(trial_state_file)
            proc_env["OPTUNA_RUN_SLOT"] = "1"

            # Use the exact same flags as optimize.py for headless batch mode
            creation_flags = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            )
            if hasattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS"):
                creation_flags |= subprocess.BELOW_NORMAL_PRIORITY_CLASS

            try:
                proc = subprocess.Popen(
                    [RUNSOFA_EXE, "-l", "SofaPython3", "-g", "batch", str(scene_file)],
                    env=proc_env,
                    cwd=ASSETS_ROOT,
                    creationflags=creation_flags,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                processes.append(proc)
            except Exception as e:
                print(
                    f"    ✗ Failed to launch process {proc_idx}: {e}",
                    file=sys.stderr,
                    flush=True,
                )
                continue

        # Wait for all to complete and measure time
        batch_start = time.perf_counter()

        active = len(processes)
        completed = 0
        last_update = 0.0

        while completed < active:
            now = time.perf_counter()
            elapsed = now - batch_start

            # Check for completed processes
            completed = sum(1 for p in processes if p.poll() is not None)

            # Print progress every 2 seconds
            if now - last_update >= 2.0:
                pct = (100.0 * completed) / active if active > 0 else 0.0
                print(
                    f"    Progress: {completed}/{active} ({pct:.0f}%) - {elapsed:.1f}s",
                    flush=True,
                )
                last_update = now

            if completed < active:
                time.sleep(0.5)

        batch_elapsed = time.perf_counter() - batch_start
        total_elapsed += batch_elapsed

        # Count successful completions (score file exists)
        successful = sum(1 for sp in score_paths if sp.exists())
        total_successful += successful

        print(
            f"    Completed in {batch_elapsed:.2f}s ({successful}/{concurrency} with valid scores)"
        )

    avg_elapsed = total_elapsed / num_runs if num_runs > 0 else 0.0
    return avg_elapsed, total_successful


# ─────────────────────────────────────────────
# Benchmark Runner
# ─────────────────────────────────────────────
def _benchmark_concurrency_level(
    gripper_mesh: Path,
    concurrency: int,
    scene_file: Path,
    num_runs: int = 3,
) -> BenchmarkResult:
    """
    Run simulations at a specific concurrency level.

    Launches N concurrent processes, waits for all to finish, repeats num_runs times,
    and calculates average throughput.

    Inputs:
        gripper_mesh (Path): Path to gripper STL
        concurrency (int): Number of concurrent instances
        num_runs (int): Number of times to repeat this batch

    Returns:
        BenchmarkResult: Timing and throughput metrics
    """
    print(f"\n{'─' * 60}")
    print(f"Testing concurrency level: {concurrency}")
    print(f"Running {num_runs} batches of {concurrency} parallel instances")
    print(f"{'─' * 60}")

    env = build_env()

    with tempfile.TemporaryDirectory(prefix="sofa_bench_") as tmpdir:
        trial_dir = Path(tmpdir)

        avg_elapsed, num_successful = _launch_sofa_batch(
            gripper_mesh=gripper_mesh,
            concurrency=concurrency,
            trial_dir=trial_dir,
            env=env,
            scene_file=scene_file,
            num_runs=num_runs,
        )

    # Calculate throughput
    # Each batch runs `concurrency` simulations
    # So in time avg_elapsed, we ran `concurrency` simulations
    # Sims per hour = (3600 / avg_elapsed) * concurrency
    sims_per_hour = (3600.0 * concurrency / avg_elapsed) if avg_elapsed > 0 else 0.0

    # Efficiency: throughput per concurrent slot
    efficiency_ratio = sims_per_hour / concurrency if concurrency > 0 else 0.0

    result = BenchmarkResult(
        concurrency=concurrency,
        elapsed_time=avg_elapsed,
        sims_per_hour=sims_per_hour,
        efficiency_ratio=efficiency_ratio,
    )

    print(f"\n  Summary for concurrency {concurrency}:")
    print(f"    Average batch time: {avg_elapsed:.2f}s")
    print(f"    Concurrent instances: {concurrency}")
    print(f"    Theoretical sims/hour: {sims_per_hour:.1f}")
    print(f"    Efficiency (sims/hour/slot): {efficiency_ratio:.2f}")

    return result


def _format_results_table(results: List[BenchmarkResult]) -> str:
    """Format results as a readable table."""
    lines = []
    lines.append("\n" + "═" * 90)
    lines.append("SOFA CONCURRENCY BENCHMARK RESULTS (CONCURRENT MODE)")
    lines.append("═" * 90)
    lines.append(
        f"{'Concurrency':>12} | {'Batch Time (s)':>14} | {'Sims/Hour':>12} | "
        f"{'Efficiency':>12} | {'Notes':>20}"
    )
    lines.append("─" * 90)

    max_efficiency = max(r.efficiency_ratio for r in results) if results else 0
    optimal_concurrency = max(
        (r.concurrency for r in results if r.efficiency_ratio == max_efficiency),
        default=1,
    )

    for result in results:
        is_optimal = " ◄ OPTIMAL" if result.concurrency == optimal_concurrency else ""
        notes = is_optimal

        lines.append(
            f"{result.concurrency:>12} | {result.elapsed_time:>14.2f} | "
            f"{result.sims_per_hour:>12.1f} | {result.efficiency_ratio:>12.2f} | "
            f"{notes:>20}"
        )

    lines.append("─" * 90)
    lines.append(
        f"\n✓ Optimal concurrency: {optimal_concurrency} "
        f"(efficiency: {max_efficiency:.2f} sims/hour per slot)"
    )
    lines.append("═" * 90 + "\n")

    return "\n".join(lines)


# ─────────────────────────────────────────────
# Main Entry Point
# ─────────────────────────────────────────────
def main() -> None:
    """Main benchmark runner."""
    print("\n" + "═" * 60)
    print("SOFA Concurrency Benchmark")
    print("═" * 60)

    # Ensure dependencies
    print("\n[*] Checking dependencies...")
    try:
        _ensure_dependencies()
    except Exception as e:
        print(f"✗ Dependency installation failed: {e}", file=sys.stderr, flush=True)
        sys.exit(1)

    # Check SOFA installation
    print("[*] Checking SOFA installation...")
    if not os.path.isfile(RUNSOFA_EXE):
        print(
            f"✗ SOFA executable not found at: {RUNSOFA_EXE}",
            file=sys.stderr,
            flush=True,
        )
        print(
            f"  Set RUNSOFA_EXE or SOFA_ROOT environment variable to override",
            file=sys.stderr,
            flush=True,
        )
        sys.exit(1)
    print(f"    SOFA: {Path(RUNSOFA_EXE).name}")

    # Select test
    selected = prompt_for_tests("Select test to benchmark", multi_select=False)
    test_spec = get_test_spec(selected[0])
    scene_file = test_spec.scene_file
    print(f"    Test: {selected[0]}")

    # Get gripper mesh
    print("[*] Locating gripper mesh...")
    try:
        gripper_mesh = _get_current_gripper_mesh()
        print(f"    Gripper: {gripper_mesh.name}")
    except FileNotFoundError as e:
        print(f"✗ {e}", file=sys.stderr, flush=True)
        sys.exit(1)

    # Run benchmarks
    print("\n[*] Starting benchmarks...")
    print("    Testing concurrency levels 1-10 (3 runs each)")

    results: List[BenchmarkResult] = []

    for concurrency_level in range(1, 11):
        try:
            result = _benchmark_concurrency_level(
                gripper_mesh=gripper_mesh,
                concurrency=concurrency_level,
                scene_file=scene_file,
                num_runs=3,
            )
            results.append(result)
        except KeyboardInterrupt:
            print("\n✗ Benchmark interrupted by user", file=sys.stderr, flush=True)
            sys.exit(1)
        except Exception as e:
            print(
                f"✗ Benchmark failed at concurrency {concurrency_level}: {e}",
                file=sys.stderr,
                flush=True,
            )
            sys.exit(1)

    # Print results
    report = _format_results_table(results)
    print(report)

    # Optional: Save results to JSON
    output_file = RUNTIME_DIR / "benchmark_results.json"
    try:
        results_json = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "gripper": gripper_mesh.name,
            "mode": "concurrent",
            "description": "Each concurrency level launches N parallel SOFA instances",
            "results": [
                {
                    "concurrency": r.concurrency,
                    "batch_time_s": r.elapsed_time,
                    "sims_per_hour": r.sims_per_hour,
                    "efficiency_ratio": r.efficiency_ratio,
                }
                for r in results
            ],
        }
        output_file.write_text(json.dumps(results_json, indent=2))
        print(f"✓ Results saved to: {output_file}")
    except Exception as e:
        print(f"⚠ Could not save results: {e}", file=sys.stderr, flush=True)

    print("\n✓ Benchmark complete!")


if __name__ == "__main__":
    main()
