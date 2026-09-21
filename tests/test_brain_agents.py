from athenaeum_brain.agents import MasterOfMathematics, MasterOfLogic

def test_math_explore_real_primality():
    m = MasterOfMathematics()
    claims = m.explore("is 17 prime and is 12 prime?", "q1")
    stmts = {c.statement for c in claims}
    assert "17 is prime" in stmts
    assert "12 is not prime" in stmts  # genuinely computed, not asserted

def test_math_cross_examine_confirms_correct_claim():
    from athenaeum_brain.claims import Claim
    m = MasterOfMathematics()
    correct = Claim(question_id="q1", round=1, issuing_agent="SomeoneElse",
                     statement="17 is prime", claim_type="formal", confidence=1.0,
                     defeat_condition="x", jurisdiction_check=True)
    resp = m.cross_examine(correct, "q1")
    assert resp.relation == "corroborates"

def test_math_cross_examine_challenges_wrong_claim():
    from athenaeum_brain.claims import Claim
    m = MasterOfMathematics()
    wrong = Claim(question_id="q1", round=1, issuing_agent="SomeoneElse",
                  statement="9 is prime", claim_type="formal", confidence=1.0,
                  defeat_condition="x", jurisdiction_check=True)
    resp = m.cross_examine(wrong, "q1")
    assert resp.relation == "challenges"  # 9 = 3*3, genuinely not prime

def test_logic_flags_out_of_jurisdiction_claim():
    from athenaeum_brain.claims import Claim
    logic = MasterOfLogic()
    claim = Claim(question_id="q1", round=1, issuing_agent="Mathematics",
                  statement="x", claim_type="formal", confidence=1.0,
                  defeat_condition="x", jurisdiction_check=False)
    resp = logic.cross_examine(claim, "q1")
    assert resp.relation == "challenges"
    assert resp.claim_type == "procedural"

def test_engineering_computes_round_half_to_even():
    from athenaeum_brain.agents import MasterOfEngineering
    e = MasterOfEngineering()
    claims = e.explore("how should we round 2.5?", "q1")
    assert any("rounds to 2" in c.statement for c in claims)  # banker's rounding

def test_mathematics_computes_round_half_up():
    m = MasterOfMathematics()
    claims = m.explore("how should we round 2.5?", "q1")
    assert any("rounds to 3" in c.statement for c in claims)  # classical convention
