"""
Ingestion pipeline -- mechanical only (Section 9): fetch + license check,
parse/normalize into Provenance schema, a scheduled work-unit type, and a
one-time seed-load path. No reputability judgment here (that's the
Brain's Section 6) -- this only decides whether a source is even
*eligible* to be fetched at all (license/ToS/paid-access), mechanically.

No real network access in this environment -- `fetch()` takes a
FixtureSource standing in for a real HTTP fetch, exactly the same
substitution pattern used for MockBackend (model_serving.py) and
simulate_tier2_outage (tiered.py): the interface is real and testable,
the transport underneath is swapped for something deterministic.
"""
from __future__ import annotations
from dataclasses import dataclass
from .schemas import ProvenanceEntry
from .storage.content_addressed import ContentAddressedStore


@dataclass
class FixtureSource:
    """Stand-in for a fetched URL: what a real HTTP client would report."""
    url: str
    content: bytes
    license: str          # e.g. "public-domain", "cc-by", "all-rights-reserved"
    is_paid_or_metered: bool = False
    robots_disallowed: bool = False


class IngestionRejected(Exception):
    pass


def fetch_and_check(source: FixtureSource) -> dict:
    """Section 9, step 1: accept/reject + reason. Hard invariants, not
    policy the caller can override -- mirrors config.py's disallow_paid_apis."""
    if source.is_paid_or_metered:
        return {"accepted": False, "reason": "paid or metered access -- hard invariant, never fetched"}
    if source.robots_disallowed:
        return {"accepted": False, "reason": "robots/ToS disallows access"}
    if source.license == "all-rights-reserved":
        return {"accepted": False, "reason": "no license permitting reuse"}
    return {"accepted": True, "reason": "license and access checks passed"}


def parse_and_normalize(source: FixtureSource, cas: ContentAddressedStore) -> ProvenanceEntry:
    """Section 9, step 2: accepted raw source -> Provenance Ledger schema.
    Caller must have already checked fetch_and_check(source)['accepted']."""
    content_hash = cas.put(source.content)  # durable, tamper-evident (3.4)
    return ProvenanceEntry(
        id=source.url,
        content_hash=content_hash,
        metadata={"license": source.license},
    )


def ingest(source: FixtureSource, cas: ContentAddressedStore) -> ProvenanceEntry:
    """The full mechanical pipeline: check, then parse. Raises
    IngestionRejected rather than silently skipping, so a caller always
    knows whether ingestion happened."""
    check = fetch_and_check(source)
    if not check["accepted"]:
        raise IngestionRejected(check["reason"])
    return parse_and_normalize(source, cas)


def seed_load(sources: list[FixtureSource], cas: ContentAddressedStore) -> list[ProvenanceEntry]:
    """Section 9, step 4: one-time foundational corpus load. Deliberately
    a separate entry point from `ingest()` used by ongoing ingestion, even
    though the underlying logic is identical -- keeps the one-shot seed
    path auditable independently of steady-state ingestion volume."""
    entries = []
    for s in sources:
        try:
            entries.append(ingest(s, cas))
        except IngestionRejected:
            continue  # a rejected seed source is skipped, not fatal to the batch
    return entries
