"""
Knowledge Consolidation judgment (Section 10.2-10.5): the promotion
criteria, compaction, and de-compaction logic. Storage lives in
athenaeum_body/consolidation_store.py; this module decides WHEN and
WHETHER to promote/compact, not how it's persisted.
"""
from __future__ import annotations
from athenaeum_body.consolidation_store import ConsolidationStore


def record_survival(store: ConsolidationStore, key: str, claim: dict) -> dict:
    """Section 10.1-10.2: every time a claim survives another round of
    cross-examination unchanged (an idle-evolution re-challenge cycle, or
    -- in this POC, since there's no idle-evolution loop yet -- a repeat
    deliberation reaching the same conclusion), record one more cycle of
    survival, accumulate any newly-seen independent sources, and append
    to the confidence history."""
    entry = store.get(key) or {
        "tier": "B", "cycles": 0, "sources": [], "confidence_history": [],
        "statement": claim["statement"], "archive_ref": None,
    }
    entry["cycles"] += 1
    for src in claim.get("supporting_provenance", []):
        if src not in entry["sources"]:
            entry["sources"].append(src)
    entry["confidence_history"].append(claim["confidence"])
    entry["statement"] = claim["statement"]  # keep latest wording
    store.upsert(key, entry)
    return entry


def _confidence_trend_ok(history: list[float]) -> bool:
    """Section 10.2: 'a calibration/confidence trend that is flat or
    improving, not declining' -- non-decreasing across the whole history.
    A single declining step disqualifies promotion even if survival count
    and source count both already meet threshold, exactly as specified:
    'specifically excluded from promotion even if it hasn't yet been
    overturned, since that trend is itself informative.'"""
    return all(history[i] <= history[i + 1] for i in range(len(history) - 1))


def should_promote_to_c(entry: dict, min_cycles: int = 5, min_sources: int = 2) -> dict:
    """Returns a full verdict, not just a bool, so a caller can see WHY
    a claim didn't qualify -- useful for the same reason materiality's
    'reasons' list is useful."""
    reasons = []
    if entry["cycles"] < min_cycles:
        reasons.append(f"only {entry['cycles']}/{min_cycles} survival cycles")
    if len(entry["sources"]) < min_sources:
        reasons.append(f"only {len(entry['sources'])}/{min_sources} independent sources")
    if not _confidence_trend_ok(entry["confidence_history"]):
        reasons.append("confidence trend is declining, not flat or improving")
    return {"eligible": len(reasons) == 0, "reasons": reasons}


def compact(store: ConsolidationStore, key: str) -> dict:
    """Section 10.3-10.4: archive the full trace (content-addressed,
    never deleted), replace the active entry with a compact Tier C form
    plus an archive pointer."""
    entry = store.get(key)
    if entry is None:
        raise KeyError(f"no tracked entry for {key!r}")
    ref = store.archive_full_trace(entry)
    compact_node = {
        "tier": "C", "statement": entry["statement"],
        "confidence": entry["confidence_history"][-1],
        "cycles": entry["cycles"], "sources": entry["sources"],
        "archive_ref": ref,
    }
    store.upsert(key, compact_node)
    return compact_node


def expand(store: ConsolidationStore, key: str) -> dict:
    """Section 10.5: de-compaction on challenge -- required, not optional,
    before any further reasoning builds on a compacted (Tier C) claim."""
    entry = store.get(key)
    if entry is None:
        raise KeyError(f"no tracked entry for {key!r}")
    if entry.get("archive_ref"):
        return store.read_full_trace(entry["archive_ref"])
    return entry  # not yet compacted -- nothing to expand
