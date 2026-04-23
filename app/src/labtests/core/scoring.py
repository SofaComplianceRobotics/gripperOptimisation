"""
Shared scoring I/O helpers for all ShapeOPT tests.

All tests need to write status updates and final scores to JSON files
so the optimizer and monitor can read them. This module centralises
those two operations so no test duplicates the logic.

Usage inside a controller:
    from labtests.core.scoring import ScoreWriter
    writer = ScoreWriter(rootnode, env)
    writer.write_status({...})
    writer.write_score_and_stop(score, "reason text")
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


class ScoreWriter:
    """
    Handles all JSON output for one simulation run.

    Inputs at construction:
        rootnode:   SOFA root node (used for rootnode.time in status payloads)
        run_info:   Dict with keys gen, trial, run — injected into every payload
    """

    def __init__(
        self,
        rootnode,
        run_info: dict[str, int],
        trial_state_path: str,
        run_slot: int,
    ) -> None:
        self.rootnode = rootnode
        self.run_info = run_info
        self.trial_state_path = trial_state_path
        self.run_slot = int(run_slot)
        self._finished = False
        self._last_status: dict[str, Any] = {}

    def _acquire_lock(self, lock_path: Path, timeout_s: float = 5.0) -> bool:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            try:
                fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                return True
            except FileExistsError:
                time.sleep(0.01)
            except Exception:
                return False
        return False

    def _release_lock(self, lock_path: Path) -> None:
        try:
            if lock_path.exists():
                lock_path.unlink()
        except Exception:
            pass

    def _update_trial_state_run(self, payload: dict[str, Any]) -> bool:
        if self.trial_state_path is None:
            return False
        path = Path(self.trial_state_path)
        lock_path = path.with_suffix(path.suffix + ".lock")
        if not self._acquire_lock(lock_path):
            return False

        try:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    data = {}
            except Exception:
                data = {}

            runs = data.get("runs")
            if not isinstance(runs, list):
                runs = []
            while len(runs) < self.run_slot:
                runs.append({"run": len(runs) + 1})

            slot = runs[self.run_slot - 1]
            if not isinstance(slot, dict):
                slot = {"run": self.run_slot}
            slot.update(payload)
            slot["run"] = self.run_slot
            slot["updated_at"] = self.rootnode.time.value
            runs[self.run_slot - 1] = slot

            data["runs"] = runs
            data["updated_at"] = self.rootnode.time.value
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(path)
            return True
        finally:
            self._release_lock(lock_path)

    # ── Public API ─────────────────────────────────────────────────────────────

    def write_status(self, payload: dict[str, Any]) -> None:
        """
        Atomically write a live-status payload.

        Status writes are best-effort: any I/O error is silently swallowed
        so a status failure never kills the simulation.

        Inputs:
            payload: Arbitrary dict merged with run_info before writing.

        Returns:
            None
        """
        full = {**self.run_info, **payload, "updated_at": self.rootnode.time.value}
        self._last_status = dict(full)

        self._update_trial_state_run(full)

    def write_score_and_stop(self, score: float, reason: str) -> None:
        """
        Update the trial_state run slot to 'done', then stop the simulation.

        Safe to call multiple times — only the first call has any effect.

        Inputs:
            score:  Final numeric score for this run.
            reason: Human-readable explanation string (logged + stored in status).

        Returns:
            None
        """
        if self._finished:
            return
        self._finished = True

        final_status = dict(self._last_status)
        final_status.update({"state": "done", "score": score, "reason": reason})
        self.write_status(final_status)
        print(f"[Score] {reason} | score: {score:.4f}")
        self.rootnode.animate = False
        os.kill(os.getpid(), 9)

    def write_pruned_and_stop(self, reason: str) -> None:
        """
        Mark this run as pruned in trial_state.json and stop the simulation.

        Used when the simulation reaches an undefined state that should not
        count as a scored trial (e.g. cube glitched through the floor after
        a successful pickup, or the test horizon completed normally in a mode
        where that is not a scoring event).

        Inputs:
            reason: Human-readable explanation string.

        Returns:
            None
        """
        if self._finished:
            return
        self._finished = True

        final_status = dict(self._last_status)
        final_status.update({"state": "pruned", "score": None, "reason": reason})
        self.write_status(final_status)
        print(f"[Pruned] {reason}")
        self.rootnode.animate = False
        os.kill(os.getpid(), 9)

    @property
    def finished(self) -> bool:
        """True after write_score_and_stop or write_pruned_and_stop has been called."""
        return self._finished
