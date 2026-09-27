"""
Human input records (Section 11, batch 11 Phase AU): each submission, what
happened to it, and -- for one that waited at a checkpoint -- how the review
ended. Storage only; the judgment is athenaeum_brain/human_input.py.
Append-only like every store here: an input's record gains a status, but the
checkpoint log keeps every earlier state.
"""
from __future__ import annotations
from dataclasses import dataclass
from .storage.checkpoint import CheckpointLog


@dataclass
class HumanInputStore:
    log: CheckpointLog

    def _state(self) -> dict:
        return self.log.read_latest() or {"inputs": {}}

    def record(self, input_id: str, entry: dict) -> dict:
        state = self._state()
        state["inputs"][input_id] = {"id": input_id, **entry}
        self.log.write_checkpoint(state, label="human_inputs")
        return state["inputs"][input_id]

    def set_status(self, input_id: str, status: str, **extra) -> dict:
        state = self._state()
        state["inputs"][input_id].update({"status": status, **extra})
        self.log.write_checkpoint(state, label="human_inputs")
        return state["inputs"][input_id]

    def for_question(self, question_id: str) -> list[dict]:
        return [i for i in self._state()["inputs"].values() if i["question_id"] == question_id]

    def count(self) -> int:
        return len(self._state()["inputs"])
