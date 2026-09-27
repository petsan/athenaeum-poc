"""Two Brain bugs found by batch 12's deliberation suite (known-bugs #40, #41).

#40: both rounding agents ignored the requested precision ("round 0.125 to
two decimal places" committed "0.125 rounds to 0"), and a precision written
as a digit was itself rounded as a value.
#41: "which came first, X or Y?" got no chronology claim; only
"before/after" phrasing did.
"""
import pytest

from athenaeum_brain import model_backed_reasoning
from athenaeum_brain.agents import rounding_request
from athenaeum_brain.rounds import cross_examination_round, exploration_round, framing_round, synthesis_round


@pytest.fixture(autouse=True)
def _no_models(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)


def committed(question):
    frame = framing_round(question, "q")
    exp = exploration_round(frame, "q")
    return [c.statement for c in synthesis_round(exp, cross_examination_round(exp, "q"))["committed"]]


@pytest.mark.parametrize("question, places, values", [
    ("how should we round 2.5?", 0, ["2.5"]),
    ("round 0.125 to two decimal places", 2, ["0.125"]),
    ("round 0.125 to 2 decimal places", 2, ["0.125"]),          # the "2" is the precision, not a value
    ("round 3.14159 to 3 dp", 3, ["3.14159"]),
    ("round 2.45 to the nearest tenth", 1, ["2.45"]),
    ("round 7.5 to the nearest whole number", 0, ["7.5"]),
])
def test_the_precision_is_read_and_never_rounded_itself(question, places, values):
    assert rounding_request(question) == (places, values)


def test_rounding_to_decimal_places_gives_both_conventions():
    got = committed("round 0.125 to two decimal places")
    assert "0.125 rounds to 0.13 (classical round-half-up convention)" in got
    assert "0.125 rounds to 0.12 (IEEE-754 round-half-to-even convention)" in got
    assert not any("rounds to 0 (" in s for s in got)
    assert not any(s.startswith("2 rounds") for s in committed("round 0.125 to 2 decimal places"))


def test_rounding_to_an_integer_is_unchanged():
    got = committed("how should we round 2.5?")
    assert "2.5 rounds to 3 (classical round-half-up convention)" in got
    assert "2.5 rounds to 2 (IEEE-754 round-half-to-even convention)" in got


@pytest.mark.parametrize("question", [
    "which came first, the moon landing or the fall of the Berlin Wall?",
    "was the moon landing earlier than the fall of the Berlin Wall?",
    "did the moon landing precede the fall of the Berlin Wall?",
    "did the moon landing happen before the fall of the Berlin Wall?",
])
def test_every_ordinary_way_of_asking_order_gets_the_answer(question):
    assert ("'moon landing' (1969-07-20) occurred before 'fall of the berlin wall' (1989-11-09)"
            in committed(question))
