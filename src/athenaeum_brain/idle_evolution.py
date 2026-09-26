"""
Idle-evolution rounds (brain-design.md Section 3.6).

Between questions, already-committed claims are re-challenged against the
CURRENT agents and CURRENT reputability grades, to catch claims that were
reasonable when made but are no longer well-supported. The same pass is
where the other periodic reviews run: knowledge consolidation (10),
Logic-chaired dispute resolution for newly challenged claims (6.4),
Domain Fidelity scoring (2.4), and a consistency review of the
reputability standard itself (6.5). Findings that touch a previously
answered question feed re-evaluation (7) via reopening.reopen_if_material.

It runs as an ordinary WorkUnit on the Body's scheduler, so it is
checkpointed and kill/resume-safe like any deliberation:

  round 0  sample   -- priority- then randomly-sampled committed claims
  round 1  re-examine -- fresh cross-examination + current evidence weight
  round 2  review   -- pure analysis: fidelity scores, disputes to hold,
                       reevaluation candidates, standard-amendment proposal
  round 3  commit   -- the ONLY round with side effects, each idempotent
                       under the cycle id, so a kill between writing and
                       checkpointing can't double-count on resume

Two deliberate restraints:
- Re-examination records NO reputability outcomes. A claim surviving
  re-examination is not new evidence about its sources; counting it would
  let the same claim corroborate its own sources every cycle until they
  reached 'foundational' on no new information.
- A standard amendment is only ever PROPOSED, to the human checkpoint
  (11.5); it is adopted by apply_amendment_if_approved once a reviewer has
  approved it, never automatically.
"""
from __future__ import annotations
import random
from dataclasses import dataclass, field
from athenaeum_body.ledger import QuestionLedger
from athenaeum_body.reputability_store import ReputabilityStore
from athenaeum_body.consolidation_store import ConsolidationStore
from athenaeum_body.domain_fidelity_store import DomainFidelityStore
from athenaeum_body.human_checkpoint_store import HumanCheckpointStore
from athenaeum_body.scheduler.work_unit import WorkUnit, RoundResult
from .claims import Claim, next_claim_id
from .rounds import cross_examination_round, reputability_factor
from .consolidation import claim_key, record_survival, should_promote_to_c, compact, decompact
from .dispute_resolution import resolve_dispute
from .domain_fidelity import compute_score, needs_review
from .fidelity_remediation import remediate

SUBMITTER = "idle-evolution"  # recorded as the proposer of standard amendments


@dataclass
class IdleContext:
    ledger: QuestionLedger
    reputability: ReputabilityStore
    consolidation: ConsolidationStore | None = None
    fidelity: DomainFidelityStore | None = None
    checkpoints: HumanCheckpointStore | None = None
    cites: dict = field(default_factory=dict)
    # Section 10.2's N and M (brain-design.md Open Question 7: configurable,
    # values unset by the design -- these are placeholders)
    consolidation_min_cycles: int = 5
    consolidation_min_sources: int = 2


# --- round 0 ---------------------------------------------------------------

def sample_claims(ledger: QuestionLedger, sample_size: int, seed: int) -> list[dict]:
    """Priority first (higher-importance questions' claims), random order
    among equally important questions (seeded, so a cycle is reproducible)."""
    questions = [q for q in ledger._state()["questions"].values() if q["versions"]]
    random.Random(seed).shuffle(questions)
    questions.sort(key=lambda q: -q["importance"])  # stable: keeps the shuffle within ties
    sample = []
    for q in questions:
        for c in q["versions"][-1].get("committed", []):
            if len(sample) >= sample_size:
                return sample
            sample.append({"question_id": q["id"], "claim": c})
    return sample


# --- round 1 ---------------------------------------------------------------

def reexamine(sample: list[dict], reputability: ReputabilityStore, cycle_id: str) -> dict:
    """Cross-examines every sampled claim afresh and re-weighs it under
    current grades. Claims get fresh ids for this pass: claims from
    different past deliberations are examined together and must not share
    ids. Status per claim:
      challenged  -- a current agent now challenges it
      unsupported -- its weakest source is now rejected (factor 0)
      weakened    -- survived, but its evidence weight fell since commit
      survived    -- survived with undiminished support"""
    lookup = lambda src: reputability.current_grade(src)["grade"]
    claims = [Claim(**{**s["claim"], "claim_id": next_claim_id()}) for s in sample]
    exam = cross_examination_round(claims, cycle_id)
    challenges = {}
    for r in exam:
        if r.relation == "challenges":
            challenges.setdefault(r.target_claim_id, []).append(r)

    findings = []
    for s, c in zip(sample, claims):
        factor_now = reputability_factor(c.supporting_provenance, lookup)
        factor_then = s["claim"].get("reputability_factor")
        against = challenges.get(c.claim_id, [])
        if against:
            status = "challenged"
        elif factor_now == 0.0:
            status = "unsupported"
        elif factor_then is not None and factor_now < factor_then:
            status = "weakened"
        else:
            status = "survived"
        findings.append({
            "question_id": s["question_id"], "claim_key": claim_key(s["claim"]),
            "claim": c.to_dict(), "status": status,
            "factor_then": factor_then, "factor_now": factor_now,
            "challenges": [r.to_dict() for r in against],
        })
    return {"findings": findings, "exam": [r.to_dict() for r in exam]}


