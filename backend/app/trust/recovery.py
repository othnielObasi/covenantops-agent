"""Recovery for CovenantOps Agent: checkpoint + resume.

During a covenant run the agent checkpoints its progress after each covenant is
analysed. If the run is interrupted (worker loss, timeout), it resumes from the
last checkpoint without re-running completed tool calls or double-emitting the memo.

For the demo, an injected failure after covenant N produces a partial run; a resume
call restores the checkpoint and completes only the remaining covenants.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.models import new_id, utc_now


class RunInterrupted(Exception):
    """Raised to simulate a worker/provider failure mid-run (demo)."""
    def __init__(self, checkpoint_id: str, completed: List[str]):
        self.checkpoint_id = checkpoint_id
        self.completed = completed
        super().__init__(f"run interrupted after {completed}")


class CheckpointStore:
    """In-memory checkpoint store (persisted via trust.store in production)."""
    def __init__(self):
        self._cp: Dict[str, Dict[str, Any]] = {}

    def save(self, task_id: str, state: Dict[str, Any]) -> str:
        cid = new_id("chk")
        self._cp[task_id] = {"checkpoint_id": cid, "saved_at": utc_now().isoformat(), "state": state}
        return cid

    def load(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self._cp.get(task_id)

    def clear(self, task_id: str) -> None:
        self._cp.pop(task_id, None)


class RecoveryContext:
    """Threaded through a run to checkpoint progress and optionally inject a failure.

    fail_after: covenant index after which to raise RunInterrupted (demo).
    resume_from: a previously-saved checkpoint state to continue from.
    """
    def __init__(self, store: CheckpointStore, task_id: str,
                 fail_after: Optional[int] = None, resume_state: Optional[Dict[str, Any]] = None):
        self.store = store
        self.task_id = task_id
        self.fail_after = fail_after
        self.resume_state = resume_state or {}
        self.completed_covenants: List[str] = list(self.resume_state.get("completed_covenants", []))
        self.saved_findings: List[Dict[str, Any]] = list(self.resume_state.get("findings", []))
        self.checkpoint_id: Optional[str] = self.resume_state.get("checkpoint_id")
        self._n_completed_at_start = len(self.completed_covenants)

    def already_done(self, covenant: str) -> bool:
        return covenant in self.completed_covenants

    def record(self, covenant: str, finding: Dict[str, Any]) -> None:
        self.completed_covenants.append(covenant)
        self.saved_findings.append(finding)
        self.checkpoint_id = self.store.save(self.task_id, {
            "completed_covenants": self.completed_covenants,
            "findings": self.saved_findings,
            "checkpoint_id": None,  # set by store
        })
        # inject failure for the demo AFTER this covenant, if configured
        idx = len(self.completed_covenants)
        if self.fail_after is not None and idx == self.fail_after + 1:
            raise RunInterrupted(self.checkpoint_id, list(self.completed_covenants))

    @property
    def resumed(self) -> bool:
        return self._n_completed_at_start > 0
