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
        state = self.log.read_latest() or {"tallies": {}}
        state.setdefault("admissions", {})  # absent in checkpoints from before the admission gate
        return state

    # --- Section 6.7 model admission (storage only; the gate's policy is
    # athenaeum_brain/model_fitness.py) -----------------------------------

    def admit(self, model_id: str, rationale: str, admitted_by: str) -> dict:
        """Records a model's admission once; a second admit is a no-op that
        returns the original record (admission history is never rewritten)."""
        state = self._state()
        if model_id not in state["admissions"]:
            state["admissions"][model_id] = {"model_id": model_id, "rationale": rationale,
                                             "admitted_by": admitted_by}
            self.log.write_checkpoint(state, label="model_fitness")
        return state["admissions"][model_id]

    def admission(self, model_id: str) -> dict | None:
        return self._state()["admissions"].get(model_id)

    def outcomes_for_model(self, model_id: str) -> dict:
        """Totals across every agent this model has backed."""
        total = {"corroborated": 0, "challenged": 0}
        for key, tally in self._state()["tallies"].items():
            if key.endswith(f"::{model_id}"):
                for k in total:
                    total[k] += tally[k]
        return total

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
