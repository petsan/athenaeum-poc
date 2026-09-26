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
    _attach_grades_and_record_outcomes for source reputability.

    Only correct for ONE claim per (agent, model) per deliberation: called
    once per claim, the second claim's snapshot would already include the
    first claim's outcome from the same deliberation. loop.py therefore
    doesn't use it -- synthesis snapshots every factor first and
    _attach_fitness_and_record_outcomes records all outcomes afterwards."""
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


# ---------------------------------------------------------------------------
# Section 6.7 model admission gate, and fitness as a synthesis-time factor
# ---------------------------------------------------------------------------

ESTABLISHED_AFTER = 10  # outcomes across all agents before a model stops being "provisional"
                        # -- a placeholder threshold, like every other in this repo


def is_model_backed(serving_model: str | None) -> bool:
    """Deterministic claims carry serving_model None or 'deterministic:...'
    (Engineering's sandbox runs); only real models are subject to fitness."""
    return bool(serving_model) and not serving_model.startswith("deterministic:")


def admit_model(store: ModelFitnessStore, model_id: str, *, rationale: str, admitted_by: str) -> dict:
    """Section 6.7: admission is a lightweight gate, requiring a stated
    rationale from whoever evaluated the model (the human workbench step of
    body-design.md 4.5). An admitted model starts at the cold-start fitness
    weight (0.5, Open Question 10) for every agent -- standing is earned
    only through accumulated outcomes, never granted at admission."""
    if not rationale or not rationale.strip():
        raise ValueError("model admission requires a rationale (Section 6.7)")
    return store.admit(model_id, rationale=rationale, admitted_by=admitted_by)


def model_standing(store: ModelFitnessStore, model_id: str, established_after: int = ESTABLISHED_AFTER) -> str:
    """'not_admitted', 'provisional' (admitted, too little evidence yet),
    or 'established'. Informational; the weight itself is what synthesis uses."""
    if store.admission(model_id) is None:
        return "not_admitted"
    total = store.outcomes_for_model(model_id)
    return "established" if sum(total.values()) >= established_after else "provisional"


def fitness_factor(store: ModelFitnessStore, agent_name: str, serving_model: str | None) -> float:
    """The factor synthesis multiplies into a claim's evidence weight:
    1.0 for deterministic claims, 0.0 for a model that was never admitted
    (the gate), otherwise the (agent, model) pairing's current weight."""
    if not is_model_backed(serving_model):
        return 1.0
    if store.admission(serving_model) is None:
        return 0.0
    return current_fitness_weight(store, agent_name, serving_model)


def rank_models_for(store: ModelFitnessStore, agent_name: str, candidates: list[str]) -> list[dict]:
    """Section 6.7: fitness informs which model is asked for on the next
    similar task. Admitted candidates only, best first (ties keep the
    caller's order)."""
    ranked = [{"model": m, "fitness": current_fitness_weight(store, agent_name, m),
               "standing": model_standing(store, m)}
              for m in candidates if store.admission(m) is not None]
    return sorted(ranked, key=lambda r: -r["fitness"])
