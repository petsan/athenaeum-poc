"""
Audit report STORAGE (brain-design.md Sections 9.4-9.5): an append-only
history of audit reports by kind, so audit results accumulate as a trend
rather than being printed once and lost. What an audit checks is Brain
judgment (athenaeum_brain/audits.py); this only keeps the reports.
"""
from __future__ import annotations
from dataclasses import dataclass
from .storage.checkpoint import CheckpointLog


@dataclass
class AuditStore:
    log: CheckpointLog

    def _state(self) -> dict:
        return self.log.read_latest() or {"reports": {}}

    def record(self, kind: str, report: dict) -> None:
        """Idempotent on report['audit_id']: recording the same audit twice
        (e.g. a resumed run) keeps one copy."""
        state = self._state()
        reports = state["reports"].setdefault(kind, [])
        if any(r.get("audit_id") == report.get("audit_id") for r in reports):
            return
        reports.append(report)
        self.log.write_checkpoint(state, label="audit")

    def history(self, kind: str) -> list[dict]:
        return self._state()["reports"].get(kind, [])
