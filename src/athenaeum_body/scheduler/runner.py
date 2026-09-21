"""Single-unit runner: round-boundary checkpointing, kill-safe resume (Tasks 12-13)."""
from __future__ import annotations
from ..storage.checkpoint import CheckpointLog
from .work_unit import WorkUnit


class SingleUnitRunner:
    """Executes one work unit's rounds, checkpointing after each one.
    A fresh runner can resume a unit from its last completed round --
    no progress is lost even if the process was killed mid-run."""

    def __init__(self, checkpoint_log: CheckpointLog, shared_state: dict):
        self.log = checkpoint_log
        self.shared_state = shared_state

    def resume_round_index(self, unit_id: str) -> int:
        """How many rounds this unit has already completed, per the
        checkpoint log -- 0 if it has never run."""
        latest = self.log.read_latest()
        if latest is None:
            return 0
        return latest.get("units", {}).get(unit_id, {}).get("round_index", 0)

    def run_round(self, unit: WorkUnit) -> bool:
        """Execute exactly one round of `unit`. Returns True if the unit is
        now done. Checkpoints immediately after the round completes -- the
        round is atomic from the outside: it either fully happened (and is
        checkpointed) or, if interrupted first, never happened at all."""
        result = unit.round_handler(self.shared_state, unit.round_index)
        self.shared_state.update(result.proposed_writes)
        unit.round_index += 1
        if result.done:
            unit.status = "completed"

        # persist: this write IS the atomicity boundary
        prior = self.log.read_latest() or {"units": {}}
        prior.setdefault("units", {})[unit.id] = {
            "round_index": unit.round_index,
            "status": unit.status,
        }
        prior["shared_state"] = self.shared_state
        self.log.write_checkpoint(prior, label=f"unit:{unit.id}")
        return unit.status == "completed"
