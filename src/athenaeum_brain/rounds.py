"""
The four deliberation rounds (Section 3) and the Synthesis Commit
boundary (Section 4.4): proposal-only writes until synthesis explicitly
commits them.
"""
from __future__ import annotations
from .claims import Claim
from .agents import MasterOfMathematics, MasterOfLogic

ALL_AGENTS = [MasterOfMathematics(), MasterOfLogic()]


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

    Ordinary case (4.1): a claim with no surviving challenge is committed
    at its original confidence.
    Jurisdictional-conflict case (4.2): a claim successfully challenged on
    jurisdiction grounds is NOT committed as fact -- it's surfaced as a
    labeled dissent rather than silently dropped or silently accepted
    (never manufacture false consensus, Section 4.3).
    """
    by_target = {}
    for r in exam_claims:
        by_target.setdefault(r.target_claim_id, []).append(r)

    committed, dissent = [], []
    for claim in exploration_claims:
        responses = by_target.get(claim.claim_id, [])
        challenged = [r for r in responses if r.relation == "challenges"]
        if challenged:
            dissent.append({"claim": claim.to_dict(), "challenges": [c.to_dict() for c in challenged]})
        else:
            claim.status = "committed"
            committed.append(claim)
    return {"committed": committed, "dissent": dissent}
