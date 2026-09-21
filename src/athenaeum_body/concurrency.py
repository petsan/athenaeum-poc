"""Idempotency keys + expected-version writes (body-design.md Section 7.5)."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict


class ConflictError(Exception):
    """Raised when a write's expected_version doesn't match current state."""


@dataclass
class VersionedStore:
    """Generic in-memory key/value store with optimistic concurrency."""
    _data: Dict[str, Any] = field(default_factory=dict)
    _versions: Dict[str, int] = field(default_factory=dict)
    _idempotency_cache: Dict[str, Any] = field(default_factory=dict)

    def get(self, key: str):
        return self._data.get(key), self._versions.get(key, 0)

    def put(self, key: str, value: Any, expected_version: int, idempotency_key: str = None):
        if idempotency_key and idempotency_key in self._idempotency_cache:
            return self._idempotency_cache[idempotency_key]  # duplicate retry: no-op replay
        current = self._versions.get(key, 0)
        if current != expected_version:
            raise ConflictError(
                f"expected version {expected_version} for '{key}', found {current}"
            )
        self._data[key] = value
        self._versions[key] = current + 1
        result = {"key": key, "version": current + 1}
        if idempotency_key:
            self._idempotency_cache[idempotency_key] = result
        return result
