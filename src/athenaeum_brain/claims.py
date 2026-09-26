"""The normalized claim structure (brain-design.md Section 3.5)."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List
import uuid

# Defeat conditions that name nothing that could ever happen (Section 2.2).
# Shared by Physics's falsifiability challenge and its Domain Fidelity
# fingerprint so the two can't drift apart.
VACUOUS_DEFEAT_CONDITIONS = {"", "none", "n/a", "na", "-", "nothing", "no defeat condition",
                             "cannot be falsified", "unfalsifiable", "not applicable"}


def is_vacuous_defeat(defeat_condition: str | None) -> bool:
    return (defeat_condition or "").strip().lower().rstrip(".") in VACUOUS_DEFEAT_CONDITIONS


def next_claim_id() -> str:
    """Globally unique, not a per-process counter: claims from different
    processes (distributed_worker.py rounds, a restarted runner, past
    ledger versions) are compared and cross-examined together, and a
    counter restarts at claim-0 in every process (known-bugs.md #23)."""
    return f"claim-{uuid.uuid4().hex[:16]}"

@dataclass
class Claim:
    question_id: str
    round: int
    issuing_agent: str
    statement: str
    claim_type: str                 # empirical|formal|executable|normative|traditional|human_input|procedural
    confidence: float
    defeat_condition: str
    jurisdiction_check: bool        # True if issuing_agent believes this is in its domain
    relation: str = "asserts"       # asserts|corroborates|challenges|abstains|clarifies
    target_claim_id: str = None
    supporting_provenance: List[str] = field(default_factory=list)
    status: str = "proposed"        # proposed|committed  (Section 4.4 -- only synthesis may commit)
    subject: str = None              # the specific entity/value this claim is about, independently
                                     # extracted by the issuing agent (see rounds.py synthesis_round
                                     # for how conflict-grouping normalizes this across agents)
    argument: dict = None            # optional {'premises': [...], 'conclusion': str} for Logic
                                     # to check via logic_engine.check_validity (Section 2.2)
    output_type_relevance: List[str] = None  # which of research|forecast|recommendation
                                     # (output_types.py) this claim bears on; None until an
                                     # agent/round sets it explicitly -- not yet mandatory
    serving_model: str = None       # which local model (Body's registry) produced this
                                     # claim, for Model Fitness tracking (Section 6.7) --
                                     # None for a deterministic, non-model-backed claim
    reputability_factor: float = None  # set only by synthesis_round (Section 4.1): the
                                     # weakest-link grade weight across supporting_provenance,
                                     # using grades AT TIME OF USE -- None if unweighted
    fitness_factor: float = None     # set only by synthesis_round (Section 6.7): the
                                     # (agent, serving_model) fitness weight at time of use;
                                     # 1.0 for deterministic claims, 0.0 for an unadmitted model
    weighted_confidence: float = None  # confidence * reputability_factor * fitness_factor
                                     # (each factor only when its lookup was given); `confidence`
                                     # itself stays the issuing agent's own, untouched value
    forecast: dict = None            # Section 5.4: keyword args for output_types.
                                     # build_forecast_answer when this claim IS a forecast;
                                     # its probability is kept here, never in `confidence`
    recommendation_option: dict = None  # Section 5.4: {'option', 'serves_objective',
                                     # 'reversibility'} when this claim's conclusion is one
                                     # course of action a Recommendation can weigh
    claim_id: str = field(default_factory=next_claim_id)

    def to_dict(self) -> dict:
        return asdict(self)
