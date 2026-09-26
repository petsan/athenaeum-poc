"""known-bugs.md #25: Mathematics claims primality only for whole numbers a
question actually asks about -- the same bug class as #21 for Physics."""
import pytest
from athenaeum_brain.agents import MasterOfMathematics


def _statements(question):
    return [c.statement for c in MasterOfMathematics()._explore_deterministic(question, "q")]


@pytest.mark.parametrize("question,expected", [
    ("is 17 prime?", ["17 is prime"]),
    ("are 7 and 9 prime?", ["7 is prime", "9 is not prime"]),
    ("is 1989 prime?", ["1989 is not prime"]),
    ("is 17 prime and is 17 prime?", ["17 is prime"]),                      # asked twice, claimed once
    ("is 17 prime and does a ball fall 4.9m in 1 second?", ["17 is prime"]),  # not 1 (a duration)
    ("is 20 kg prime?", []),                                                 # a quantity, not a number
    ("is 2.5 prime?", []),                                                   # not a whole number
])
def test_primality_is_claimed_only_for_numbers_in_question(question, expected):
    assert _statements(question) == expected


@pytest.mark.parametrize("question", ["is 4 even?", "what is the sum of 3 and 4?", "is 91 divisible by 7?"])
def test_no_primality_claim_when_primality_isnt_asked(question):
    assert _statements(question) == []


def test_rounding_is_unaffected():
    assert _statements("how should we round 2.5?") == ["2.5 rounds to 3 (classical round-half-up convention)"]
