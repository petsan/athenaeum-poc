"""
Ingestion pipeline -- mechanical only (Section 9): fetch + license check,
parse/normalize into Provenance schema, a scheduled work-unit type, and a
one-time seed-load path. No reputability judgment here (that's the
Brain's Section 6) -- this only decides whether a source is even
*eligible* to be fetched at all (license/ToS/paid-access), mechanically.

Real network fetch (`fetch_url`, added 2026-09-22) is now available now
that a real, internet-connected guest exists (VMID 104/106) -- the
"no real network available here" blocker noted in earlier sessions no
longer applies. `FixtureSource` remains the normalized shape both a real
fetch and a hand-authored test fixture produce -- the class name predates
`fetch_url` and is kept rather than churned across every caller/test for a
rename alone; what changed is that it's no longer ONLY ever hand-authored.
The same substitution-seam pattern used elsewhere (MockBackend in
model_serving.py, simulate_tier2_outage in tiered.py) still applies for
anything that wants a fixture without a real network round-trip -- both
paths now genuinely exist side by side, not one superseding the other.
"""
from __future__ import annotations
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import dataclass, field
from .schemas import ProvenanceEntry
from .storage.content_addressed import ContentAddressedStore


@dataclass
class FixtureSource:
    """The normalized shape of a fetched URL -- what a real HTTP client
    reported (fetch_url) OR a hand-authored stand-in for one (tests)."""
    url: str
    content: bytes
    license: str          # e.g. "public-domain", "cc-by", "all-rights-reserved"
    is_paid_or_metered: bool = False
    robots_disallowed: bool = False
    cites: list = field(default_factory=list)  # source ids this one cites/derives
                          # from -- caller/curator-supplied like `license`, since
                          # it isn't mechanically derivable from raw content; the
                          # Brain's independence check (dispute_resolution.py)
                          # reads it back from ProvenanceEntry.metadata["cites"]


class FetchError(Exception):
    """A real network fetch failed outright (DNS, connection, HTTP error
    status, timeout) -- distinct from IngestionRejected, which is a
    successful fetch that then failed the license/ToS/paid-access checks.
    Never silently swallowed; the caller decides how to handle it."""


def _robots_allowed(url: str, user_agent: str) -> bool:
    """Real robots.txt check via the stdlib parser. Fails OPEN (allowed)
    only when robots.txt itself is unreachable or absent -- absence of a
    robots.txt is not a disallow signal; a genuinely failed fetch of the
    page itself is a separate, loud FetchError raised by fetch_url, not
    silently converted into a robots disallow here."""
    parsed = urllib.parse.urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(robots_url)
    try:
        rp.read()
    except Exception:
        return True
    return rp.can_fetch(user_agent, url)


def fetch_url(url: str, *, license: str, is_paid_or_metered: bool = False,
               timeout_seconds: float = 10.0,
               user_agent: str = "AthenaeumIngestionBot/0.1") -> FixtureSource:
    """A real HTTP GET (stdlib `urllib` only -- no new dependency, matching
    api.py's own stdlib-only convention), plus a real robots.txt check.
    `license` and `is_paid_or_metered` remain caller-supplied, exactly as
    they always were on FixtureSource -- neither is mechanically
    determinable from an HTTP response alone, so this doesn't pretend
    otherwise; a human/curator still asserts them, same as for a
    hand-authored fixture. Never uses credentials or an API key of any
    kind, keeping every fetch this function performs a plain, freely
    accessible GET (Section 6.6's hard floor, config.py's
    disallow_paid_apis)."""
    robots_disallowed = not _robots_allowed(url, user_agent)
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            content = resp.read()
    except (urllib.error.URLError, OSError) as e:
        raise FetchError(f"fetch failed for {url!r}: {e}") from e
    return FixtureSource(url=url, content=content, license=license,
                          is_paid_or_metered=is_paid_or_metered, robots_disallowed=robots_disallowed)


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
    metadata = {"license": source.license}
    if source.cites:
        metadata["cites"] = list(source.cites)
    return ProvenanceEntry(
        id=source.url,
        content_hash=content_hash,
        metadata=metadata,
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
