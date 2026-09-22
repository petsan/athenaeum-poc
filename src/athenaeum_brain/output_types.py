"""
Output-type classification and structured answer synthesis (Section 5.4).

A single "most likely outcome" framing blurs together three genuinely
different kinds of uncertainty. This module classifies which of Research
Answer / Forecast / Recommendation a question is asking for, and builds
each type's structure according to its own semantics -- never a shared
generic confidence number.
"""
from __future__ import annotations

RESEARCH = "research"
FORECAST = "forecast"
RECOMMENDATION = "recommendation"

_FORECAST_CUES = ("will ", "probability", "chance of", "likely to", "odds of")
_RECOMMENDATION_CUES = ("should we", "what should", "recommend", "ought we")


def classify_output_type(question: str) -> list[str]:
    """Section 5.4 / 3.1: classify which output type(s) a question is
    asking for. A question may legitimately warrant more than one --
    'should we do X' implies both a Research Answer about the facts and a
    Recommendation about the choice (5.4's own example) -- in which case
    Research is always included alongside Recommendation. A pure Forecast
    question (no recommendation cue) stands alone, since a probability
    estimate doesn't inherently imply a separate research section. Absent
    either cue, Research is the default, matching 5.4's own description of
    it as "the default type for descriptive/explanatory questions"."""
    q = question.lower()
    types = []
    if any(cue in q for cue in _FORECAST_CUES):
        types.append(FORECAST)
    if any(cue in q for cue in _RECOMMENDATION_CUES):
        types.append(RECOMMENDATION)
    if RESEARCH not in types and (not types or RECOMMENDATION in types):
        types.insert(0, RESEARCH)
    return types


def build_research_answer(committed: list[dict], dissent: list[dict], plural_answers: list[dict]) -> dict:
    """Section 5.2/5.4: leading conclusion, alternatives, dissent, citations.
    When the underlying claims are jurisdictionally plural (Section 4.2),
    there is no single leading_conclusion by design -- plural_conclusions
    carries the full labeled set instead, non-collapsed."""
    leading = committed[0] if len(committed) == 1 and not plural_answers else None
    citations = sorted({src for c in committed for src in c.get("supporting_provenance", [])})
    return {
        "output_type": RESEARCH,
        "leading_conclusion": leading,
        "plural_conclusions": plural_answers,
        "alternatives_considered": [d["claim"] for d in dissent],
        "dissent": dissent,
        "citations": citations,
        "claim_type_flags": sorted({c.get("claim_type") for c in committed}),
    }


class ForecastSpecError(ValueError):
    """A Forecast built without its required resolution structure (Section
    5.4) is a hard error, not a best-effort guess -- an under-specified
    forecast is exactly the kind of thing that would otherwise drift into
    being presented with Research-confidence grammar by accident."""


def build_forecast_answer(*, statement: str, probability: float, resolution_criterion: str,
                           resolution_source: str, deadline: str, sensitivity: str,
                           assumptions: list[str] = ()) -> dict:
    """Section 5.4: probability is a genuine probability, kept in its own
    'probability' field, never 'confidence' -- structurally separating the
    two makes the category error 5.4 warns about (conflating forecast
    probability with research confidence) hard to introduce by accident,
    not just by convention."""
    if not (0.0 <= probability <= 1.0):
        raise ForecastSpecError(f"probability {probability} out of [0,1] range")
    required = {
        "resolution_criterion": resolution_criterion,
        "resolution_source": resolution_source,
        "deadline": deadline,
        "sensitivity": sensitivity,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ForecastSpecError(f"Forecast missing required field(s): {', '.join(missing)}")
    return {
        "output_type": FORECAST,
        "statement": statement,
        "probability": probability,
        "resolution_criterion": resolution_criterion,
        "resolution_source": resolution_source,
        "deadline": deadline,
        "assumptions": list(assumptions),
        "sensitivity": sensitivity,
        "resolved": None,
    }


def resolve_forecast(forecast: dict, outcome: bool) -> dict:
    """Marks a Forecast resolved. Section 5.4's last bullet: a resolved
    forecast is ALWAYS material for re-evaluation, wired via
    reevaluation.forecast_is_material -- resolution is what this flag
    exists to drive, not just record."""
    resolved = dict(forecast)
    resolved["resolved"] = outcome
    return resolved


def build_recommendation_answer(*, decision_maker: str, objectives: list[str], constraints: list[str],
                                 chosen_option: str, alternatives: list[dict], reversibility: str,
                                 review_trigger: str) -> dict:
    """Section 5.4: always explicitly value-laden (Philosophy's
    jurisdiction, Section 2.2) -- never presented as if it followed from
    evidence alone the way a Research Answer does. value_laden is a fixed
    output, not a caller-supplied parameter, so it can't be accidentally
    omitted."""
    return {
        "output_type": RECOMMENDATION,
        "decision_maker": decision_maker,
        "objectives": list(objectives),
        "constraints": list(constraints),
        "chosen_option": chosen_option,
        "alternatives_considered": list(alternatives),
        "reversibility": reversibility,
        "review_trigger": review_trigger,
        "value_laden": True,
    }


def compose_answer(output_types: list[str], sections: dict) -> dict:
    """Section 5.4: a question warranting more than one output type is
    presented as clearly labeled, separate sections, never blended into
    one voice -- the same non-collapsing principle Section 4.2 established
    for jurisdictionally plural answers, now applied across output types
    instead of across agents."""
    missing = [t for t in output_types if t not in sections]
    if missing:
        raise ValueError(f"compose_answer: missing section(s) for {missing}")
    return {"output_types": list(output_types), "sections": {t: sections[t] for t in output_types}}
