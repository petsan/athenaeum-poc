from athenaeum_brain.agents import MasterOfWorldNews, all_agents, master_agent, _REGISTRY
from athenaeum_brain.claims import Claim
from athenaeum_brain.rounds import ALL_AGENTS, framing_round, exploration_round, cross_examination_round, synthesis_round


# --- registry plumbing (the "adding a new domain is not difficult" ask) ---

def test_registry_includes_world_news():
    names = {a.name for a in all_agents()}
    assert "WorldNews" in names


def test_rounds_all_agents_built_from_registry_not_hardcoded():
    assert any(a.name == "WorldNews" for a in ALL_AGENTS)


def test_registering_a_brand_new_toy_domain_requires_no_other_file_change():
    """Proves the actual claim: decorate a class here, and it's picked up
    by all_agents() with zero edits anywhere else -- this test IS the
    demonstration, not just an assertion about it."""
    before = len(_REGISTRY)

    @master_agent
    class MasterOfWeather:
        name = "Weather"

        def in_jurisdiction(self, q):
            return "weather" in q.lower()

    try:
        assert len(_REGISTRY) == before + 1
        assert any(a.name == "Weather" for a in all_agents())
    finally:
        _REGISTRY.remove(MasterOfWeather)  # test cleanup -- don't leak into other tests


def test_registry_order_is_deterministic():
    names_1 = [a.name for a in all_agents()]
    names_2 = [a.name for a in all_agents()]
    assert names_1 == names_2


# --- real chronology computation ---

def test_wwii_alone_does_not_falsely_match_wwi_substring():
    """The real bug caught while writing this agent: 'world war i' is a
    literal substring of 'world war ii'. A question naming only WWII must
    not silently also 'find' WWI."""
    wn = MasterOfWorldNews()
    found = wn._find_events("What year did World War II start?")
    assert found == ["world war ii"]


def test_both_world_wars_mentioned_are_both_found_in_order():
    wn = MasterOfWorldNews()
    found = wn._find_events("Did World War I happen before World War II?")
    assert found == ["world war i", "world war ii"]


def test_explore_produces_correct_chronological_ordering_claim():
    wn = MasterOfWorldNews()
    claims = wn.explore("did the moon landing happen before the fall of the berlin wall?", "q1")
    stmts = [c.statement for c in claims]
    assert any("occurred before" in s for s in stmts)


def test_explore_flags_chronologically_impossible_causal_claim():
    wn = MasterOfWorldNews()
    # the wall fell in 1989, the Soviet collapse was 1991 -- asking whether
    # the LATER event caused the EARLIER one is chronologically impossible
    claims = wn.explore("did the collapse of the soviet union cause the fall of the berlin wall?", "q1")
    assert any("IMPOSSIBLE" in c.statement for c in claims)


def test_explore_flags_chronologically_possible_causal_claim():
    wn = MasterOfWorldNews()
    claims = wn.explore("did the fall of the berlin wall lead to the collapse of the soviet union?", "q1")
    assert any("POSSIBLE" in c.statement for c in claims)


def test_explore_returns_nothing_for_unrelated_question():
    wn = MasterOfWorldNews()
    assert wn.explore("is 17 prime?", "q1") == []


# --- cross-examination: real chronological consistency checking ---

def test_cross_examine_corroborates_chronologically_valid_causal_claim():
    wn = MasterOfWorldNews()
    claim = Claim(question_id="q1", round=1, issuing_agent="SomeoneElse",
                  statement="the fall of the berlin wall led to the collapse of the soviet union",
                  claim_type="empirical", confidence=0.8,
                  defeat_condition="x", jurisdiction_check=True)
    resp = wn.cross_examine(claim, "q1")
    assert resp.relation == "corroborates"


def test_cross_examine_challenges_reversed_causal_claim():
    wn = MasterOfWorldNews()
    claim = Claim(question_id="q1", round=1, issuing_agent="SomeoneElse",
                  statement="the collapse of the soviet union caused the fall of the berlin wall",
                  claim_type="empirical", confidence=0.8,
                  defeat_condition="x", jurisdiction_check=True)
    resp = wn.cross_examine(claim, "q1")
    assert resp.relation == "challenges"
    assert "IMPOSSIBLE" in resp.statement


def test_cross_examine_abstains_on_unrecognized_events():
    wn = MasterOfWorldNews()
    claim = Claim(question_id="q1", round=1, issuing_agent="SomeoneElse",
                  statement="the invention of sliced bread led to the rise of toaster sales",
                  claim_type="empirical", confidence=0.8,
                  defeat_condition="x", jurisdiction_check=True)
    assert wn.cross_examine(claim, "q1") is None


def test_cross_examine_ignores_non_causal_statements():
    wn = MasterOfWorldNews()
    claim = Claim(question_id="q1", round=1, issuing_agent="SomeoneElse",
                  statement="17 is prime", claim_type="formal", confidence=1.0,
                  defeat_condition="x", jurisdiction_check=True)
    assert wn.cross_examine(claim, "q1") is None


# --- build_timeline utility ---

def test_build_timeline_orders_events_by_real_date():
    wn = MasterOfWorldNews()
    result = wn.build_timeline(["Moon Landing", "World War I", "Fall of the Berlin Wall"])
    ordered_names = [e["event"] for e in result["timeline"]]
    assert ordered_names == ["World War I", "Moon Landing", "Fall of the Berlin Wall"]
    assert result["unrecognized"] == []


def test_build_timeline_reports_unrecognized_events_without_dropping_silently():
    wn = MasterOfWorldNews()
    result = wn.build_timeline(["World War I", "Invention of the Wheel"])
    assert result["unrecognized"] == ["Invention of the Wheel"]
    assert len(result["timeline"]) == 1


# --- full loop integration ---

def test_world_news_question_routes_and_commits_via_real_loop():
    frame = framing_round("did world war i happen before world war ii?", "wn-1")
    assert "WorldNews" in frame["routed_agents"]
    exp = exploration_round(frame, "wn-1")
    exam = cross_examination_round(exp, "wn-1")
    result = synthesis_round(exp, exam)
    assert any("occurred before" in c.statement for c in result["committed"])