# --- round 2 ---------------------------------------------------------------

def propose_standard_amendment(findings: list[dict], reputability: ReputabilityStore,
                               min_evidence: int = 2) -> dict | None:
    """Section 6.5's consistency review: if claims resting ENTIRELY on
    sources the current standard grades 'foundational' are nonetheless
    challenged on re-examination, the bar for 'foundational' looks too
    low. With at least `min_evidence` such claims, propose raising it by
    one corroboration. Returns the proposal, or None."""
    evidence = []
    for f in findings:
        srcs = f["claim"]["supporting_provenance"]
        if f["status"] == "challenged" and srcs and all(
                reputability.current_grade(s)["grade"] == "foundational" for s in srcs):
            evidence.append(f["claim_key"])
    if len(evidence) < min_evidence:
        return None
    current = reputability.current_standard()
    params = {**current["params"],
              "foundational_min_corroborations": current["params"]["foundational_min_corroborations"] + 1}
    return {
        "from_version": current["version"],
        "params": params,
        "rationale": (f"{len(evidence)} claim(s) resting only on 'foundational' sources were challenged "
                      f"on idle re-examination ({'; '.join(evidence)}), suggesting the foundational bar "
                      f"of {current['params']['foundational_min_corroborations']} corroborations is too low"),
        "evidence": evidence,
    }


def review(findings: list[dict], exam: list[dict], reputability: ReputabilityStore) -> dict:
    """Pure analysis of round 1's findings -- nothing is written here."""
    claims = [f["claim"] for f in findings]
    agents = sorted({c["issuing_agent"] for c in claims})
    fidelity = {a: compute_score(a, claims, exam) for a in agents}
    candidates = {}
    for f in findings:
        if f["status"] in ("challenged", "unsupported"):
            reason = (f"idle re-examination: '{f['claim_key']}' is now {f['status']}"
                      + (f" ({f['challenges'][0]['statement']})" if f["challenges"] else ""))
            candidates.setdefault(f["question_id"], []).append(reason)
    return {
        "fidelity": fidelity,
        "disputes": [f["claim_key"] for f in findings if f["status"] == "challenged"],
        "reevaluation_candidates": candidates,
        "amendment_proposal": propose_standard_amendment(findings, reputability),
    }


# --- round 3 ---------------------------------------------------------------

def commit(ctx: IdleContext, cycle_id: str, findings: list[dict], plan: dict) -> dict:
    """Applies the cycle's effects, every one idempotent under cycle_id."""
    survived, compacted, decompacted = [], [], []
    if ctx.consolidation is not None:
        for f in findings:
            if f["status"] in ("survived", "weakened"):
                # The confidence history tracks CURRENT evidence weight, so a
                # weakened claim's declining trend blocks Tier C promotion (10.2).
                weighed = {**f["claim"], "confidence": f["claim"]["confidence"] * f["factor_now"]}
                entry = record_survival(ctx.consolidation, f["claim_key"], weighed, cycle_id=cycle_id)
                survived.append(f["claim_key"])
                # 10.3: compaction is performed here, by idle evolution, the
                # moment a claim meets 10.2's promotion criteria.
                if entry.get("tier") != "C" and should_promote_to_c(
                        entry, min_cycles=ctx.consolidation_min_cycles,
                        min_sources=ctx.consolidation_min_sources, cites=ctx.cites)["eligible"]:
                    compact(ctx.consolidation, f["claim_key"])
                    compacted.append(f["claim_key"])
            elif f["status"] in ("challenged", "unsupported"):
                # 10.5: a compacted claim under challenge is expanded back to its
                # full trace before anything -- including the dispute below --
                # reasons about it.
                entry = ctx.consolidation.get(f["claim_key"])
                if entry is not None and entry.get("tier") == "C":
                    decompact(ctx.consolidation, f["claim_key"], reason=f"{cycle_id}: now {f['status']}")
                    decompacted.append(f["claim_key"])

    rulings = {}
    by_key = {f["claim_key"]: f for f in findings}
    for key in plan["disputes"]:
        f = by_key[key]
        sides = {"claim": [Claim(**f["claim"])], "challenge": [Claim(**c) for c in f["challenges"]]}
        record = resolve_dispute(key, sides, reputability=ctx.reputability, cites=ctx.cites,
                                 question_id=cycle_id, dispute_id=f"{cycle_id}:{key}")
        rulings[key] = record["ruling"]

    flagged, remediation = {}, {}
    if ctx.fidelity is not None:
        for agent, score in plan["fidelity"].items():
            if not any(h.get("cycle_id") == cycle_id for h in ctx.fidelity.history_for(agent)):
                ctx.fidelity.record(agent, {**score, "cycle_id": cycle_id})
            verdict = needs_review(ctx.fidelity, agent)
            if verdict["needs_review"]:
                flagged[agent] = verdict["reason"]
            # Section 2.4.3: the flag starts (or advances) a remediation path,
            # re-examining this cycle's sample of the agent's claims for style.
            record = remediate(ctx.fidelity, agent, cycle_id=cycle_id, checkpoints=ctx.checkpoints,
                               recent_claims=[f["claim"] for f in findings if f["claim"]["issuing_agent"] == agent])
            remediation[agent] = record["stage"]

    proposal = plan["amendment_proposal"]
    if proposal is not None and ctx.checkpoints is not None:
        key = amendment_checkpoint_key(cycle_id)
        if ctx.checkpoints.get(key) is None:
            ctx.checkpoints.set_pending(key, reason=proposal["rationale"],
                                        triggering_claim_id=proposal["evidence"][0], submitter_id=SUBMITTER)

    return {
        "cycle_id": cycle_id,
        "status_counts": {s: sum(1 for f in findings if f["status"] == s)
                          for s in ("survived", "weakened", "unsupported", "challenged")},
        "recorded_survival": survived,
        "compacted": compacted,
        "decompacted": decompacted,
        "dispute_rulings": rulings,
        "fidelity_flags": flagged,
        "remediation": remediation,
        "reevaluation_candidates": plan["reevaluation_candidates"],
        "amendment_proposal": proposal,
    }


