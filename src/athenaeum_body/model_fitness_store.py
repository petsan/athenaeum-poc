"""
Model Fitness Tracking STORAGE mechanics (brain-design.md Section 6.7):
per-(agent, model) evidence accumulation, mirroring reputability_store.py's
shape exactly -- Section 6.7 describes this as "the same kind of judgment
the Engine already applies to sources, extended to a second dimension,"
so the storage mechanics are deliberately the same too, not a new design.
Weight computation (the actual judgment) is Brain policy
(athenaeum_brain/model_fitness.py); this module only stores and serves
the raw tallies.
"""
from __future__ import annotations
from dataclasses import dataclass
from .storage.checkpoint import CheckpointLog


def _key(agent_name: str, model_id: str) -> str:
    return f"{agent_name}::{model_id}"


@dataclass
class ModelFitnessStore:
    log: CheckpointLog

    def _state(self) -> dict:
        return self.log.read_latest() or {"tallies": {}}

    def record_outcome(self, agent_name: str, model_id: str, outcome: str) -> None:
        """Section 6.7: did claims produced by this (agent, model) pairing
        survive cross-examination? outcome is 'corroborated' or
        'challenged', the same vocabulary reputability_store.py uses."""
        assert outcome in ("corroborated", "challenged")
        state = self._state()
        tally = state["tallies"].setdefault(_key(agent_name, model_id), {"corroborated": 0, "challenged": 0})
        tally[outcome] += 1
        self.log.write_checkpoint(state, label="model_fitness")

    def tally(self, agent_name: str, model_id: str) -> dict:
        state = self._state()
        return state["tallies"].get(_key(agent_name, model_id), {"corroborated": 0, "challenged": 0})
