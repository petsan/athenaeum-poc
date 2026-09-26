"""
Knowledge Consolidation judgment (Section 10.2-10.5): the promotion
criteria, compaction, and de-compaction logic. Storage lives in
athenaeum_body/consolidation_store.py; this module decides WHEN and
WHETHER to promote/compact, not how it's persisted.
"""
from __future__ import annotations
from athenaeum_body.consolidation_store import ConsolidationStore
from .dispute_resolution import check_independence


def claim_key(claim: dict) -> str:
    """The canonical consolidation key for a claim: its issuing agent and
    exact statement. Claim ids differ on every deliberation, so they can't
    identify "the same claim surviving again"; agent + statement can, and
    is what lets a reopened answer (reopening.py) find its own claims'
    Tier C entries to expand, and idle-evolution record their survival."""
    return f"{claim['issuing_agent']}::{claim['statement']}"


def record_survival(store: ConsolidationStore, key: str, claim: dict, cycle_id: str | None = None) -> dict:
    """Section 10.1-10.2: every time a claim survives another round of
    cross-examination unchanged (an idle-evolution re-challenge cycle,
    idle_evolution.py, or a repeat deliberation reaching the same
    conclusion), record one more cycle of survival, accumulate any
    newly-seen independent sources, and append to the confidence history.

    cycle_id makes the record idempotent: an idle-evolution cycle that is
    killed after recording but before checkpointing re-runs its final
    round, and must not count the same cycle twice."""
    entry = store.get(key) or {
        "tier": "B", "cycles": 0, "sources": [], "confidence_history": [],
        "statement": claim["statement"], "archive_ref": None,
    }
    if cycle_id is not None:
        seen = entry.setdefault("cycle_ids", [])
        if cycle_id in seen:
            return entry
        seen.append(cycle_id)
    if entry.get("tier") == "C":
        # A compacted node's history lives in its archived trace, and must
        # keep matching it (the 9.5 audit compares them). Surviving again
        # counts separately, and the latest confidence goes in its own field
        # so `confidence` keeps matching the archive
        # (known-bugs.md #29: this path used to KeyError on confidence_history).
        entry["cycles_since_compaction"] = entry.get("cycles_since_compaction", 0) + 1
        entry["current_confidence"] = claim["confidence"]
        store.upsert(key, entry)
        return entry
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


def should_promote_to_c(entry: dict, min_cycles: int = 5, min_sources: int = 2,
                        cites: dict | None = None) -> dict:
    """Returns a full verdict, not just a bool, so a caller can see WHY
    a claim didn't qualify -- useful for the same reason materiality's
    'reasons' list is useful.

    Section 10.2 asks for M *independent* corroborating sources: sources
    that cite each other or share an upstream source count once
    (dispute_resolution.check_independence, Section 6.4.2). With no
    citation data, every distinct source is its own line of evidence."""
    reasons = []
    if entry["cycles"] < min_cycles:
        reasons.append(f"only {entry['cycles']}/{min_cycles} survival cycles")
    independence = check_independence(entry["sources"], cites or {})
    if independence["independent_count"] < min_sources:
        reasons.append(f"only {independence['independent_count']}/{min_sources} independent sources"
                       + (f" (circular citation among {independence['circular']})"
                          if independence["circular"] else ""))
    if not _confidence_trend_ok(entry["confidence_history"]):
        reasons.append("confidence trend is declining, not flat or improving")
    return {"eligible": len(reasons) == 0, "reasons": reasons}


def compact(store: ConsolidationStore, key: str) -> dict:
    """Section 10.3-10.4: archive the full trace (content-addressed,
    never deleted), replace the active entry with a compact Tier C form
    plus an archive pointer. Compacting an already-compacted node is a
    no-op that returns it."""
    entry = store.get(key)
    if entry is None:
        raise KeyError(f"no tracked entry for {key!r}")
    if entry.get("tier") == "C":
        return entry
    ref = store.archive_full_trace(entry)
    compact_node = {
        "tier": "C", "statement": entry["statement"],
        "confidence": entry["confidence_history"][-1],
        "cycles": entry["cycles"], "sources": entry["sources"],
        "archive_ref": ref,
        # kept so record_survival stays idempotent across a compaction
        "cycle_ids": list(entry.get("cycle_ids", [])),
    }
    store.upsert(key, compact_node)
    return compact_node


def decompact(store: ConsolidationStore, key: str, reason: str) -> dict:
    """Section 10.5: when a compacted claim is challenged, reasoning must not
    build on the lossy summary -- the full archived trace becomes the active
    entry again (back at Tier B), recording why and where it came from. The
    archived copy stays where it is (10.4: nothing is ever deleted).
    De-compacting an entry that isn't Tier C is a no-op."""
    entry = store.get(key)
    if entry is None or entry.get("tier") != "C":
        return entry
    full = store.read_full_trace(entry["archive_ref"])
    restored = {**full, "tier": "B",
                "decompacted_from": entry["archive_ref"], "decompaction_reason": reason,
                "cycle_ids": sorted(set(full.get("cycle_ids", [])) | set(entry.get("cycle_ids", [])))}
    store.upsert(key, restored)
    return restored


def expand(store: ConsolidationStore, key: str) -> dict:
    """Section 10.5: de-compaction on challenge -- required, not optional,
    before any further reasoning builds on a compacted (Tier C) claim."""
    entry = store.get(key)
    if entry is None:
        raise KeyError(f"no tracked entry for {key!r}")
    if entry.get("archive_ref"):
        return store.read_full_trace(entry["archive_ref"])
    return entry  # not yet compacted -- nothing to expand
