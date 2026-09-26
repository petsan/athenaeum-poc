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
from .belief_graph_store import BeliefGraphStore
from .scheduler.work_unit import WorkUnit, RoundResult


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


def host_allowed(url: str, allowlist) -> bool:
    """An http(s) URL whose host is on the curator allow-list, exactly or as
    a subdomain of an entry (owner decision 7). Anything else -- another
    scheme, no host, an unlisted host -- is not allowed."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    return any(host == entry or host.endswith("." + entry) for entry in allowlist)


class _GuardedRedirects(urllib.request.HTTPRedirectHandler):
    """Refuses any redirect whose target fails `ok`: an allow-listed host
    must not be able to bounce a fetch to an internal address (SSRF)."""

    def __init__(self, ok):
        super().__init__()
        self.ok = ok

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not self.ok(newurl):
            raise urllib.error.URLError(f"redirect to {newurl!r} refused: not on the ingestion allow-list")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _robots_allowed(url: str, user_agent: str, opener=None) -> bool:
    """Real robots.txt check via the stdlib parser. Fails OPEN (allowed)
    only when robots.txt itself is unreachable or absent -- absence of a
    robots.txt is not a disallow signal; a genuinely failed fetch of the
    page itself is a separate, loud FetchError raised by fetch_url, not
    silently converted into a robots disallow here. With a guarded
    `opener`, robots.txt is fetched through it too: RobotFileParser.read()
    would otherwise follow any redirect on its own."""
    parsed = urllib.parse.urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(robots_url)
    try:
        if opener is None:
            rp.read()
        else:
            req = urllib.request.Request(robots_url, headers={"User-Agent": user_agent})
            with opener.open(req, timeout=10) as resp:
                rp.parse(resp.read().decode("utf-8", errors="replace").splitlines())
    except Exception:
        return True
    return rp.can_fetch(user_agent, url)


def fetch_url(url: str, *, license: str, is_paid_or_metered: bool = False,
               timeout_seconds: float = 10.0,
               user_agent: str = "AthenaeumIngestionBot/0.1", redirect_ok=None) -> FixtureSource:
    """A real HTTP GET (stdlib `urllib` only -- no new dependency, matching
    api.py's own stdlib-only convention), plus a real robots.txt check.
    `license` and `is_paid_or_metered` remain caller-supplied, exactly as
    they always were on FixtureSource -- neither is mechanically
    determinable from an HTTP response alone, so this doesn't pretend
    otherwise; a human/curator still asserts them, same as for a
    hand-authored fixture. Never uses credentials or an API key of any
    kind, keeping every fetch this function performs a plain, freely
    accessible GET (Section 6.6's hard floor, config.py's
    disallow_paid_apis).

    `redirect_ok(url) -> bool`, when given, is checked for every redirect
    (of robots.txt and of the page): a refused redirect is a FetchError."""
    opener = urllib.request.build_opener(_GuardedRedirects(redirect_ok)) if redirect_ok else None
    robots_disallowed = not _robots_allowed(url, user_agent, opener)
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with (opener.open(req, timeout=timeout_seconds) if opener
              else urllib.request.urlopen(req, timeout=timeout_seconds)) as resp:
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


def ingest(source: FixtureSource, cas: ContentAddressedStore, graph: BeliefGraphStore | None = None) -> ProvenanceEntry:
    """The full mechanical pipeline: check, then parse. Raises
    IngestionRejected rather than silently skipping, so a caller always
    knows whether ingestion happened. With a Belief Graph, the accepted
    source is recorded as a `source:<id>` node (license, content hash) with
    a `cites` edge to each source it cites -- the graph is then where
    dispute resolution and consolidation read citation data from."""
    check = fetch_and_check(source)
    if not check["accepted"]:
        raise IngestionRejected(check["reason"])
    entry = parse_and_normalize(source, cas)
    if graph is not None:
        record_source(graph, entry)
    return entry


def record_source(graph: BeliefGraphStore, entry: ProvenanceEntry) -> None:
    """Idempotent: nodes and edges are write-once. A cited source that
    hasn't been ingested yet gets a bare node, filled in by its own ingest.
    One checkpoint per source."""
    node_id = f"source:{entry.id}"
    with graph.batch():
        graph.add_node(node_id, "source", {"license": entry.metadata.get("license"),
                                           "content_hash": entry.content_hash})
        for cited in entry.metadata.get("cites", []):
            graph.add_node(f"source:{cited}", "source", {})
            graph.add_edge(node_id, f"source:{cited}", "cites")


def source_from_spec(spec: dict, fetch=None) -> FixtureSource:
    """A JSON-safe source spec -> FixtureSource. With `content` (text) it is
    a hand-authored fixture; otherwise the URL is fetched for real.
    `license`, `is_paid_or_metered` and `cites` are curator-asserted either
    way. `fetch` defaults to fetch_url (a seam for tests)."""
    if "content" in spec:
        return FixtureSource(url=spec["url"], content=spec["content"].encode("utf-8"), license=spec["license"],
                             is_paid_or_metered=spec.get("is_paid_or_metered", False),
                             robots_disallowed=spec.get("robots_disallowed", False),
                             cites=list(spec.get("cites", [])))
    if spec.get("is_paid_or_metered"):
        # never even requested (6.6's hard floor): the check below rejects it
        return FixtureSource(url=spec["url"], content=b"", license=spec["license"], is_paid_or_metered=True)
    source = (fetch or fetch_url)(spec["url"], license=spec["license"])
    source.cites = list(spec.get("cites", []))
    return source


def make_ingestion_unit(batch_id: str, sources: list[dict], cas: ContentAddressedStore,
                        graph: BeliefGraphStore | None = None, *, priority: int = -1, fetch=None):
    """Section 9's scheduled ingestion, as an ordinary checkpointed WorkUnit:
    round i fetches, checks, normalizes and records source i. Its outcome
    lands under `ingestion:<batch_id>`, and the last round also writes
    `ingestion_result`.

    Kill-safety: a round's writes (CAS put, graph nodes and edges) are all
    idempotent, and a round is checkpointed once done. So a resume re-runs
    only the round in flight: that one source may be fetched again, but
    nothing is ever recorded twice, and a completed source is never
    re-fetched. A fetch that fails is an outcome (`fetch failed: ...`), not
    an exception, so one unreachable URL doesn't stop the batch."""
    ns = f"ingestion:{batch_id}"

    def handler(state: dict, round_index: int) -> RoundResult:
        mine = state.get(ns, {"outcomes": []})
        if round_index < len(sources):
            spec = sources[round_index]
            try:
                source = source_from_spec(spec, fetch)
            except FetchError as e:
                outcome = {"url": spec["url"], "accepted": False, "reason": f"fetch failed: {e}"}
            else:
                check = fetch_and_check(source)
                outcome = {"url": spec["url"], "accepted": check["accepted"], "reason": check["reason"]}
                if check["accepted"]:
                    entry = parse_and_normalize(source, cas)
                    if graph is not None:
                        record_source(graph, entry)
                    outcome["content_hash"] = entry.content_hash
            mine = {"outcomes": mine["outcomes"] + [outcome]}
        done = round_index + 1 >= len(sources)
        writes = {ns: mine}
        if done:
            writes[ns] = {**mine, "ingestion_result": {
                "batch_id": batch_id,
                "accepted": [o["url"] for o in mine["outcomes"] if o["accepted"]],
                "rejected": {o["url"]: o["reason"] for o in mine["outcomes"] if not o["accepted"]}}}
        return RoundResult(proposed_writes=writes, done=done)

    return WorkUnit(id=batch_id, priority=priority, round_handler=handler)


def seed_load(sources: list[FixtureSource], cas: ContentAddressedStore,
              graph: BeliefGraphStore | None = None) -> list[ProvenanceEntry]:
    """Section 9, step 4: one-time foundational corpus load. Deliberately
    a separate entry point from `ingest()` used by ongoing ingestion, even
    though the underlying logic is identical -- keeps the one-shot seed
    path auditable independently of steady-state ingestion volume."""
    entries = []
    for s in sources:
        try:
            entries.append(ingest(s, cas, graph))
        except IngestionRejected:
            continue  # a rejected seed source is skipped, not fatal to the batch
    return entries
