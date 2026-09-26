"""
Human checkpoint lifecycle STORAGE mechanics (brain-design.md Section 11.5):
tracks pending_human_checkpoint -> current transitions and their full
history. Matches the Body/Brain storage-vs-judgment split already used
for reputability_store.py and consolidation_store.py -- role enforcement
and conflict-of-interest checking is Brain judgment
(athenaeum_brain/human_input.py), this module only stores and serves
state.
"""
from __future__ import annotations
from dataclasses import dataclass
from .storage.checkpoint import CheckpointLog


@dataclass
class HumanCheckpointStore:
    log: CheckpointLog

    def _state(self) -> dict:
        return self.log.read_latest() or {"checkpoints": {}}

    def set_pending(self, question_id: str, reason: str, triggering_claim_id: str, submitter_id: str) -> dict:
        state = self._state()
        prior = state["checkpoints"].get(question_id, {})
        state["checkpoints"][question_id] = {
            "status": "pending_human_checkpoint",
            "reason": reason,
            "triggering_claim_id": triggering_claim_id,
            "submitter_id": submitter_id,
            "reviewer_id": None,
            "note": None,
            "history": prior.get("history", []) + ["pending_human_checkpoint"],
        }
        self.log.write_checkpoint(state, label="human_checkpoint")
        return state["checkpoints"][question_id]

    def get(self, question_id: str) -> dict | None:
        return self._state()["checkpoints"].get(question_id)

    def all(self) -> dict[str, dict]:
        """Every tracked checkpoint by key, whatever its status."""
        return self._state()["checkpoints"]

    def _transition(self, question_id: str, new_status: str, reviewer_id: str, note: str | None) -> dict:
        state = self._state()
        cp = state["checkpoints"].get(question_id)
        if cp is None:
            raise KeyError(f"no checkpoint tracked for {question_id!r}")
        cp["status"] = new_status
        cp["reviewer_id"] = reviewer_id
        cp["note"] = note
        cp["history"].append(new_status)
        self.log.write_checkpoint(state, label="human_checkpoint")
        return cp

    def approve(self, question_id: str, reviewer_id: str) -> dict:
        return self._transition(question_id, "current", reviewer_id, note=None)

    def reject_with_note(self, question_id: str, reviewer_id: str, note: str) -> dict:
        """Section 11.4/11.5: a rejection is not a silent drop, and not a
        unilateral override either -- it stays pending_human_checkpoint
        (the answer does NOT become current) while the note re-enters the
        loop as a new human_input claim (Brain-side, athenaeum_brain.
        human_input.submit_human_input), not by this store deciding
        anything on its own."""
        return self._transition(question_id, "pending_human_checkpoint", reviewer_id, note=note)

    def request_more_deliberation(self, question_id: str, reviewer_id: str) -> dict:
        return self._transition(question_id, "pending_human_checkpoint", reviewer_id,
                                 note="more deliberation requested")
