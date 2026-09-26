"""Section 4.1: evidence-weighted synthesis -- committed claims are
weighted by the reputability of what they rest on (grades at time of use),
and the Research Answer's leading conclusion follows that weight."""
import pytest
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.reputability_store import ReputabilityStore
from athenaeum_body.scheduler.runner import SingleUnitRunner
from athenaeum_brain import model_backed_reasoning
from athenaeum_brain.claims import Claim
from athenaeum_brain.rounds import synthesis_round, reputability_factor, GRADE_WEIGHT
from athenaeum_brain.output_types import build_research_answer
from athenaeum_brain.evaluation import a1_full_workflow, ablation_no_reputability_weighting
from athenaeum_brain.loop import make_deliberation_unit

# Both claims come from deterministic paths; stub the model fallback so a
# live OLMo worker can't add a third claim and change what's being compared.
QUESTION = "should we believe 17 is prime?"


@pytest.fixture(autouse=True)
def _no_model_fallback(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)


def _claim(agent, confidence, provenance, subject=None):
    return Claim(question_id="q", round=1, issuing_agent=agent, statement=f"{agent} says",
                 claim_type="formal", confidence=confidence, defeat_condition="x",
                 jurisdiction_check=True, supporting_provenance=provenance, subject=subject)


def _store(tmp_path):
    cas = ContentAddressedStore(tmp_path / "cas")
    return ReputabilityStore(CheckpointLog(cas=cas, index_path=tmp_path / "rep.txt"))


def _reject(store, source):
    for _ in range(3):
        store.record_outcome(source, "source", "challenged")
    assert store.current_grade(source)["grade"] == "rejected"


def test_factor_is_weakest_link_across_provenance():
    grades = {"a": "foundational", "b": "contested"}
    assert reputability_factor(["a", "b"], grades.get) == GRADE_WEIGHT["contested"]
    assert reputability_factor(["a"], grades.get) == 1.0


def test_claim_citing_nothing_gets_zero_factor():
    assert reputability_factor([], lambda s: "foundational") == 0.0


def test_weighting_sets_fields_but_never_touches_raw_confidence():
    c = _claim("Mathematics", 0.9, ["src"])
    result = synthesis_round([c], [], grade_lookup=lambda s: "contested")
    committed = result["committed"][0]
    assert committed.confidence == 0.9
    assert committed.reputability_factor == GRADE_WEIGHT["contested"]
    assert committed.weighted_confidence == pytest.approx(0.9 * GRADE_WEIGHT["contested"])


def test_without_lookup_claims_stay_unweighted():
    result = synthesis_round([_claim("Mathematics", 0.9, ["src"])], [])
    assert result["committed"][0].weighted_confidence is None


def test_weighting_never_changes_what_is_committed():
    """A claim on a rejected source is still committed (it survived
    cross-examination); weighting only orders it lower."""
    claims = [_claim("Mathematics", 1.0, ["bad"]), _claim("Physics", 0.5, ["good"])]
    grades = {"bad": "rejected", "good": "foundational"}
    result = synthesis_round(claims, [], grade_lookup=grades.get)
    assert len(result["committed"]) == 2 and result["dissent"] == []


def test_leading_conclusion_follows_weight_not_raw_confidence():
    claims = [_claim("Mathematics", 1.0, ["bad"]), _claim("Physics", 0.5, ["good"])]
    grades = {"bad": "rejected", "good": "foundational"}
    result = synthesis_round(claims, [], grade_lookup=grades.get)
    ans = build_research_answer([c.to_dict() for c in result["committed"]], [], [])
    assert ans["leading_conclusion"]["issuing_agent"] == "Physics"
    assert [c["issuing_agent"] for c in ans["supporting_conclusions"]] == ["Mathematics"]


def test_unweighted_leading_conclusion_falls_back_to_raw_confidence():
    ans = build_research_answer([_claim("A", 0.5, ["s"]).to_dict(), _claim("B", 0.9, ["s"]).to_dict()], [], [])
    assert ans["leading_conclusion"]["issuing_agent"] == "B"


def test_plural_answer_still_has_no_leading_conclusion_when_weighted():
    a = _claim("Mathematics", 1.0, ["s"], subject="2.5")
    b = _claim("Engineering", 1.0, ["s"], subject="2.5")
    b.statement = "different"
    result = synthesis_round([a, b], [], grade_lookup=lambda s: "foundational")
    ans = build_research_answer([c.to_dict() for c in result["committed"]], [], result["plural_answers"])
    assert ans["leading_conclusion"] is None and ans["supporting_conclusions"] == []


def test_reputability_ablation_is_now_distinguishable_from_a1(tmp_path):
    """Section 9.7: with trial division's track record rejected, A1 leads
    with Philosophy's claim; the no-weighting ablation still leads with
    Mathematics on raw confidence. Previously these were identical."""
    store = _store(tmp_path)
    _reject(store, "computed:trial_division")
    lookup = lambda s: store.current_grade(s)["grade"]

    a1 = a1_full_workflow(QUESTION, "q-abl", grade_lookup=lookup)
    ablated = ablation_no_reputability_weighting(QUESTION, "q-abl")

    assert {c["issuing_agent"] for c in a1["committed"]} == {"Mathematics", "Philosophy"}
    assert a1["research"]["leading_conclusion"]["issuing_agent"] == "Philosophy"
    assert ablated["research"]["leading_conclusion"]["issuing_agent"] == "Mathematics"


def test_loop_weights_with_grades_at_time_of_use(tmp_path):
    """The weight on the answer must come from the same pre-deliberation
    grade that loop.py snapshots into source_grades_at_use, not from the
    grade after this deliberation's own outcome is recorded."""
    store = _store(tmp_path)
    for _ in range(4):
        store.record_outcome("computed:trial_division", "source", "corroborated")
    # One more corroboration (this deliberation's own) tips it to foundational.
    assert store.current_grade("computed:trial_division")["grade"] == "provisionally_accepted"

    cas = ContentAddressedStore(tmp_path / "loopcas")
    log = CheckpointLog(cas=cas, index_path=tmp_path / "loop.txt")
    runner = SingleUnitRunner(log, shared_state={})
    unit = make_deliberation_unit("is 17 prime?", "q-tou", reputability=store)
    while unit.status != "completed":
        runner.run_round(unit)
    answer = log.read_latest()["shared_state"]["answer"]

    math = next(c for c in answer["committed"] if c["issuing_agent"] == "Mathematics")
    assert answer["source_grades_at_use"]["computed:trial_division"]["grade"] == "provisionally_accepted"
    assert math["reputability_factor"] == GRADE_WEIGHT["provisionally_accepted"]
    assert store.current_grade("computed:trial_division")["grade"] == "foundational"
