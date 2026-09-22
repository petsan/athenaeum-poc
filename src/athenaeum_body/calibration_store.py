"""
Calibration tracking STORAGE mechanics (brain-design.md Section 5.3):
per-agent record of confidence-bucketed claims and whether they were
later verified/survived. Matches the existing storage-only pattern
(reputability_store.py, model_fitness_store.py) -- bucketing/scoring
judgment lives in athenaeum_brain/evaluation.py.
"""
from __future__ import annotations
from dataclasses import dataclass
from .storage.checkpoint import CheckpointLog


def confidence_bucket(confidence: float) -> str:
    """Coarse deciles are enough to see drift without needing so many
    buckets that each one is starved of data in a small POC."""
    if confidence >= 1.0:
        return "1.0"
    return f"{int(confidence * 10) / 10:.1f}-{int(confidence * 10) / 10 + 0.1:.1f}"


@dataclass
class CalibrationStore:
    log: CheckpointLog

    def _state(self) -> dict:
        return self.log.read_latest() or {"records": {}}

    def record(self, agent_name: str, confidence: float, verified: bool) -> None:
        """Section 5.3: 'of claims made at confidence level X, what
        fraction later survived idle-evolution re-challenge or external
        verification, versus were overturned' -- one tally per (agent,
        bucket)."""
        bucket = confidence_bucket(confidence)
        state = self._state()
        per_agent = state["records"].setdefault(agent_name, {})
        tally = per_agent.setdefault(bucket, {"verified": 0, "overturned": 0})
        tally["verified" if verified else "overturned"] += 1
        self.log.write_checkpoint(state, label="calibration")

    def record_for_agent(self, agent_name: str) -> dict:
        return self._state()["records"].get(agent_name, {})
