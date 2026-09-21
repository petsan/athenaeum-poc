"""
Reputability Engine STORAGE mechanics (brain-design.md Section 6):
versioned grading, evidence accumulation, non-retroactive attachment,
and the dispute-resolution log. The Body stores and serves this data;
the grading *policy* below is a simple, explicitly-labeled placeholder --
real judgment (brain-design.md 6.1-6.5) is a Brain concern once a model
is backing it, not implemented here.
"""
from __future__ import annotations
from dataclasses import dataclass
from .storage.checkpoint import CheckpointLog

# Ordinal scale for materiality comparisons (athenaeum_brain/reevaluation.py).
# Placeholder policy -- not the real, evolving Reputability standard (Section 6.5).
GRADE_ORDER = ["rejected", "contested", "provisionally_accepted", "foundational"]


def _grade_from_tally(corroborated: int, challenged: int) -> str:
    """Explicitly a placeholder policy, not the real judgment (Section 6.1)."""
    if corroborated == 0 and challenged >= 3:
        return "rejected"
    if challenged > 0 and challenged >= corroborated:
        return "contested"
    if corroborated >= 5 and challenged == 0:
        return "foundational"
    return "provisionally_accepted"


@dataclass
class ReputabilityStore:
    log: CheckpointLog

    def _state(self) -> dict:
        return self.log.read_latest() or {"tallies": {}, "grade_versions": {}, "disputes": []}

    def record_outcome(self, subject_id: str, subject_type: str, outcome: str) -> None:
        """Section 6.2: every use of a source records an outcome against it.
        outcome is 'corroborated' or 'challenged'."""
        assert outcome in ("corroborated", "challenged")
        state = self._state()
        tally = state["tallies"].setdefault(subject_id, {"subject_type": subject_type, "corroborated": 0, "challenged": 0})
        tally[outcome] += 1
        new_grade = _grade_from_tally(tally["corroborated"], tally["challenged"])
        versions = state["grade_versions"].setdefault(subject_id, [])
        if not versions or versions[-1]["grade"] != new_grade:
            versions.append({"grade": new_grade, "version": len(versions)})
        self.log.write_checkpoint(state, label="reputability")

    def current_grade(self, subject_id: str) -> dict:
        """Returns {'grade': ..., 'version': ...} -- the LIVE current grade,
        which may differ from a grade snapshotted at an earlier time-of-use
        (Section 6.3's non-retroactive-attachment guarantee)."""
        state = self._state()
        versions = state["grade_versions"].get(subject_id)
        if not versions:
            return {"grade": "provisionally_accepted", "version": 0}  # ungraded default
        return versions[-1]

    def log_dispute(self, subject_id: str, claim_ids: list[str], rationale: str, ruling: str) -> None:
        """Section 6.4: dispute resolution, logged permanently with rationale."""
        state = self._state()
        state["disputes"].append({
            "subject_id": subject_id, "claim_ids": claim_ids,
            "rationale": rationale, "ruling": ruling,
        })
        self.log.write_checkpoint(state, label="reputability")

    def disputes_for(self, subject_id: str) -> list[dict]:
        return [d for d in self._state()["disputes"] if d["subject_id"] == subject_id]
