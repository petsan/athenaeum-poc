"""Section 7.1 importance rating and 7.3 reopen-with-diff, on the real
deliberation loop and real stores."""
import pytest
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.scheduler.runner import SingleUnitRunner
from athenaeum_body.ledger import QuestionLedger
from athenaeum_body.schemas import QuestionLedgerEntry
from athenaeum_body.reputability_store import ReputabilityStore
from athenaeum_body.consolidation_store import ConsolidationStore
from athenaeum_body.api import build_app
from athenaeum_brain import model_backed_reasoning
from athenaeum_brain.loop import make_deliberation_unit
from athenaeum_brain.consolidation import claim_key, record_survival, compact
from athenaeum_brain.reopening import (
    importance_rating, count_dependents, rate_and_store_importance, answer_diff,
    reopen_question, reopen_if_material,
)


@pytest.fixture(autouse=True)
def _no_model_fallback(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)


class World:
    """One ledger, one reputability store, and a fresh unit log per run."""
    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.cas = ContentAddressedStore(tmp_path / "cas")
        self.ledger = QuestionLedger(self.log("ledger"))
        self.rep = ReputabilityStore(self.log("rep"))
        self._n = 0

    def log(self, name):
        return CheckpointLog(cas=self.cas, index_path=self.tmp / f"{name}.txt")

    def fresh_log(self):
        self._n += 1
        return self.log(f"unit-{self._n}")

    def answer(self, qid, question):
        self.ledger.submit(QuestionLedgerEntry(id=qid))
        log = self.fresh_log()
        runner = SingleUnitRunner(log, shared_state={})
        unit = make_deliberation_unit(question, qid, reputability=self.rep)
        while unit.status != "completed":
            runner.run_round(unit)
        answer = log.read_latest()["shared_state"]["answer"]
        self.ledger.append_version(qid, answer)
        return answer

    def reject(self, source):
        for _ in range(3):
            self.rep.record_outcome(source, "source", "challenged")


# --- 7.1 importance ---------------------------------------------------------

def test_importance_components_are_explained():
    r = importance_rating({"routed_agents": ["Logic", "Mathematics", "Philosophy"],
                           "output_types": ["research", "recommendation"]},
                          dependents=2, requested_priority=1.0)
    assert r["components"] == {"breadth": 2 / 3, "output_types": 1.0, "dependency": 0.5, "requested": 1.0}
    assert r["importance"] == round(0.4 * 2 / 3 + 0.1 + 0.3 * 0.5 + 0.2, 4)


def test_logic_does_not_count_as_a_domain():
    only_logic = importance_rating({"routed_agents": ["Logic"], "output_types": ["research"]})
    assert only_logic["components"]["breadth"] == 0.0


def test_requested_priority_must_be_a_probability_like_value():
    with pytest.raises(ValueError):
        importance_rating({"routed_agents": []}, requested_priority=2.0)


def test_dependents_are_other_questions_committing_the_same_claims(tmp_path):
    w = World(tmp_path)
    w.answer("q1", "is 17 prime?")
    w.answer("q2", "should we believe 17 is prime?")  # also commits "17 is prime"
    w.answer("q3", "how should we round 2.5?")
    assert count_dependents(w.ledger, "q1") == 1
    assert count_dependents(w.ledger, "q3") == 0


def test_rated_importance_is_stored_and_bounds_checked(tmp_path):
    w = World(tmp_path)
    w.answer("q1", "is 17 prime?")
    rating = rate_and_store_importance(w.ledger, "q1", requested_priority=0.5)
    assert w.ledger.get("q1").importance == rating["importance"] > 0
    with pytest.raises(ValueError):
        w.ledger.update_importance("q1", 1.5)


def test_api_computes_importance_instead_of_a_fixed_placeholder(tmp_path):
    submit, _, get_q, _ = build_app(tmp_path)
    out = submit("is 17 prime?")
    assert out["importance"] == get_q(out["id"])["importance"]
    assert out["importance"] == round(0.4 / 3, 4)  # one domain; not the old 0.5 placeholder


def test_answer_records_its_own_question_and_frame(tmp_path):
    a = World(tmp_path).answer("q1", "is 17 prime?")
    assert a["question"] == "is 17 prime?"
    assert "Mathematics" in a["frame"]["routed_agents"]


# --- 7.3 reopen-if-material --------------------------------------------------

def test_not_material_is_not_reopened(tmp_path):
    w = World(tmp_path)
    w.answer("q1", "is 17 prime?")
    result = reopen_if_material(w.ledger, "q1", reputability=w.rep, unit_log=w.fresh_log())
    assert result == {"reopened": False, "reason": "not material", "importance": 0.0}
    assert len(w.ledger.get("q1").versions) == 1


def test_material_but_unimportant_is_held_back_with_reasons(tmp_path):
    w = World(tmp_path)
    w.answer("q1", "is 17 prime?")
    rate_and_store_importance(w.ledger, "q1")  # one domain -> ~0.13
    w.reject("computed:trial_division")
    result = reopen_if_material(w.ledger, "q1", reputability=w.rep, unit_log=w.fresh_log())
    assert result["reopened"] is False and "below the 0.3 threshold" in result["reason"]
    assert any("newly contested" in r for r in result["materiality_reasons"])


