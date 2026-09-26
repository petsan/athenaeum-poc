"""
The four deliberation rounds (Section 3) and the Synthesis Commit
boundary (Section 4.4): proposal-only writes until synthesis explicitly
commits them.
"""
from __future__ import annotations
from .claims import Claim
from .agents import all_agents
from .output_types import classify_output_type
from .model_fitness import apply_fitness_to_confidence

# Built from agents.py's @master_agent registry, not a hardcoded class
# list -- adding a new domain (agents.py) requires no change here. See
# agents.py's module docstring for the full explanation.
ALL_AGENTS = all_agents()


def framing_round(question: str, question_id: str) -> dict:
    """Section 3.1: decide which agents are routed to this question, and
    (Section 5.4) which of research|forecast|recommendation it's asking
    for -- written into the frame itself, same as routing, so later
    re-evaluation can detect if the *classification* becomes outdated,
    not just the answer built on it."""
    routed = [a.name for a in ALL_AGENTS if a.in_jurisdiction(question)]
    output_types = classify_output_type(question)
    return {"question": question, "routed_agents": routed, "output_types": output_types}


def exploration_round(frame: dict, question_id: str) -> list[Claim]:
    """Section 3.2: each routed agent proposes candidate claims independently."""
    claims = []
    for agent in ALL_AGENTS:
        if agent.name in frame["routed_agents"]:
            claims.extend(agent.explore(frame["question"], question_id))
    return claims


def cross_examination_round(claims: list[Claim], question_id: str) -> list[Claim]:
    """Section 3.3: every other agent may corroborate/challenge/abstain."""
    responses = []
    for claim in claims:
        for agent in ALL_AGENTS:
            resp = agent.cross_examine(claim, question_id)
            if resp is not None:
                responses.append(resp)
    return responses


def _normalize_subject(subject: str):
    """Numeric-equality normalization so agents that format the same
    subject differently ('2.5' vs '2.50') still correctly conflict-group,
    without needing to agree on a shared string convention in advance --
    a modest, real improvement over exact-string topic matching, though
    still far short of general semantic 'same underlying question'
    detection, which needs the model-serving layer (Section 4.5)."""
    try:
        from decimal import Decimal
        return ("numeric", Decimal(subject).normalize())
    except Exception:
        return ("text", subject.strip().lower())


# Section 4.1: how much of a claim's own confidence survives, given the
# reputability grade of what it rests on. Explicitly a placeholder policy,
# same status as reputability_store._grade_from_tally -- the ordering is
# the design's (foundational > provisional > contested > rejected), the
# exact numbers are not.
GRADE_WEIGHT = {
    "foundational": 1.0,
    "provisionally_accepted": 0.8,
    "contested": 0.4,
    "rejected": 0.0,
}


def reputability_factor(provenance: list[str], grade_lookup) -> float:
    """Weakest link, not an average: every provenance list the agents emit
    today is conjunctive (a causal-precedence claim needs BOTH dates right),
    so one rejected source should sink the claim rather than be diluted by
    a good one. A claim citing nothing has nothing to trace its confidence
    to (Section 5.1) and gets 0.0."""
    if not provenance:
        return 0.0
    return min(GRADE_WEIGHT[grade_lookup(src)] for src in provenance)


def synthesis_round(exploration_claims: list[Claim], exam_claims: list[Claim],
                    grade_lookup=None, fitness_lookup=None) -> dict:
    """
    Section 4: the ONLY step allowed to move a claim's status from
    'proposed' to 'committed' (Section 4.4 -- single commit boundary).

    Standalone claims (Section 4.1): a claim with no surviving challenge
    is committed at its original confidence; a challenged one surfaces as
    labeled dissent rather than being silently accepted or dropped.

    Subject-grouped claims (Section 4.2): each agent independently sets
    `subject` on a claim to whatever specific entity/value it's reasoning
    about -- agents do NOT coordinate on a shared label. Grouping here
    happens via `_normalize_subject`, so two agents both reasoning about
    "2.5" conflict-group correctly even without prior coordination. When
    two or more distinct, still-jurisdiction-valid agents reach genuinely
    different conclusions about the same normalized subject, synthesis does
    NOT pick a winner (that would manufacture false consensus, Section 4.3)
    -- it commits every surviving conclusion, labeled by agent, as a
    structured plural answer, chaired by Logic checking only that each
    side's claim survived cross-examination on its own merits.

    Evidence weighting (Section 4.1): when `grade_lookup` (source_id ->
    grade name) is given, every committed claim gets `reputability_factor`
    and `weighted_confidence` set -- the caller is responsible for passing
    grades as of time-of-use (loop.py does, before recording this
    deliberation's own outcomes). Weighting never decides what is
    committed or dissented; it only orders what was committed, which is
    what build_research_answer's leading conclusion is chosen from.
    `fitness_lookup(agent, serving_model) -> factor` (Section 6.7,
    model_fitness.fitness_factor) multiplies in a second, independent
    factor for model-backed claims, on the same time-of-use terms.
    Without a lookup, claims are left unweighted (None), which is exactly
    what evaluation.py's no-reputability ablation compares against.
    """
    by_target = {}
    for r in exam_claims:
        by_target.setdefault(r.target_claim_id, []).append(r)

    def surviving_or_dissent(claim, dissent_list):
        responses = by_target.get(claim.claim_id, [])
        challenged = [r for r in responses if r.relation == "challenges"]
        if challenged:
            dissent_list.append({"claim": claim.to_dict(), "challenges": [c.to_dict() for c in challenged]})
            return False
        return True

    subject_groups, standalone = {}, []
    for c in exploration_claims:
        (subject_groups.setdefault(_normalize_subject(c.subject), []) if c.subject else standalone).append(c)

    committed, dissent, plural_answers = [], [], []

    for claim in standalone:
        if surviving_or_dissent(claim, dissent):
            claim.status = "committed"
            committed.append(claim)

    for norm_subject, group in subject_groups.items():
        survivors = [c for c in group if surviving_or_dissent(c, dissent)]
        distinct_agents = {c.issuing_agent for c in survivors}
        distinct_statements = {c.statement for c in survivors}
        for c in survivors:
            c.status = "committed"
        committed.extend(survivors)
        if len(survivors) >= 2 and len(distinct_agents) > 1 and len(distinct_statements) > 1:
            plural_answers.append({
                "subject": group[0].subject,  # original, un-normalized, for display
                "chaired_by": "Logic",
                "note": "genuine jurisdictional conflict -- no single winner adjudicated (Section 4.2-4.3)",
                "conclusions": [
                    {"agent": c.issuing_agent, "statement": c.statement,
                     "confidence": c.confidence, "claim_id": c.claim_id}
                    for c in survivors
                ],
            })

    if grade_lookup is not None or fitness_lookup is not None:
        for c in committed:
            weight = c.confidence
            if grade_lookup is not None:
                c.reputability_factor = reputability_factor(c.supporting_provenance, grade_lookup)
                weight *= c.reputability_factor
            if fitness_lookup is not None:
                c.fitness_factor = fitness_lookup(c.issuing_agent, c.serving_model)
                weight = apply_fitness_to_confidence(weight, c.fitness_factor)
            c.weighted_confidence = weight

    return {"committed": committed, "dissent": dissent, "plural_answers": plural_answers}
