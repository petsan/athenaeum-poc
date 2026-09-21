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
