"""Trial data tracking and state management for the optimization loop."""

import sys
from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parent.parent
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from optimization._trial_state import (
    read_trial_run,
    read_trial_state,
    update_trial_summary,
)
from labtests.registry import get_test_spec


class TrialState:
    """Tracks current generation, trial count, best score, and all collected scores."""

    def __init__(self) -> None:
        self.gen: int = 0
        self.trial_count: int = 0
        self.best_score: float = float("-inf")
        self.best_gen: int = 0
        self.all_scores: list[float] = []
        self.gated_tests_enabled: bool = False
        self._test_max_scores: dict[str, float] = {}
        self._test_aggregations: dict[str, str] = {}

    def load_test_specs(self, test_names: list[str]) -> None:
        """Populate per-test max-score and aggregation method from the test registry.

        Falls back to safe defaults for any test not found in the registry.

        Args:
            test_names: Ordered list of test names to resolve.
        """
        for name in test_names:
            try:
                spec = get_test_spec(name)
                self._test_max_scores[name] = spec.max_score
                self._test_aggregations[name] = spec.score_aggregation
            except Exception:
                self._test_max_scores[name] = 1.0
                self._test_aggregations[name] = "mean"

    @property
    def test_max_scores(self) -> dict[str, float]:
        return self._test_max_scores

    @property
    def test_aggregations(self) -> dict[str, str]:
        return self._test_aggregations

    def record_score(self, score: float) -> None:
        """Record a new trial score and update best-score tracking.

        Args:
            score: Final score for the completed trial (out of 100).
        """
        self.all_scores.append(score)
        self.trial_count += 1
        if score > self.best_score:
            self.best_score = score
            self.best_gen = self.gen

    def advance_gen(self) -> None:
        """Increment the generation counter."""
        self.gen += 1

    def compute_rolling_stats(self, window: int = 20) -> dict:
        """Calculate rolling performance metrics over the most recent trials.

        Args:
            window: Number of recent scores to include in the window.

        Returns:
            Dict with rolling_avg, rolling_best, and window keys.
        """
        recent = self.all_scores[-window:] if self.all_scores else []
        valid = [s for s in recent if s != float("-inf")]
        if not valid:
            return {"rolling_avg": None, "rolling_best": None, "window": window}
        return {
            "rolling_avg": round(sum(valid) / len(valid), 4),
            "rolling_best": round(max(valid), 4),
            "window": len(valid),
        }


def _load_trial_data(path: Path) -> dict:
    """Read trial results from filesystem.

    Args:
        path: Path to trial_state.json.

    Returns:
        Trial state as a dict, or {} on any read error.
    """
    return read_trial_state(path)


def _save_trial_checkpoint(path: Path, data: dict) -> None:
    """Persist trial summary fields to JSON.

    Args:
        path: Path to trial_state.json.
        data: Fields to merge into the existing trial state document.
    """
    update_trial_summary(path, data)


def _compute_rolling_stats(all_scores: list[float], window: int = 20) -> dict:
    """Calculate rolling performance metrics over recent trials.

    Standalone function for use outside a TrialState instance.

    Args:
        all_scores: Full score history across all trials.
        window: How many recent scores to include.

    Returns:
        Dict with rolling_avg, rolling_best, and window keys.
    """
    recent = all_scores[-window:] if all_scores else []
    valid = [s for s in recent if s != float("-inf")]
    if not valid:
        return {"rolling_avg": None, "rolling_best": None, "window": window}
    return {
        "rolling_avg": round(sum(valid) / len(valid), 4),
        "rolling_best": round(max(valid), 4),
        "window": len(valid),
    }
