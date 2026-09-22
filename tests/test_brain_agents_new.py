from athenaeum_brain.agents import MasterOfPhysics, MasterOfPhilosophy, MasterOfTheology
from athenaeum_brain.claims import Claim


def test_physics_computes_real_free_fall_time():
    p = MasterOfPhysics()
    claims = p.explore("how long does it take an object falling from 19.6m to land?", "q1")
    assert len(claims) == 1
    assert "2.00s" in claims[0].statement  # sqrt(2*19.6/9.8) = 2.0 exactly


def test_physics_cross_examine_confirms_correct_claim():
    p = MasterOfPhysics()
    correct = Claim(question_id="q1", round=1, issuing_agent="SomeoneElse",
                     statement="an object falling from 19.6m takes approximately 2.00s to hit the ground (v0=0, g=9.8 m/s^2)",
                     claim_type="empirical", confidence=0.95,
                     defeat_condition="x", jurisdiction_check=True)
    resp = p.cross_examine(correct, "q1")
    assert resp.relation == "corroborates"


def test_physics_cross_examine_challenges_wrong_claim():
    p = MasterOfPhysics()
    wrong = Claim(question_id="q1", round=1, issuing_agent="SomeoneElse",
                  statement="an object falling from 19.6m takes approximately 5.00s to hit the ground (v0=0, g=9.8 m/s^2)",
                  claim_type="empirical", confidence=0.95,
                  defeat_condition="x", jurisdiction_check=True)
    resp = p.cross_examine(wrong, "q1")
    assert resp.relation == "challenges"


def test_philosophy_flags_is_ought_gap_on_normative_question():
    ph = MasterOfPhilosophy()
    claims = ph.explore("should we always keep our promises?", "q1")
    assert len(claims) == 1
    assert claims[0].claim_type == "normative"
    assert "is-ought" in claims[0].statement


def test_philosophy_does_not_fire_on_purely_descriptive_question():
    ph = MasterOfPhilosophy()
    assert ph.explore("is 17 prime?", "q1") == []


def test_philosophy_challenges_empirical_claim_smuggling_normative_conclusion():
    ph = MasterOfPhilosophy()
    claim = Claim(question_id="q1", round=1, issuing_agent="SomeoneElse",
                  statement="the data shows we should ban this substance",
                  claim_type="empirical", confidence=0.9,
                  defeat_condition="x", jurisdiction_check=True)
    resp = ph.cross_examine(claim, "q1")
    assert resp.relation == "challenges"
    assert "category error" in resp.statement


def test_philosophy_does_not_challenge_properly_typed_normative_claim():
    ph = MasterOfPhilosophy()
    claim = Claim(question_id="q1", round=1, issuing_agent="SomeoneElse",
                  statement="we should ban this substance",
                  claim_type="normative", confidence=0.9,
                  defeat_condition="x", jurisdiction_check=True)
    assert ph.cross_examine(claim, "q1") is None


def test_theology_produces_traditional_claim_capped_below_empirical_certainty():
    t = MasterOfTheology()
    claims = t.explore("what does stoicism hold about the good life?", "q1")
    assert len(claims) == 1
    assert claims[0].claim_type == "traditional"
    assert claims[0].confidence < 1.0


def test_theology_challenges_traditional_claim_asserted_at_empirical_confidence():
    t = MasterOfTheology()
    overclaimed = Claim(question_id="q1", round=1, issuing_agent="SomeoneElse",
                         statement="according to buddhism: X is true",
                         claim_type="traditional", confidence=1.0,
                         defeat_condition="x", jurisdiction_check=True)
    resp = t.cross_examine(overclaimed, "q1")
    assert resp.relation == "challenges"
    assert "empirical-grade certainty" in resp.statement


def test_theology_does_not_challenge_properly_capped_traditional_claim():
    t = MasterOfTheology()
    fine = Claim(question_id="q1", round=1, issuing_agent="SomeoneElse",
                 statement="according to epicureanism: X is true",
                 claim_type="traditional", confidence=0.7,
                 defeat_condition="x", jurisdiction_check=True)
    assert t.cross_examine(fine, "q1") is None
