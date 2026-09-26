"""
Domain Fidelity Monitoring judgment (Section 2.4): two independent drift
signals -- jurisdictional overreach rate and reasoning-fingerprint
deviation -- combined into a single tracked score. Tracked separately
from calibration (Section 2.4.4): an agent can be accurate while still
drifting in STYLE, which is exactly what this catches.
"""
from __future__ import annotations
from athenaeum_body.domain_fidelity_store import DomainFidelityStore
from .claims import is_vacuous_defeat
from .model_backed_reasoning import GENERIC_DEFEAT_CONDITION


def _explicit_defeat_condition(c: dict) -> bool:
    """Physics (2.4.1): 'the presence rate of an explicit defeat condition'.
    Explicit means it names something observable -- not vacuous, and not the
    boilerplate every raw model completion carries."""
    defeat = c.get("defeat_condition")
    return not is_vacuous_defeat(defeat) and defeat != GENERIC_DEFEAT_CONDITION


# Section 2.4.1: per-agent style markers -- what "reasoning like this
# domain" mechanically looks like for each agent already implemented. Each
# is chosen to separate an agent's own method from a general-purpose model
# answering in its place, since that is what drift looks like here.
FINGERPRINT_CHECKS = {
    "Mathematics": lambda c: any(p.startswith("computed:") for p in c.get("supporting_provenance", [])),
    "Engineering": lambda c: c.get("claim_type") == "executable",
    "Logic": lambda c: c.get("claim_type") == "procedural",  # Logic must NEVER assert first-order claims
    "WorldNews": lambda c: any(p.startswith("dated_event:") for p in c.get("supporting_provenance", [])),
    # Added 2026-09-26 (Phase J) from 2.4.1's own list:
    "Physics": _explicit_defeat_condition,
    # "assumption-surfacing": the claim names the reasoning principle or
    # premise it rests on (e.g. reasoning:is-ought_gap), not a bare verdict.
    "Philosophy": lambda c: any(p.startswith("reasoning:") for p in c.get("supporting_provenance", [])),
    # "the rate at which claim_type: traditional is correctly attached".
    "Theology": lambda c: c.get("claim_type") == "traditional",
}
# Not every registered agent needs an entry here -- fingerprint_deviation()
# below returns 0.0 (neutral, not broken) for one that's missing, so a
# newly added domain works correctly before anyone gets around to giving
# it a style marker. See agents.py's module docstring.


def jurisdiction_overreach_rate(agent_name: str, exploration_claims: list[dict], exam_claims: list[dict]) -> float:
    """Section 2.4.1 signal 1: fraction of this agent's claims that were
    challenged specifically for asserting outside its declared jurisdiction
    (the exact pattern MasterOfLogic.cross_examine already produces)."""
    agent_claims = [c for c in exploration_claims if c["issuing_agent"] == agent_name]
    if not agent_claims:
        return 0.0
    overreach_targets = {
        r["target_claim_id"] for r in exam_claims
        if r["relation"] == "challenges" and "declared jurisdiction" in r["statement"]
    }
    overreached = sum(1 for c in agent_claims if c["claim_id"] in overreach_targets)
    return overreached / len(agent_claims)


def fingerprint_deviation(agent_name: str, claims: list[dict]) -> float:
    """Section 2.4.1 signal 2: fraction of this agent's claims that DON'T
    match its expected reasoning-style marker. 0.0 = perfectly on-style."""
    check = FINGERPRINT_CHECKS.get(agent_name)
    agent_claims = [c for c in claims if c["issuing_agent"] == agent_name]
    if check is None or not agent_claims:
        return 0.0
    on_style = sum(1 for c in agent_claims if check(c))
    return 1 - (on_style / len(agent_claims))


def compute_score(agent_name: str, exploration_claims: list[dict], exam_claims: list[dict]) -> dict:
    """Section 2.4.2: combine the two signals into one tracked score.
    The exact combination formula is a placeholder (same spirit as
    reputability_store's grading policy) -- 1.0 = perfect fidelity."""
    overreach = jurisdiction_overreach_rate(agent_name, exploration_claims, exam_claims)
    deviation = fingerprint_deviation(agent_name, exploration_claims)
    score = 1 - ((overreach + deviation) / 2)
    return {
        "agent": agent_name,
        "jurisdiction_overreach_rate": overreach,
        "fingerprint_deviation": deviation,
        "domain_fidelity_score": score,
    }


def needs_review(store: DomainFidelityStore, agent_name: str, drop_threshold: float = 0.15,
                  baseline_window: int = 3) -> dict:
    """Section 2.4.3: a statistically significant DROP triggers a flagged
    review, not an automatic behavioral change. This POC's 'significant'
    is a simple threshold against a rolling baseline -- explicitly a
    placeholder, same as every other threshold-based policy in this repo."""
    history = store.history_for(agent_name)
    if len(history) < baseline_window + 1:
        return {"needs_review": False, "reason": "not enough history yet"}
    baseline = sum(h["domain_fidelity_score"] for h in history[:baseline_window]) / baseline_window
    latest = history[-1]["domain_fidelity_score"]
    drop = baseline - latest
    if drop >= drop_threshold:
        return {"needs_review": True, "reason": f"score dropped {drop:.2f} from baseline {baseline:.2f} to {latest:.2f}"}
    return {"needs_review": False, "reason": f"drop of {drop:.2f} below threshold {drop_threshold}"}
