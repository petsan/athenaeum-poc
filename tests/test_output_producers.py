"""Section 5.4: real producers for the Forecast and Recommendation output
types, plus the Physics height-parsing fix they depended on
(known-bugs.md #21)."""
import pytest
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.scheduler.runner import SingleUnitRunner
from athenaeum_brain import model_backed_reasoning
from athenaeum_brain.agents import MasterOfPhysics
from athenaeum_brain.claims import Claim
from athenaeum_brain.loop import make_deliberation_unit
from athenaeum_brain.rounds import synthesis_round
from athenaeum_brain.output_types import (
    FORECAST, RECOMMENDATION, forecast_section_from_claims, recommendation_section_from_claims,
)


@pytest.fixture(autouse=True)
def _no_model_fallback(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)


def _answer(tmp_path, question):
    log = CheckpointLog(cas=ContentAddressedStore(tmp_path / "cas"), index_path=tmp_path / "i.txt")
    runner = SingleUnitRunner(log, shared_state={})
    unit = make_deliberation_unit(question, "q")
    while unit.status != "completed":
        runner.run_round(unit)
    return log.read_latest()["shared_state"]["answer"]


def _forecasts(question):
    return [c for c in MasterOfPhysics().explore(question, "q") if c.forecast]


# --- known-bugs #21: only real heights are heights -------------------------

@pytest.mark.parametrize("question,heights", [
    ("did the berlin wall fall in 1989?", []),                      # a year, not a height
    ("is 17 prime and does a ball fall 4.9m in 1 second?", ["4.9"]),  # 17 and 1 aren't heights
    ("how long does it take an object falling from 19.6m to land?", ["19.6"]),  # not also '19'
    ("how long does it take to fall 20 meters?", ["20"]),
    ("dropped from 20 meters at 5 m/s", ["20"]),                     # 5 m/s is a speed
    ("how long does an object take to fall from 30?", ["30"]),       # 'from N' with no unit
    ("will an object dropped from 20m land within 3 seconds?", ["20"]),  # 3 is a time bound
])
def test_only_numbers_that_are_heights_become_heights(question, heights):
    assert MasterOfPhysics()._heights(question) == heights


def test_year_in_a_history_question_produces_no_free_fall_claim():
    assert MasterOfPhysics()._explore_deterministic("did the berlin wall fall in 1989?", "q") == []


# --- Forecast producer ------------------------------------------------------

@pytest.mark.parametrize("question,probability", [
    ("will an object dropped from 20m land within 3 seconds?", 0.9),     # 48% slack
    ("will an object dropped from 20m land within 2.3 seconds?", 0.75),  # ~14% slack
    ("will an object dropped from 20m land within 2.05 seconds?", 0.5),  # ~1% slack
    ("will an object dropped from 45m land within 3 seconds?", 0.02),    # vacuum time 3.03s
    ("will an object dropped from 20m take more than 2 seconds?", 0.95),  # drag only helps
    ("will an object dropped from 20m take more than 3 seconds?", 0.1),   # needs ~1s of drag
])
def test_forecast_probability_follows_the_room_left_for_air_resistance(question, probability):
    [claim] = _forecasts(question)
    assert claim.forecast["probability"] == probability


def test_forecast_keeps_probability_out_of_confidence():
    """5.4's category error: forecast probability must never be conflated
    with research confidence."""
    [claim] = _forecasts("will an object dropped from 45m land within 3 seconds?")
    assert claim.confidence == 0.95
    assert claim.forecast["probability"] == 0.02
    assert claim.output_type_relevance == [FORECAST]


def test_forecast_states_what_would_flip_it():
    [claim] = _forecasts("will an object dropped from 20m land within 3 seconds?")
    assert "0.98s" in claim.forecast["sensitivity"]
    assert "<= 3s" in claim.forecast["resolution_criterion"]
    assert any("air resistance" in a for a in claim.forecast["assumptions"])


@pytest.mark.parametrize("question", [
    "how long does it take an object dropped from 20m to land?",  # not a forecast question
    "will an object dropped from 20m land?",                       # nothing to resolve against
])
def test_no_forecast_without_a_forecast_question_and_a_bound(question):
    assert _forecasts(question) == []


def test_loop_builds_the_forecast_section(tmp_path):
    answer = _answer(tmp_path, "will an object dropped from 20m land within 3 seconds?")
    section = answer["output_answer"]["sections"][FORECAST]
    assert section["available"] and section["issuing_agent"] == "Physics"
    assert section["probability"] == 0.9 and section["resolved"] is None


def test_forecast_question_nobody_can_answer_says_so(tmp_path):
    answer = _answer(tmp_path, "will it rain tomorrow?")
    section = answer["output_answer"]["sections"][FORECAST]
    assert section["available"] is False and "no committed claim" in section["reason"]


def test_challenged_forecast_is_not_used():
    [claim] = _forecasts("will an object dropped from 20m land within 3 seconds?")
    challenge = Claim(question_id="q", round=2, issuing_agent="Logic", statement="x",
                      claim_type="procedural", confidence=1.0, defeat_condition="x",
                      jurisdiction_check=True, relation="challenges", target_claim_id=claim.claim_id)
    result = synthesis_round([claim], [challenge])
    section = forecast_section_from_claims([c.to_dict() for c in result["committed"]])
    assert section["available"] is False


# --- Recommendation producer -----------------------------------------------

def test_conflicting_objectives_produce_no_manufactured_choice(tmp_path):
    answer = _answer(tmp_path, "should we round 2.5 up or down?")
    section = answer["output_answer"]["sections"][RECOMMENDATION]
    assert section["available"] and section["value_laden"] is True
    assert section["chosen_option"].startswith("none chosen")
    assert {a["issuing_agent"] for a in section["alternatives_considered"]} == {"Mathematics", "Engineering"}
    assert len(section["objectives"]) == 2
    # the research section still carries the honest plural answer alongside it
    assert answer["output_answer"]["sections"]["research"]["plural_conclusions"]


def test_one_objective_chooses_every_option_it_covers():
    def opt(agent, option):
        return {"issuing_agent": agent, "claim_id": option, "confidence": 1.0,
                "recommendation_option": {"option": option, "serves_objective": "same goal",
                                          "reversibility": "reversible"}}
    section = recommendation_section_from_claims([opt("Mathematics", "a"), opt("Mathematics", "b")])
    assert section["chosen_option"] == "a; b"
    assert section["objectives"] == ["same goal"]


def test_recommendation_question_with_no_options_says_so(tmp_path):
    answer = _answer(tmp_path, "should we believe 17 is prime?")
    section = answer["output_answer"]["sections"][RECOMMENDATION]
    assert section["available"] is False and "course of action" in section["reason"]
