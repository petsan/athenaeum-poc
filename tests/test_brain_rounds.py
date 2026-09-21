from athenaeum_brain.rounds import framing_round, exploration_round, cross_examination_round, synthesis_round

def test_framing_routes_mathematics_for_numeric_question():
    frame = framing_round("is 17 prime?", "q1")
    assert "Mathematics" in frame["routed_agents"]

def test_full_loop_commits_correct_claim_no_dissent():
    frame = framing_round("is 17 prime?", "q1")
    exp = exploration_round(frame, "q1")
    exam = cross_examination_round(exp, "q1")
    result = synthesis_round(exp, exam)
    assert len(result["committed"]) == 1
    assert result["committed"][0].status == "committed"
    assert result["dissent"] == []

def test_only_synthesis_commits_claims_not_exploration():
    frame = framing_round("is 17 prime?", "q1")
    exp = exploration_round(frame, "q1")
    # Section 4.4: still 'proposed' until synthesis runs
    assert all(c.status == "proposed" for c in exp)

def test_jurisdictional_conflict_produces_plural_answer_not_forced_consensus():
    frame = framing_round("how should we round 2.5?", "q2")
    assert "Mathematics" in frame["routed_agents"] and "Engineering" in frame["routed_agents"]
    exp = exploration_round(frame, "q2")
    exam = cross_examination_round(exp, "q2")
    result = synthesis_round(exp, exam)

    assert len(result["plural_answers"]) == 1
    pa = result["plural_answers"][0]
    assert pa["chaired_by"] == "Logic"
    agents_in_answer = {c["agent"] for c in pa["conclusions"]}
    assert agents_in_answer == {"Mathematics", "Engineering"}
    statements = {c["statement"] for c in pa["conclusions"]}
    assert any("rounds to 3" in s for s in statements)
    assert any("rounds to 2" in s for s in statements)
    # both conclusions are legitimately committed -- neither silently dropped
    assert len(result["committed"]) == 2
    assert result["dissent"] == []

def test_non_conflicting_question_produces_no_plural_answer():
    frame = framing_round("is 17 prime?", "q1")
    exp = exploration_round(frame, "q1")
    exam = cross_examination_round(exp, "q1")
    result = synthesis_round(exp, exam)
    assert result["plural_answers"] == []

def test_conflict_groups_by_normalized_value_not_exact_string():
    """Agents don't coordinate on a shared label -- '2.5' and '2.50'
    (differently formatted, same real number) must still conflict-group."""
    from athenaeum_brain.claims import Claim
    from athenaeum_brain.rounds import synthesis_round
    a = Claim(question_id="q", round=1, issuing_agent="Mathematics",
              statement="rounds to 3", claim_type="formal", confidence=1.0,
              defeat_condition="x", jurisdiction_check=True, subject="2.5")
    b = Claim(question_id="q", round=1, issuing_agent="Engineering",
              statement="rounds to 2", claim_type="executable", confidence=1.0,
              defeat_condition="x", jurisdiction_check=True, subject="2.50")
    result = synthesis_round([a, b], [])
    assert len(result["plural_answers"]) == 1
