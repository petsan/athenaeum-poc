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
        state = self.log.read_latest() or {"records": {}}
        state.setdefault("claims", {})  # absent in checkpoints from before per-claim outcomes
        return state

    def set_outcome(self, claim_key: str, agent_name: str, confidence: float, verified: bool) -> None:
        """Per-CLAIM outcome, overwritten when the claim's fate changes: one
        claim contributes exactly once, with its latest known fate. Idle
        evolution re-examines the same claims every cycle; tallying each
        re-examination would let a single long-lived claim swamp its agent's
        calibration record. Idempotent: writing an unchanged outcome is a no-op."""
        state = self._state()
        new = {"agent": agent_name, "confidence": confidence, "verified": verified}
        if state["claims"].get(claim_key) == new:
            return
        state["claims"][claim_key] = new
        self.log.write_checkpoint(state, label="calibration")

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
        """Tallies per bucket: explicit `record` calls plus every per-claim
        outcome (`set_outcome`) for this agent, each claim counted once."""
        state = self._state()
        merged = {b: dict(t) for b, t in state["records"].get(agent_name, {}).items()}
        for outcome in state["claims"].values():
            if outcome["agent"] != agent_name:
                continue
            tally = merged.setdefault(confidence_bucket(outcome["confidence"]), {"verified": 0, "overturned": 0})
            tally["verified" if outcome["verified"] else "overturned"] += 1
        return merged

    def agents(self) -> list[str]:
        state = self._state()
        return sorted(set(state["records"]) | {o["agent"] for o in state["claims"].values()})