def test_material_and_important_reopens_with_an_explicit_diff(tmp_path):
    w = World(tmp_path)
    first = w.answer("q1", "is 17 prime?")
    rate_and_store_importance(w.ledger, "q1", requested_priority=1.0)
    w.reject("computed:trial_division")

    result = reopen_if_material(w.ledger, "q1", reputability=w.rep, unit_log=w.fresh_log())

    assert result["reopened"] is True
    versions = w.ledger.get("q1").versions
    assert len(versions) == 2 and versions[0] == first  # the prior version is untouched
    diff = versions[1]["diff"]
    assert diff["added"] == [] and diff["removed"] == []
    assert diff["leading_conclusion"]["change"] == "unchanged"
    assert diff["leading_conclusion"]["confidence"] == "decreased"
    [change] = diff["weight_changes"]
    # first use: ungraded (provisional, 0.8); now 1 corroboration vs 3 challenges -> contested (0.4)
    assert change["claim"] == "Mathematics::17 is prime"
    assert (change["from"], change["to"]) == (0.8, 0.4)
    assert any("newly contested" in c for c in diff["cause"])
    assert versions[1]["reopen_context"]["prior_version"] == 0


def test_resolved_forecast_reopens_regardless_of_importance(tmp_path):
    w = World(tmp_path)
    w.answer("q1", "will an object dropped from 20m land within 3 seconds?")
    assert w.ledger.get("q1").importance == 0.0
    result = reopen_if_material(w.ledger, "q1", reputability=w.rep, unit_log=w.fresh_log(),
                                forecast_outcome=True)
    assert result["reopened"] is True
    ctx = result["answer"]["reopen_context"]
    assert ctx["forecast_resolution"] == {"outcome": True, "probability_given": 0.9}
    assert any("forecast resolved" in r for r in ctx["reasons"])


def test_forecast_outcome_for_a_question_with_no_forecast_changes_nothing(tmp_path):
    w = World(tmp_path)
    w.answer("q1", "is 17 prime?")
    result = reopen_if_material(w.ledger, "q1", reputability=w.rep, unit_log=w.fresh_log(),
                                forecast_outcome=True)
    assert result["reopened"] is False


# --- reopen mechanics ---------------------------------------------------------

def test_reopen_expands_consolidated_claims_first(tmp_path):
    w = World(tmp_path)
    answer = w.answer("q1", "is 17 prime?")
    cons = ConsolidationStore(w.log("cons"), ContentAddressedStore(tmp_path / "archive"))
    key = claim_key(answer["committed"][0])
    for _ in range(5):
        record_survival(cons, key, answer["committed"][0])
    compact(cons, key)

    new = reopen_question(w.ledger, "q1", reasons=["manual"], unit_log=w.fresh_log(),
                          reputability=w.rep, consolidation=cons)
    [trace] = new["reopen_context"]["expanded_traces"]
    assert trace["claim"] == key and trace["full_trace"]["cycles"] == 5


def test_reopen_context_does_not_nest(tmp_path):
    w = World(tmp_path)
    w.answer("q1", "is 17 prime?")
    reopen_question(w.ledger, "q1", reasons=["first"], unit_log=w.fresh_log())
    second = reopen_question(w.ledger, "q1", reasons=["second"], unit_log=w.fresh_log())
    assert "reopen_context" not in second["reopen_context"]["prior_answer"]
    assert second["reopen_context"]["prior_version"] == 1


def test_legacy_answer_without_question_text_is_refused(tmp_path):
    w = World(tmp_path)
    w.ledger.submit(QuestionLedgerEntry(id="old"))
    w.ledger.append_version("old", {"committed": []})
    with pytest.raises(ValueError, match="predates question recording"):
        reopen_question(w.ledger, "old", reasons=["x"], unit_log=w.fresh_log())


def _ans(*claims, leading=None):
    committed = [{"issuing_agent": a, "statement": s, "confidence": c} for a, s, c in claims]
    lead = next((c for c in committed if c["statement"] == leading), None)
    return {"committed": committed, "output_answer": {"sections": {"research": {"leading_conclusion": lead}}}}


def test_diff_reports_a_changed_leading_conclusion_and_membership():
    prior = _ans(("Mathematics", "a", 1.0), ("Physics", "b", 0.5), leading="a")
    new = _ans(("Physics", "b", 0.5), ("Philosophy", "c", 0.9), leading="c")
    d = answer_diff(prior, new)
    assert d["added"] == ["Philosophy::c"] and d["removed"] == ["Mathematics::a"]
    assert d["leading_conclusion"] == {"change": "changed", "from": "a", "to": "c"}


def test_diff_reports_a_leading_conclusion_that_disappears():
    d = answer_diff(_ans(("Mathematics", "a", 1.0), leading="a"), _ans())
    assert d["leading_conclusion"] == {"change": "disappeared", "from": "a"}
