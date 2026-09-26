"""
Knowledge Consolidation storage mechanics (brain-design.md Section 10):
tracks per-claim survival state and archives full traces content-
addressed (Tier 3 equivalent), never deleting anything. Promotion
CRITERIA (min cycles/sources, confidence trend) is Brain judgment
(athenaeum_brain/consolidation.py) -- this module only stores and
serves state, matching the split already used for reputability.
"""
from __future__ import annotations
from dataclasses import dataclass
from .storage.checkpoint import CheckpointLog
from .storage.content_addressed import ContentAddressedStore


@dataclass
class ConsolidationStore:
    log: CheckpointLog                  # tracker state: Tier B/C entries
    archive: ContentAddressedStore      # full-trace cold archive (10.3/10.4)

    def _state(self) -> dict:
        return self.log.read_latest() or {"entries": {}}

    def batch(self):
        """Group one idle cycle's updates into one checkpoint: CheckpointLog.batch."""
        return self.log.batch()

    def get(self, key: str) -> dict | None:
        return self._state()["entries"].get(key)

    def entries(self) -> dict:
        """Every tracked entry by key (Section 9.5's audit samples from these)."""
        return dict(self._state()["entries"])

    def upsert(self, key: str, entry: dict) -> None:
        state = self._state()
        state["entries"][key] = entry
        self.log.write_checkpoint(state, label="consolidation")

    def archive_full_trace(self, trace: dict) -> str:
        """Section 10.3/10.4: write the full trace to the content-addressed
        cold archive. Never deletes anything -- returns a durable pointer."""
        return self.archive.put_json(trace)

    def read_full_trace(self, ref: str) -> dict:
        """Section 10.5: de-compaction -- retrieve the full trace on demand."""
        return self.archive.get_json(ref)
