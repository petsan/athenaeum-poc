"""Question Ledger CRUD -- permanent retention, append-only versions (Task 11).

Layout 2 (owner decision 8, 2026-09-26): one checkpoint log per question.
The log this ledger is given is the INDEX -- {"layout": 2, "ids": [...]},
in submission order -- and each question's entry lives in its own log in a
sibling directory (`<index stem>.questions/`). A write now costs one
question's size instead of the whole ledger's, which made storage grow
quadratically (progress §76). Every log is still append-only.

A layout-1 ledger (one log whose every checkpoint held all questions) is
migrated when first opened: each question is written to its own log, then
the index is written. The old full snapshots stay in the index log's
history, since nothing is ever removed. Migration is idempotent, so an
interrupted one simply runs again.
"""
from __future__ import annotations
import copy
import hashlib
import re
from pathlib import Path
from .storage.checkpoint import CheckpointLog
from .schemas import QuestionLedgerEntry

LAYOUT = 2


class QuestionLedger:
    def __init__(self, checkpoint_log: CheckpointLog):
        self.log = checkpoint_log                     # the index
        index_path = Path(checkpoint_log.index_path)
        self._dir = index_path.parent / f"{index_path.stem}.questions"
        self._logs: dict[str, CheckpointLog] = {}
        self._cache: dict[str, tuple[str, dict]] = {}  # id -> (its log's latest snapshot id, entry)
        self._migrate_if_needed()

    # --- layout ------------------------------------------------------------------

    def _path_for(self, question_id: str) -> Path:
        # readable, filesystem-safe, and collision-free (distinct ids can
        # sanitize to the same text, never to the same hash)
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", question_id)[:40]
        digest = hashlib.sha256(question_id.encode("utf-8")).hexdigest()[:12]
        return self._dir / f"{safe}-{digest}.txt"

    def _log_for(self, question_id: str) -> CheckpointLog:
        if question_id not in self._logs:
            self._logs[question_id] = CheckpointLog(cas=self.log.cas, index_path=self._path_for(question_id))
        return self._logs[question_id]

    def _exists(self, question_id: str) -> bool:
        log = self._logs.get(question_id)
        if log is not None:
            return log._pending is not None or log.latest_snapshot_id() is not None
        path = self._path_for(question_id)
        return path.exists() and path.stat().st_size > 0

    def _ids(self) -> list[str]:
        return (self.log.read_latest() or {}).get("ids", [])

    def _migrate_if_needed(self) -> None:
        legacy = self.log.read_latest()
        if not legacy or "layout" in legacy or "questions" not in legacy:
            return
        for qid, entry in legacy["questions"].items():
            log = self._log_for(qid)
            if log.read_latest() != entry:      # idempotent: an interrupted migration just resumes
                log.write_checkpoint(entry, label="question_ledger (migrated from layout 1)")
        # Layout 1 kept questions in a dict, and canonical JSON sorts keys, so
        # it never actually preserved submission order; created_at recovers it.
        ids = sorted(legacy["questions"], key=lambda q: (legacy["questions"][q].get("created_at", 0), q))
        self.log.write_checkpoint({"layout": LAYOUT, "ids": ids,
                                   "migrated_from": self.log.latest_snapshot_id()},
                                  label="question_ledger_index")

    def _entry(self, question_id: str) -> dict:
        """A private copy of the question's current entry. Unchanged entries
        come from a cache keyed on their log's latest snapshot id, so a read
        of many questions touches one small index file each, not every blob."""
        log = self._log_for(question_id)
        if log._pending is not None:            # inside a batch: its pending state is the truth
            return log.read_latest()
        latest = log.latest_snapshot_id()
        if latest is None:
            raise KeyError(question_id)
        cached = self._cache.get(question_id)
        if cached is None or cached[0] != latest:
            cached = (latest, log.read_state(latest))
            self._cache[question_id] = cached
        return copy.deepcopy(cached[1])

    def _write(self, question_id: str, entry: dict) -> None:
        self._log_for(question_id).write_checkpoint(entry, label="question")

    def batch(self, question_id: str):
        """Group writes to one question into one checkpoint (CheckpointLog.batch)."""
        return self._log_for(question_id).batch()

    # --- the ledger's interface (unchanged) ---------------------------------------------

    def _state(self) -> dict:
        """Every question, in submission order -- the layout-1 shape, which
        callers still read."""
        return {"questions": {qid: self._entry(qid) for qid in self._ids()}}

    def count(self) -> int:
        return len(self._ids())

    def submit(self, entry: QuestionLedgerEntry) -> str:
        self._write(entry.id, entry.to_dict())
        ids = self._ids()
        if entry.id not in ids:
            self.log.write_checkpoint({"layout": LAYOUT, "ids": ids + [entry.id]}, label="question_ledger_index")
        return entry.id

    def get(self, question_id: str) -> QuestionLedgerEntry | None:
        if not self._exists(question_id):
            return None
        return QuestionLedgerEntry.from_dict(self._entry(question_id))

    def list_by_status(self, status: str) -> list[QuestionLedgerEntry]:
        return [QuestionLedgerEntry.from_dict(q) for q in self._state()["questions"].values()
                if q["status"] == status]

    def append_version(self, question_id: str, answer: dict) -> None:
        """Never overwrites -- appends a new version, matching the
        Body's permanent-retention, versioned-answer guarantee."""
        q = self._entry(question_id)
        q["versions"].append(answer)
        q["status"] = "completed"
        self._write(question_id, q)

    STATUSES = ("queued", "active", "suspended", "completed", "archived")

    def set_status(self, question_id: str, status: str) -> None:
        """The Question Ledger lifecycle (schemas.md): queued -> active ->
        completed, with suspended/archived available. append_version still
        marks a question completed itself."""
        if status not in self.STATUSES:
            raise ValueError(f"unknown status {status!r}; expected one of {self.STATUSES}")
        q = self._entry(question_id)
        q["status"] = status
        self._write(question_id, q)

    def update_importance(self, question_id: str, importance: float) -> None:
        """Section 7.1: importance is assigned at submission and revisable.
        The value itself is the Brain's judgment (reopening.importance_rating);
        this only stores it. Earlier values stay recoverable from the
        question's own append-only log."""
        if not 0.0 <= importance <= 1.0:
            raise ValueError(f"importance must be in [0, 1], got {importance}")
        q = self._entry(question_id)
        q["importance"] = importance
        self._write(question_id, q)

    # deliberately no delete() -- retention is a hard invariant (Section 8)