def amendment_checkpoint_key(cycle_id: str) -> str:
    return f"standard-amendment:{cycle_id}"


# --- the work unit --------------------------------------------------------

def make_idle_evolution_unit(ctx: IdleContext, cycle_id: str, *, sample_size: int = 20,
                             seed: int = 0, priority: int = -1) -> WorkUnit:
    """Idle work runs at lower priority than questions by default, so the
    time-sliced scheduler serves real questions first. Like a deliberation,
    its working state lives under its own namespace in the scheduler's
    shared state (known-bugs.md #26), mirrored at the top level for
    single-unit callers."""
    ns = f"idle:{cycle_id}"

    def writes(state: dict, new: dict) -> dict:
        return {ns: {**state.get(ns, {}), **new}, **new}

    def handler(state: dict, round_index: int) -> RoundResult:
        mine = state[ns] if ns in state else state
        if round_index == 0:
            return RoundResult(proposed_writes=writes(state, {"sample": sample_claims(ctx.ledger, sample_size, seed)}))
        if round_index == 1:
            return RoundResult(proposed_writes=writes(state, reexamine(mine["sample"], ctx.reputability, cycle_id)))
        if round_index == 2:
            return RoundResult(proposed_writes=writes(
                state, {"plan": review(mine["findings"], mine["exam"], ctx.reputability)}))
        if round_index == 3:
            result = commit(ctx, cycle_id, mine["findings"], mine["plan"])
            return RoundResult(proposed_writes=writes(state, {"idle_result": result}), done=True)
        raise ValueError(f"no round {round_index} in an idle-evolution cycle")

    return WorkUnit(id=cycle_id, priority=priority, round_handler=handler)


# --- follow-through (outside the cycle) -------------------------------------

def apply_amendment_if_approved(ctx: IdleContext, cycle_id: str, proposal: dict) -> dict:
    """Adopts a proposed amendment only once its human checkpoint has been
    approved (status 'current', via human_input.clear_checkpoint's
    Reviewer-gated path). Safe to call repeatedly."""
    cp = ctx.checkpoints.get(amendment_checkpoint_key(cycle_id))
    if cp is None or cp["status"] != "current":
        return {"adopted": False, "reason": f"checkpoint status is {cp and cp['status']!r}, not approved"}
    marker = f"[approved amendment {cycle_id}]"
    if any(marker in s["rationale"] for s in ctx.reputability.standards()):
        return {"adopted": False, "reason": "already adopted"}
    result = ctx.reputability.adopt_standard(
        proposal["params"], rationale=f"{proposal['rationale']} {marker} reviewer={cp['reviewer_id']}")
    return {"adopted": True, **result}


def feed_reevaluation(ctx: IdleContext, idle_result: dict, *, unit_log_for, importance_threshold: float = 0.3,
                      belief_graph=None) -> dict:
    """Hands each question the cycle implicated to reopen_if_material, with
    the cycle's findings as additional material reasons (7.2). The usual
    importance gate still applies. unit_log_for(question_id) supplies a
    fresh checkpoint log for each reopen; with a Belief Graph, reopened
    versions are recorded there too."""
    from .reopening import reopen_if_material
    outcomes = {}
    for qid, reasons in idle_result["reevaluation_candidates"].items():
        outcomes[qid] = reopen_if_material(
            ctx.ledger, qid, reputability=ctx.reputability, unit_log=unit_log_for(qid),
            importance_threshold=importance_threshold, consolidation=ctx.consolidation,
            additional_reasons=reasons, belief_graph=belief_graph)
    return outcomes
