"""Question Ledger CRUD -- permanent retention, append-only versions (Task 11)."""
from __future__ import annotations
from .storage.checkpoint import CheckpointLog
from .schemas import QuestionLedgerEntry


class QuestionLedger:
    def __init__(self, checkpoint_log: CheckpointLog):
        self.log = checkpoint_log

    def _state(self) -> dict:
        return self.log.read_latest() or {"questions": {}}

    def submit(self, entry: QuestionLedgerEntry) -> str:
        state = self._state()
        state["questions"][entry.id] = entry.to_dict()
        self.log.write_checkpoint(state, label="question_ledger")
        return entry.id

    def get(self, question_id: str) -> QuestionLedgerEntry | None:
        raw = self._state()["questions"].get(question_id)
        return QuestionLedgerEntry.from_dict(raw) if raw else None

    def list_by_status(self, status: str) -> list[QuestionLedgerEntry]:
        return [
            QuestionLedgerEntry.from_dict(q)
            for q in self._state()["questions"].values()
            if q["status"] == status
        ]

    def append_version(self, question_id: str, answer: dict) -> None:
        """Never overwrites -- appends a new version, matching the
        Body's permanent-retention, versioned-answer guarantee."""
        state = self._state()
        q = state["questions"][question_id]
        q["versions"].append(answer)
        q["status"] = "completed"
        self.log.write_checkpoint(state, label="question_ledger")

    # deliberately no delete() -- retention is a hard invariant (Section 8)
