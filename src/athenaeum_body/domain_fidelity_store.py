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
        state = self.log.read_latest() or {"history": {}}
        state.setdefault("remediation", {})  # absent in checkpoints from before Section 2.4.3
        return state

    def remediation(self, agent_name: str) -> dict | None:
        """Section 2.4.3's remediation record for an agent (stage + full
        stage history). The state machine itself is Brain judgment
        (athenaeum_brain/fidelity_remediation.py)."""
        return self._state()["remediation"].get(agent_name)

    def set_remediation(self, agent_name: str, record: dict) -> None:
        state = self._state()
        state["remediation"][agent_name] = record
        self.log.write_checkpoint(state, label="domain_fidelity")

    def agents_in_stage(self, *stages: str) -> list[str]:
        return sorted(a for a, r in self._state()["remediation"].items() if r["stage"] in stages)

    def record(self, agent_name: str, score_result: dict) -> None:
        state = self._state()
        state["history"].setdefault(agent_name, []).append(score_result)
        self.log.write_checkpoint(state, label="domain_fidelity")

    def history_for(self, agent_name: str) -> list[dict]:
        return self._state()["history"].get(agent_name, [])
