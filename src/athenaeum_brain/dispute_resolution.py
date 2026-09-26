"""
Dispute resolution procedure (brain-design.md Section 6.4), chaired by
Logic. Four steps, each one a real, checkable computation:

1. Restate the disputed claims and the sources on each side.
2. Compare track records and INDEPENDENCE of corroboration. Two sources
   are one line of evidence, not two, if either reaches the other through
   citations, or both derive from a common upstream source. A citation
   cycle (A cites B cites A) is circular corroboration and is named as
   such (Section 8's "circular corroboration" row).
3. Category-error check -- routed to Philosophy and Theology via their own
   cross_examine, never decided by Logic itself (6.4.3, mirroring 4.3's
   humility principle: Logic doesn't decide what counts as a category
   error in a domain it doesn't own).
4. Issue a ruling with a written rationale, logged permanently via
   ReputabilityStore.log_dispute and marked reversible on new evidence.
   The ruling never edits a grade: no single Master Agent has unilateral
   blacklist/whitelist authority. Grades still move only through
   accumulated outcomes (6.2).

Citation relationships are caller/curator-supplied, like license: a
`cites` mapping of source_id -> source ids it cites or derives from,
built from ingested ProvenanceEntry metadata by `citation_map`.
"""
from __future__ import annotations
from athenaeum_body.reputability_store import ReputabilityStore
from .claims import Claim
from .agents import all_agents

# Section 6.4.3's routing: faith-vs-empirical to Theology/Philosophy,
# research-vs-forecast-vs-recommendation to Philosophy alone.
CATEGORY_ERROR_REVIEWERS = ("Philosophy", "Theology")


def citation_map(entries) -> dict[str, list[str]]:
    """Build the `cites` mapping from ingested ProvenanceEntry objects."""
    return {e.id: list(e.metadata.get("cites", [])) for e in entries}


def _upstream(source: str, cites: dict) -> set[str]:
    """Every source reachable by following citations from `source`, not
    including itself unless a cycle leads back to it. Iterative, so a
    cycle can't recurse forever."""
    seen, stack = set(), list(cites.get(source, []))
    while stack:
        s = stack.pop()
        if s not in seen:
            seen.add(s)
            stack.extend(cites.get(s, []))
    return seen


def check_independence(sources: list[str], cites: dict) -> dict:
    """Groups `sources` into independent lines of evidence. Returns
    {'independent_count', 'groups', 'circular'} -- 'circular' lists every
    given source that sits on a citation cycle."""
    sources = list(dict.fromkeys(sources))  # dedupe, keep order
    lineage = {s: _upstream(s, cites) | {s} for s in sources}

    parent = {s: s for s in sources}

    def find(s):
        while parent[s] != s:
            parent[s] = parent[parent[s]]
            s = parent[s]
        return s

    for i, a in enumerate(sources):
        for b in sources[i + 1:]:
            if lineage[a] & lineage[b]:
                parent[find(a)] = find(b)

    groups: dict[str, list[str]] = {}
    for s in sources:
        groups.setdefault(find(s), []).append(s)
    circular = [s for s in sources if s in _upstream(s, cites)]
    return {"independent_count": len(groups), "groups": list(groups.values()), "circular": circular}


def _category_errors(claims: list[Claim], question_id: str) -> list[dict]:
    reviewers = [a for a in all_agents() if a.name in CATEGORY_ERROR_REVIEWERS]
    findings = []
    for claim in claims:
        for agent in reviewers:
            resp = agent.cross_examine(claim, question_id)
            if resp is not None and resp.relation == "challenges":
                findings.append({"claim_id": claim.claim_id, "reviewer": agent.name,
                                 "finding": resp.statement})
    return findings


def resolve_dispute(subject_id: str, sides: dict[str, list[Claim]], *,
                    reputability: ReputabilityStore, cites: dict | None = None,
                    question_id: str = "dispute") -> dict:
    """Section 6.4. `sides` maps a side label to the claims on that side.
    A side's strength is the number of independent lines of evidence
    behind its category-error-free claims, not counting a line whose
    sources are all currently graded 'rejected'. The ruling favours a side
    only when it is strictly stronger; otherwise it records the dispute as
    unresolved rather than manufacturing a winner (Section 4.3)."""
    cites = cites or {}
    record = {"subject_id": subject_id, "sides": {}}

    for label, claims in sides.items():
        errors = _category_errors(claims, question_id)
        excluded = {e["claim_id"] for e in errors}
        weighed = [c for c in claims if c.claim_id not in excluded]
        sources = [s for c in weighed for s in c.supporting_provenance]
        independence = check_independence(sources, cites)
        grades = {s: reputability.current_grade(s)["grade"] for s in sources}
        live_groups = [g for g in independence["groups"]
                       if not all(grades[s] == "rejected" for s in g)]
        record["sides"][label] = {
            "claims": [{"claim_id": c.claim_id, "issuing_agent": c.issuing_agent,
                        "statement": c.statement, "sources": list(c.supporting_provenance)}
                       for c in claims],                                  # step 1
            "grades": grades,                                             # step 2
            "independence": independence,
            "strength": len(live_groups),
            "category_errors": errors,                                    # step 3
        }

    strengths = {label: s["strength"] for label, s in record["sides"].items()}
    best = max(strengths.values(), default=0)
    leaders = [label for label, v in strengths.items() if v == best]
    if best > 0 and len(leaders) == 1:
        ruling = f"favours {leaders[0]}"
    else:
        ruling = "unresolved -- no side has strictly more independent, non-rejected corroboration"

    rationale = []
    for label, s in record["sides"].items():
        line = (f"{label}: {s['strength']} independent line(s) of evidence "
                f"from {sum(len(g) for g in s['independence']['groups'])} cited source(s)")
        if s["independence"]["circular"]:
            line += f"; circular citation among {s['independence']['circular']}"
        if s["category_errors"]:
            line += f"; {len(s['category_errors'])} claim(s) excluded for category error"
        rationale.append(line)

    record.update({"ruling": ruling, "rationale": "; ".join(rationale),
                   "chaired_by": "Logic", "reversible_on_new_evidence": True})
    claim_ids = [c["claim_id"] for s in record["sides"].values() for c in s["claims"]]
    reputability.log_dispute(subject_id, claim_ids, record["rationale"], ruling)  # step 4
    return record
