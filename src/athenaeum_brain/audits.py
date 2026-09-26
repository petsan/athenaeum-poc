"""
Periodic evaluation audits (brain-design.md Sections 9.4 and 9.5).

Both are sample-based and seeded, so any audit can be reproduced exactly.
Neither replaces human judgment where the design calls for it -- 9.4 says
"manually check" -- they narrow the question: mechanical pre-checks decide
what is clearly fine, clearly broken, and what a person needs to look at.

9.4 re-evaluation audit -- does the materiality test (7.2) thrash
    (reopening when nothing changes) or stagnate (never reopening when it
    should)? Each sampled reopened version is classified from its own diff;
    separately, every answer that is material RIGHT NOW but still sits
    un-reopened is listed as a stagnation candidate.
9.5 consolidation fidelity audit -- is compaction (10.3) losing meaning?
    Each sampled Tier C node is expanded from the cold archive and checked
    against it: same statement, confidence, sources and cycle count, and
    whether the promotion criteria (10.2) actually held for the archived
    trace. An archive that fails its content-hash check is reported, not
    trusted.
"""
from __future__ import annotations
import random
from athenaeum_body.ledger import QuestionLedger
from athenaeum_body.reputability_store import ReputabilityStore
from athenaeum_body.consolidation_store import ConsolidationStore
from athenaeum_body.audit_store import AuditStore
from athenaeum_body.storage.content_addressed import IntegrityError, NotFoundError
from .consolidation import should_promote_to_c
from .reevaluation import is_material, materiality_inputs


def _sample(items: list, size: int, seed: int) -> list:
    return items if len(items) <= size else random.Random(seed).sample(items, size)


# ---------------------------------------------------------------------------
# 9.4
# ---------------------------------------------------------------------------

def classify_reopen(diff: dict) -> str:
    """'leading_changed' -- needs a human: better reasoning, or just different?
    'no_change'       -- nothing moved at all: a thrash suspect.
    'weights_only'    -- support shifted, conclusions didn't: consistent with
                         a grade-driven materiality trigger."""
    leading = diff.get("leading_conclusion", {}).get("change")
    if leading in ("changed", "appeared", "disappeared"):
        return "leading_changed"
    confidence_moved = diff.get("leading_conclusion", {}).get("confidence") not in (None, "same")
    if diff.get("added") or diff.get("removed") or diff.get("weight_changes") or confidence_moved:
        return "weights_only"
    return "no_change"


def reevaluation_audit(ledger: QuestionLedger, reputability: ReputabilityStore, *, audit_id: str,
                       sample_size: int = 20, seed: int = 0, grade_threshold: int = 1,
                       store: AuditStore | None = None) -> dict:
    questions = ledger._state()["questions"]
    reopened = [{"question_id": qid, "version": i, "diff": v["diff"]}
                for qid, q in sorted(questions.items())
                for i, v in enumerate(q["versions"]) if i >= 1 and "diff" in v]
    sampled = []
    for r in _sample(reopened, sample_size, seed):
        sampled.append({"question_id": r["question_id"], "version": r["version"],
                        "classification": classify_reopen(r["diff"]), "cause": r["diff"].get("cause", [])})

    stagnation = []
    for qid, q in sorted(questions.items()):
        if not q["versions"] or "source_grades_at_use" not in q["versions"][-1]:
            continue
        latest = q["versions"][-1]
        current, under_prior = materiality_inputs(latest, reputability)
        m = is_material(latest, current, threshold=grade_threshold, prior_standard_grades=under_prior)
        if m["material"]:
            stagnation.append({"question_id": qid, "importance": q["importance"], "reasons": m["reasons"]})

    no_change = sum(1 for s in sampled if s["classification"] == "no_change")
    report = {
        "audit_id": audit_id, "kind": "reevaluation", "seed": seed,
        "population": len(reopened), "sampled": sampled,
        "thrash_suspect_rate": (no_change / len(sampled)) if sampled else None,
        "for_human_review": [s for s in sampled if s["classification"] == "leading_changed"],
        "stagnation_candidates": stagnation,
    }
    if store is not None:
        store.record("reevaluation", report)
    return report


# ---------------------------------------------------------------------------
# 9.5
# ---------------------------------------------------------------------------

def _check_node(consolidation: ConsolidationStore, node: dict, *, cites: dict, min_cycles: int,
                min_sources: int) -> list[str]:
    try:
        full = consolidation.read_full_trace(node["archive_ref"])
    except IntegrityError:
        return ["archive_corrupt: the archived trace no longer matches its content hash"]
    except NotFoundError:
        return ["archive_missing: no archived trace at the node's pointer"]
    problems = []
    if node["statement"] != full["statement"]:
        problems.append(f"statement_mismatch: compact {node['statement']!r} vs archived {full['statement']!r}")
    if node["confidence"] != full["confidence_history"][-1]:
        problems.append(f"confidence_mismatch: compact {node['confidence']} vs archived "
                        f"{full['confidence_history'][-1]}")
    if sorted(node["sources"]) != sorted(full["sources"]):
        problems.append("sources_mismatch: the compact node cites different sources than its trace")
    if node["cycles"] != full["cycles"]:
        problems.append(f"cycles_mismatch: compact {node['cycles']} vs archived {full['cycles']}")
    verdict = should_promote_to_c(full, min_cycles=min_cycles, min_sources=min_sources, cites=cites)
    if not verdict["eligible"]:
        problems.append("promoted_without_meeting_criteria: " + "; ".join(verdict["reasons"]))
    return problems


def consolidation_audit(consolidation: ConsolidationStore, *, audit_id: str, sample_size: int = 20,
                        seed: int = 0, cites: dict | None = None, min_cycles: int = 5,
                        min_sources: int = 2, store: AuditStore | None = None) -> dict:
    tier_c = sorted(k for k, e in consolidation.entries().items() if e.get("tier") == "C")
    findings = []
    for key in _sample(tier_c, sample_size, seed):
        problems = _check_node(consolidation, consolidation.get(key), cites=cites or {},
                               min_cycles=min_cycles, min_sources=min_sources)
        findings.append({"claim": key, "ok": not problems, "problems": problems})
    report = {
        "audit_id": audit_id, "kind": "consolidation", "seed": seed,
        "population": len(tier_c), "findings": findings,
        "failed": [f for f in findings if not f["ok"]],
    }
    if store is not None:
        store.record("consolidation", report)
    return report
