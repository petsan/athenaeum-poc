"""known-bugs.md #28: keywords match whole words (with common inflections),
never substrings -- and Physics's everyday motion verbs need physical context."""
import pytest
from athenaeum_brain.agents import (
    mentions, MasterOfMathematics, MasterOfLogic, MasterOfEngineering, MasterOfPhysics,
    MasterOfPhilosophy, MasterOfTheology, MasterOfWorldNews,
)
from athenaeum_brain.claims import Claim
from athenaeum_brain.rounds import framing_round
from athenaeum_brain.evaluation import _empirical_category_error


@pytest.mark.parametrize("text,keyword,expected", [
    ("does a ball fall?", "all", False),        # b-all
    ("is this different?", "if", False),        # d-if-ferent
    ("walk around the ground", "round", False),  # a-round, g-round
    ("is seven prime?", "even", False),          # s-even
    ("because it rained", "cause", False),       # be-cause
    ("walk toward it", "war", False),            # to-war-d
    ("the latest news", "test", False),          # la-test
    ("pass the mustard", "must", False),         # must-ard
    ("are these primes?", "prime", True),        # inflection
    ("the value was rounded", "round", True),
    ("the treaty caused a war", "cause", True),
    ("did it lead to war?", "lead to", True),    # phrase
])
def test_whole_word_matching(text, keyword, expected):
    assert mentions(text, (keyword,)) is expected


@pytest.mark.parametrize("agent,question", [
    (MasterOfLogic, "does a ball fall faster than a feather?"),
    (MasterOfMathematics, "how far around the ground did it roll?"),
    (MasterOfMathematics, "is seven lucky?"),
    (MasterOfEngineering, "what is the latest news?"),
    (MasterOfWorldNews, "did it rain because of clouds?"),
])
def test_substrings_no_longer_route(agent, question):
    assert agent().in_jurisdiction(question) is False


@pytest.mark.parametrize("question,routed", [
    ("did the berlin wall fall in 1989?", False),              # the open limitation, closed
    ("the fall of the berlin wall", False),
    ("does a ball fall faster than a feather?", True),         # physical object
    ("how long does it take an object dropped from 20m to land?", True),
    ("how long does it take to fall 20 meters?", True),        # a height
    ("what force holds the moon in orbit?", True),             # unambiguous physics term
])
def test_physics_motion_verbs_need_physical_context(question, routed):
    assert MasterOfPhysics().in_jurisdiction(question) is routed


def test_berlin_wall_question_routes_only_where_it_belongs():
    assert framing_round("did the fall of the berlin wall lead to the collapse of the soviet union?",
                         "q")["routed_agents"] == ["WorldNews"]


def test_philosophy_category_error_needs_the_whole_word():
    physics = Claim(question_id="q", round=1, issuing_agent="Physics", statement="add mustard for flavour",
                    claim_type="empirical", confidence=0.8, defeat_condition="x", jurisdiction_check=True)
    assert MasterOfPhilosophy().cross_examine(physics, "q") is None
    assert _empirical_category_error("add mustard for flavour") is None
    assert _empirical_category_error("the data says we must act") is not None


def test_theology_tradition_names_match_whole_words():
    assert MasterOfTheology().in_jurisdiction("what does stoicism hold?")
    assert MasterOfTheology().in_jurisdiction("is this a religious question?")
