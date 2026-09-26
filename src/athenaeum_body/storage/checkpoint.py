"""
Append-only, hash-chained checkpoint log.

Implements body-design.md Sections 5.3 (persistence discipline: every
checkpoint is a new entry, never an overwrite) and 3.4 (each entry carries
a reference to the hash of the immediately preceding entry, so the log's
own integrity is verifiable without trusting the storage medium).
"""
from __future__ import annotations

import copy
import time
from contextlib import contextmanager
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Optional

from .content_addressed import ContentAddressedStore, content_hash, IntegrityError


GENESIS_HASH = "sha256:" + "0" * 64


class ChainIntegrityError(Exception):
    """Raised when the checkpoint chain itself has been broken or reordered."""


@dataclass
class CheckpointEntry:
    snapshot_id: str          # content-address of this entry's own canonical form
    prev_hash: str            # content-address of the previous entry (or GENESIS_HASH)
    payload_ref: str          # content-address of the actual checkpointed state blob
    sequence: int             # monotonically increasing position in the chain
    timestamp: float
    label: str = ""           # e.g. "question_ledger", "belief_graph" -- which store

    def canonical_dict(self) -> dict:
        d = asdict(self)
        d.pop("snapshot_id", None)  # snapshot_id is derived FROM this dict, not part of it
        return d


@dataclass
class CheckpointLog:
    """
    One append-only, hash-chained checkpoint log, backed by a
    ContentAddressedStore. Multiple named logs (one per Section 5.1 store)
    can share the same underlying CAS.
    """

    cas: ContentAddressedStore
    index_path: Path  # small local index file: ordered list of entry hashes

    def __post_init__(self) -> None:
        self.index_path = Path(self.index_path)
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.index_path.exists():
            self.index_path.write_text("")
        self._batch_depth = 0
        self._pending: Optional[tuple[Any, str]] = None   # (state, label) written inside a batch

    @contextmanager
    def batch(self):
        """One logical operation, one checkpoint (batch 6, Phase AB). Inside
        the block, write_checkpoint only holds the state in memory and
        read_latest returns (a copy of) it. On a clean exit the last state
        is written as a single entry; on an exception nothing is written, so
        the operation is also atomic. Nests: only the outermost block writes.
        Scoped to this CheckpointLog object -- another object over the same
        index file doesn't see the pending state until it is written."""
        self._batch_depth += 1
        try:
            yield self
        except BaseException:
            if self._batch_depth == 1:
                self._pending = None
            raise
        finally:
            self._batch_depth -= 1
        if self._batch_depth == 0 and self._pending is not None:
            state, label = self._pending
            self._pending = None
            self.write_checkpoint(state, label=label)

    def _read_index(self) -> list[str]:
        text = self.index_path.read_text()
        return [line.strip() for line in text.splitlines() if line.strip()]

    def _append_index(self, entry_hash: str) -> None:
        with self.index_path.open("a") as f:
            f.write(entry_hash + "\n")

    def write_checkpoint(self, state: Any, label: str = "") -> str:
        """Append a new checkpoint entry for `state`. Returns the new
        checkpoint's snapshot_id. This never overwrites a prior entry.
        Inside a batch() the state is only held (a copy, like a real write)
        and None is returned; the batch writes it on exit."""
        if self._batch_depth:
            self._pending = (copy.deepcopy(state), label)
            return None
        index = self._read_index()
        prev_hash = index[-1] if index else GENESIS_HASH
        payload_ref = self.cas.put_json(state)

        entry = CheckpointEntry(
            snapshot_id="",  # filled below
            prev_hash=prev_hash,
            payload_ref=payload_ref,
            sequence=len(index),
            timestamp=time.time(),
            label=label,
        )
        canonical = entry.canonical_dict()
        entry_hash = self.cas.put_json(canonical)  # address IS the hash of the canonical form
        entry.snapshot_id = entry_hash

        self._append_index(entry_hash)
        return entry_hash

    def read_entry(self, snapshot_id: str) -> CheckpointEntry:
        # The stored object is the canonical form (snapshot_id excluded, since
        # snapshot_id is derived FROM it) -- reattach it on read.
        data = self.cas.get_json(snapshot_id)
        return CheckpointEntry(snapshot_id=snapshot_id, **data)

    def read_state(self, snapshot_id: str) -> Any:
        entry = self.read_entry(snapshot_id)
        return self.cas.get_json(entry.payload_ref)

    def latest_snapshot_id(self) -> Optional[str]:
        index = self._read_index()
        return index[-1] if index else None

    def read_latest(self) -> Optional[Any]:
        """Reload the most recent state, or None if the log is empty --
        this is what boot-from-checkpoint (Section 3.1) calls."""
        if self._pending is not None:
            return copy.deepcopy(self._pending[0])
        latest = self.latest_snapshot_id()
        if latest is None:
            return None
        return self.read_state(latest)

    def all_entries(self) -> list[CheckpointEntry]:
        return [self.read_entry(h) for h in self._read_index()]

    def verify_chain(self) -> bool:
        """Walk the entire chain verifying that each entry's prev_hash
        correctly links to the previous entry's own hash, and that every
        entry's stored content still matches its content-address (which
        `read_entry`/`cas.get_json` already enforces on every call).

        Raises ChainIntegrityError with details on the first break found;
        returns True if the whole chain is intact.
        """
        index = self._read_index()
        expected_prev = GENESIS_HASH
        for i, entry_hash in enumerate(index):
            try:
                entry = self.read_entry(entry_hash)
                self.cas.get(entry.payload_ref)  # also verifies the payload itself
            except IntegrityError as e:
                raise ChainIntegrityError(
                    f"checkpoint entry at sequence {i} is corrupted: {e}"
                ) from e
            if entry.prev_hash != expected_prev:
                raise ChainIntegrityError(
                    f"chain break at sequence {i}: expected prev_hash "
                    f"{expected_prev}, found {entry.prev_hash}"
                )
            if entry.sequence != i:
                raise ChainIntegrityError(
                    f"sequence mismatch at position {i}: entry claims sequence {entry.sequence}"
                )
            expected_prev = entry_hash
        return True

    def last_good_snapshot_id(self) -> Optional[str]:
        """Recovery helper (Section 10 fault-injection): walk the chain from
        the end backward and return the most recent entry that is still
        intact, for falling back past a corrupted tail entry."""
        index = self._read_index()
        for entry_hash in reversed(index):
            try:
                self.read_entry(entry_hash)
                return entry_hash
            except IntegrityError:
                continue
        return None
