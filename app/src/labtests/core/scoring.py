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
from typing import Any


class ScoreWriter:
    """
    Handles all JSON output for one simulation run.

    Inputs at construction:
        rootnode:   SOFA root node (used for rootnode.time in status payloads)
        score_path: Path to write the final score JSON, or None (dry run / GUI mode)
        status_path: Path to write live status JSON, or None
        run_info:   Dict with keys gen, trial, run — injected into every payload
    """

    def __init__(
        self,
        rootnode,
        score_path: str | None,
        status_path: str | None,
        run_info: dict[str, int],
    ) -> None:
        self.rootnode = rootnode
        self.score_path = score_path
        self.status_path = status_path
        self.run_info = run_info
        self._finished = False
        self._last_status: dict[str, Any] = {}

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
        if not self.status_path:
            return
        try:
            full = {**self.run_info, **payload, "updated_at": self.rootnode.time.value}
            self._last_status = dict(full)
            tmp = self.status_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(full, f, indent=2)
            os.replace(tmp, self.status_path)
        except Exception:
            pass

    def write_score_and_stop(self, score: float, reason: str) -> None:
        """
        Write the final score JSON, update status to 'done', stop the simulation.

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

        if self.score_path:
            with open(self.score_path, "w", encoding="utf-8") as f:
                json.dump({"score": score}, f)

        final_status = dict(self._last_status)
        final_status.update({"state": "done", "score": score, "reason": reason})
        self.write_status(final_status)
        print(f"[Score] {reason} | score: {score:.4f}")
        self.rootnode.animate = False
        os.kill(os.getpid(), 9)

    def write_pruned_and_stop(self, reason: str) -> None:
        """
        Mark this run as pruned (no usable score), stop the simulation.

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
