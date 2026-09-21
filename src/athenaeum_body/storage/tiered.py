"""
Tiered storage with automatic Tier 2 -> Tier 3 fallback.

Implements body-design.md Section 3.3: Tier 2 (network NVMe) is not
guaranteed available. Reads/writes prefer Tier 2, fall back to Tier 3 when
Tier 2 is unreachable, and automatically resume preferring Tier 2 once it
reappears -- no manual failback.

For this proof-of-work demo, "unreachable" is a settable flag rather than
a real network probe, so tests and the demo script can deterministically
exercise the fallback path.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

from .content_addressed import ContentAddressedStore, NotFoundError


@dataclass
class TieredStore:
    tier2: ContentAddressedStore  # NVMe-over-LAN equivalent (hot cache)
    tier3: ContentAddressedStore  # local HDD equivalent (system of record)
    _tier2_reachable: bool = True

    @property
    def tier2_reachable(self) -> bool:
        return self._tier2_reachable

    def set_tier2_reachable(self, reachable: bool) -> None:
        self._tier2_reachable = reachable

    @contextmanager
    def simulate_tier2_outage(self):
        """Test/demo helper: temporarily mark Tier 2 unreachable."""
        prev = self._tier2_reachable
        self._tier2_reachable = False
        try:
            yield
        finally:
            self._tier2_reachable = prev

    def put(self, data: bytes) -> str:
        """Write-through: always durable to Tier 3 (system of record);
        additionally cached to Tier 2 when reachable, for speed."""
        key = self.tier3.put(data)
        if self._tier2_reachable:
            self.tier2.put(data)
        return key

    def get(self, key: str) -> bytes:
        """Prefer Tier 2 (fast) when reachable and holding the object;
        fall back to Tier 3 (system of record) otherwise. A successful
        Tier 3 read opportunistically warms Tier 2's cache."""
        if self._tier2_reachable and self.tier2.exists(key):
            return self.tier2.get(key)
        data = self.tier3.get(key)
        if self._tier2_reachable and not self.tier2.exists(key):
            self.tier2.put(data)  # warm the cache now that we have it
        return data

    def exists(self, key: str) -> bool:
        if self._tier2_reachable and self.tier2.exists(key):
            return True
        return self.tier3.exists(key)
