"""
The four deliberation rounds (Section 3) and the Synthesis Commit
boundary (Section 4.4): proposal-only writes until synthesis explicitly
commits them.
"""
from __future__ import annotations
from .claims import Claim
from .agents import MasterOfMathematics, MasterOfLogic, MasterOfEngineering

ALL_AGENTS = [MasterOfMathematics(), MasterOfLogic(), MasterOfEngineering()]


def framing_round(question: str, question_id: str) -> dict:
    """Section 3.1: decide which agents are routed to this question."""
    routed = [a.name for a in ALL_AGENTS if a.in_jurisdiction(question)]
    return {"question": question, "routed_agents": routed}


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


def synthesis_round(exploration_claims: list[Claim], exam_claims: list[Claim]) -> dict:
    """
    Section 4: the ONLY step allowed to move a claim's status from
    'proposed' to 'committed' (Section 4.4 -- single commit boundary).

    Standalone claims (Section 4.1): a claim with no surviving challenge
    is committed at its original confidence; a challenged one surfaces as
    labeled dissent rather than being silently accepted or dropped.

    Topic-grouped claims (Section 4.2): claims sharing a `topic` are the
    demo's stand-in for "the same underlying question." When two or more
    distinct, still-jurisdiction-valid agents reach genuinely different
    conclusions on the same topic, this is a jurisdictional conflict --
    synthesis does NOT pick a winner (that would manufacture false
    consensus, Section 4.3). It commits every surviving conclusion,
    labeled by agent, as a structured plural answer, chaired by Logic
    checking only that each side's claim survived cross-examination on
    its own merits -- never adjudicating whose domain "should" win.
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

    topic_groups, standalone = {}, []
    for c in exploration_claims:
        (topic_groups.setdefault(c.topic, []) if c.topic else standalone).append(c)

    committed, dissent, plural_answers = [], [], []

    for claim in standalone:
        if surviving_or_dissent(claim, dissent):
            claim.status = "committed"
            committed.append(claim)

    for topic, group in topic_groups.items():
        survivors = [c for c in group if surviving_or_dissent(c, dissent)]
        distinct_agents = {c.issuing_agent for c in survivors}
        distinct_statements = {c.statement for c in survivors}
        for c in survivors:
            c.status = "committed"
        committed.extend(survivors)
        if len(survivors) >= 2 and len(distinct_agents) > 1 and len(distinct_statements) > 1:
            plural_answers.append({
                "topic": topic,
                "chaired_by": "Logic",
                "note": "genuine jurisdictional conflict -- no single winner adjudicated (Section 4.2-4.3)",
                "conclusions": [
                    {"agent": c.issuing_agent, "statement": c.statement,
                     "confidence": c.confidence, "claim_id": c.claim_id}
                    for c in survivors
                ],
            })

    return {"committed": committed, "dissent": dissent, "plural_answers": plural_answers}
