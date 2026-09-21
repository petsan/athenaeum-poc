"""
Content-addressed, tamper-evident storage.

Implements body-design.md Section 3.4: every object is stored under a key
derived from a hash of its own content. Any modification to stored content
changes its address, so tampering is detectable on read rather than being
silently served.

This is a filesystem-backed reference implementation intended for local
development and testing. A real deployment would target the Body's actual
Tier 2 / Tier 3 storage, but the interface and guarantees are identical.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


class IntegrityError(Exception):
    """Raised when stored content does not match its content-address."""


class NotFoundError(Exception):
    """Raised when a requested content-address does not exist in this store."""


def content_hash(data: bytes) -> str:
    """The canonical hashing scheme used for every content-addressed object."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


@dataclass
class ContentAddressedStore:
    """
    A minimal content-addressed object store.

    Objects are stored as raw bytes under <root>/<hash-prefix>/<hash>.
    Any caller can independently verify an object's integrity by
    re-hashing it on read, which `get()` does automatically.
    """

    root: Path

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str) -> Path:
        # key looks like "sha256:abcdef..." -- shard by the first 2 hex chars
        # to avoid dumping everything into one directory.
        algo, _, digest = key.partition(":")
        shard = digest[:2] if digest else "00"
        return self.root / algo / shard / digest

    def put(self, data: bytes) -> str:
        """Store bytes, return their content-address. Idempotent: storing the
        same content twice returns the same address and does not duplicate."""
        key = content_hash(data)
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)  # atomic on POSIX filesystems
        return key

    def put_json(self, obj) -> str:
        """Convenience: serialize a JSON-able object and store it."""
        data = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return self.put(data)

    def get(self, key: str) -> bytes:
        """Retrieve bytes by content-address, verifying integrity on read.

        Raises IntegrityError if the stored content no longer matches its
        own address (tamper/corruption detection per Section 3.4) and
        NotFoundError if the address does not exist at all.
        """
        path = self._path_for(key)
        if not path.exists():
            raise NotFoundError(f"no object found for {key}")
        data = path.read_bytes()
        actual = content_hash(data)
        if actual != key:
            raise IntegrityError(
                f"content-address mismatch for {key}: "
                f"stored content now hashes to {actual}. "
                f"This object has been corrupted or tampered with."
            )
        return data

    def get_json(self, key: str):
        return json.loads(self.get(key).decode("utf-8"))

    def exists(self, key: str) -> bool:
        return self._path_for(key).exists()

    def list_keys(self) -> Iterator[str]:
        for algo_dir in self.root.iterdir():
            if not algo_dir.is_dir():
                continue
            for shard_dir in algo_dir.iterdir():
                if not shard_dir.is_dir():
                    continue
                for obj in shard_dir.iterdir():
                    yield f"{algo_dir.name}:{obj.name}"

    def corrupt_for_testing(self, key: str, new_bytes: bytes) -> None:
        """Test-only helper: overwrite stored content without updating its
        address, to simulate on-disk corruption/tampering for fault-injection
        tests (see tests/test_content_addressed.py)."""
        path = self._path_for(key)
        path.write_bytes(new_bytes)
