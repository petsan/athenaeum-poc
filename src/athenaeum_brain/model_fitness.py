"""
Model Fitness Tracking judgment (Section 6.7): decides the starting
confidence weight for a claim based on its (issuing_agent, serving_model)
pairing's accumulated track record. Storage lives in
athenaeum_body/model_fitness_store.py; this module only computes the
weight and enforces non-retroactive attachment, matching the existing
Body-storage/Brain-judgment split.
"""
from __future__ import annotations
from athenaeum_body.model_fitness_store import ModelFitnessStore

# Open Question 10 (brain-design.md Section 14): resolved here via
# Laplace (add-one) smoothing over the corroborated/challenged tally,
# rather than a separately special-cased constant. A brand new (agent,
# model) pairing with zero evidence (0, 0) naturally lands at exactly 0.5
# -- neither the "too generous" nor "too conservative" failure mode the
# open question names -- and the weight moves smoothly toward 1.0 or 0.0
# as real evidence accumulates, without overreacting to a single early
# outcome the way a raw ratio would (1 corroboration / 0 challenges would
# otherwise jump straight to 1.0).


def fitness_weight(corroborated: int, challenged: int) -> float:
    return (corroborated + 1) / (corroborated + challenged + 2)


def current_fitness_weight(store: ModelFitnessStore, agent_name: str, model_id: str) -> float:
    tally = store.tally(agent_name, model_id)
    return fitness_weight(tally["corroborated"], tally["challenged"])


def snapshot_and_record(store: ModelFitnessStore, agent_name: str, model_id: str, survived: bool) -> float:
    """Section 6.3's non-retroactive-attachment discipline, extended to
    Model Fitness: snapshot the weight BEFORE recording this
    deliberation's own outcome, so a claim's attached starting weight
    never reflects evidence from its own outcome -- only recorded outcomes
    strictly prior to it. Returns the snapshot (what should be attached to
    the claim/answer), exactly mirroring loop.py's
    _attach_grades_and_record_outcomes for source reputability."""
    weight_at_use = current_fitness_weight(store, agent_name, model_id)
    store.record_outcome(agent_name, model_id, "corroborated" if survived else "challenged")
    return weight_at_use


def apply_fitness_to_confidence(claim_confidence: float, fitness_weight_value: float) -> float:
    """Section 6.7: fitness informs a claim's STARTING confidence pending
    its own cross-examination -- it never overrides 6.6's hard floor, and
    it never makes a claim automatically wrong, only adjusts where it
    starts. A low-fitness pairing's claim still gets evaluated on its
    merits; this just scales the prior."""
    return claim_confidence * fitness_weight_value
