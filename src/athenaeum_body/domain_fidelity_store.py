"""
Domain Fidelity storage mechanics (brain-design.md Section 2.4.2):
an append-only history of per-agent fidelity scores over time, so drift
can be detected as a trend, not just a single reading. Score computation
itself is Brain judgment (athenaeum_brain/domain_fidelity.py).
"""
from __future__ import annotations
from dataclasses import dataclass
from .storage.checkpoint import CheckpointLog


@dataclass
class DomainFidelityStore:
    log: CheckpointLog

    def _state(self) -> dict:
        return self.log.read_latest() or {"history": {}}

    def record(self, agent_name: str, score_result: dict) -> None:
        state = self._state()
        state["history"].setdefault(agent_name, []).append(score_result)
        self.log.write_checkpoint(state, label="domain_fidelity")

    def history_for(self, agent_name: str) -> list[dict]:
        return self._state()["history"].get(agent_name, [])
