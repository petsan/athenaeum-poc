import pytest
from athenaeum_brain.output_types import (
    classify_output_type, build_research_answer, build_forecast_answer,
    ForecastSpecError, resolve_forecast, build_recommendation_answer, compose_answer,
    RESEARCH, FORECAST, RECOMMENDATION,
)
from athenaeum_brain.reevaluation import forecast_is_material


def test_classify_defaults_to_research():
    assert classify_output_type("what caused the 2008 financial crisis?") == [RESEARCH]


def test_classify_recommendation_implies_research_too():
    types = classify_output_type("should we adopt this policy?")
    assert types == [RESEARCH, RECOMMENDATION]


def test_classify_pure_forecast_stands_alone():
    assert classify_output_type("what is the probability this ships by March?") == [FORECAST]


def test_build_research_answer_single_conclusion():
    committed = [{"statement": "17 is prime", "supporting_provenance": ["computed:trial_division"], "claim_type": "formal"}]
    ans = build_research_answer(committed, dissent=[], plural_answers=[])
    assert ans["output_type"] == RESEARCH
    assert ans["leading_conclusion"]["statement"] == "17 is prime"
    assert ans["citations"] == ["computed:trial_division"]


def test_build_research_answer_plural_has_no_single_leading_conclusion():
    committed = [{"statement": "a", "supporting_provenance": [], "claim_type": "formal"},
                 {"statement": "b", "supporting_provenance": [], "claim_type": "executable"}]
    plural = [{"subject": "2.5", "conclusions": []}]
    ans = build_research_answer(committed, dissent=[], plural_answers=plural)
    assert ans["leading_conclusion"] is None
    assert ans["plural_conclusions"] == plural


def test_forecast_requires_resolution_structure():
    with pytest.raises(ForecastSpecError):
        build_forecast_answer(statement="X happens", probability=0.6,
                               resolution_criterion="", resolution_source="Reuters",
                               deadline="2026-12-31", sensitivity="low")


def test_forecast_rejects_out_of_range_probability():
    with pytest.raises(ForecastSpecError):
        build_forecast_answer(statement="X happens", probability=1.5,
                               resolution_criterion="X is reported", resolution_source="Reuters",
                               deadline="2026-12-31", sensitivity="low")


def test_forecast_probability_field_is_not_called_confidence():
    f = build_forecast_answer(statement="X happens", probability=0.6,
                               resolution_criterion="X is reported", resolution_source="Reuters",
                               deadline="2026-12-31", sensitivity="low")
    assert "probability" in f
    assert "confidence" not in f


def test_forecast_resolution_is_always_material():
    f = build_forecast_answer(statement="X happens", probability=0.6,
                               resolution_criterion="X is reported", resolution_source="Reuters",
                               deadline="2026-12-31", sensitivity="low")
    assert forecast_is_material(f)["material"] is False
    resolved = resolve_forecast(f, outcome=True)
    result = forecast_is_material(resolved)
    assert result["material"] is True
    assert "resolved" in result["reasons"][0]


def test_recommendation_is_always_flagged_value_laden():
    rec = build_recommendation_answer(
        decision_maker="Ops team", objectives=["minimize downtime"], constraints=["budget"],
        chosen_option="do X", alternatives=[{"option": "do Y", "why_not": "costlier"}],
        reversibility="easily reversible", review_trigger="if downtime exceeds 1h/month")
    assert rec["value_laden"] is True
    assert rec["output_type"] == RECOMMENDATION


def test_compose_answer_keeps_sections_separate_non_collapsing():
    sections = {
        RESEARCH: {"output_type": RESEARCH, "leading_conclusion": {"statement": "fact"}},
        RECOMMENDATION: {"output_type": RECOMMENDATION, "chosen_option": "do X", "value_laden": True},
    }
    composed = compose_answer([RESEARCH, RECOMMENDATION], sections)
    assert composed["output_types"] == [RESEARCH, RECOMMENDATION]
    assert composed["sections"][RESEARCH]["leading_conclusion"]["statement"] == "fact"
    assert composed["sections"][RECOMMENDATION]["chosen_option"] == "do X"


def test_compose_answer_errors_on_missing_section():
    with pytest.raises(ValueError):
        compose_answer([RESEARCH, FORECAST], {RESEARCH: {}})
