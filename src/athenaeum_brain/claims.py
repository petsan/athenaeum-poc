"""The normalized claim structure (brain-design.md Section 3.5)."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List
import itertools

_counter = itertools.count()

def next_claim_id() -> str:
    return f"claim-{next(_counter)}"

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
    claim_id: str = field(default_factory=next_claim_id)

    def to_dict(self) -> dict:
        return asdict(self)
