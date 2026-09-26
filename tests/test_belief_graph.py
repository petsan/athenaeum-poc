"""The Belief Graph: storage semantics, what deliberations record into it,
graph-based dependents (7.1), and 7.2's second materiality trigger."""
import pytest
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.scheduler.runner import SingleUnitRunner
from athenaeum_body.belief_graph_store import BeliefGraphStore
from athenaeum_body.ledger import QuestionLedger
from athenaeum_body.schemas import QuestionLedgerEntry
from athenaeum_body.reputability_store import ReputabilityStore
from athenaeum_brain import model_backed_reasoning
from athenaeum_brain.loop import make_deliberation_unit
from athenaeum_brain.belief_graph import dependents, newly_relevant_claims, latest_answer
from athenaeum_brain.reopening import count_dependents, reopen_if_material, reopen_question


@pytest.fixture(autouse=True)
def _no_model_fallback(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)


class World:
    def __init__(self, tmp):
        self.tmp, self.cas, self.n = tmp, ContentAddressedStore(tmp / "cas"), 0
        self.graph = BeliefGraphStore(self.log("graph"))
        self.ledger = QuestionLedger(self.log("ledger"))
        self.rep = ReputabilityStore(self.log("rep"))

    def log(self, name):
        return CheckpointLog(cas=self.cas, index_path=self.tmp / f"{name}.txt")

    def fresh(self):
        self.n += 1
        return self.log(f"u{self.n}")

    def ask(self, qid, question, importance=0.0):
        self.ledger.submit(QuestionLedgerEntry(id=qid, importance=importance))
        log = self.fresh()
        runner = SingleUnitRunner(log, shared_state={})
        unit = make_deliberation_unit(question, qid, reputability=self.rep, belief_graph=self.graph)
        while unit.status != "completed":
            runner.run_round(unit)
        answer = log.read_latest()["shared_state"]["answer"]
        self.ledger.append_version(qid, answer)
        return answer


# --- storage ----------------------------------------------------------------------

def test_nodes_and_edges_are_write_once(tmp_path):
    g = BeliefGraphStore(CheckpointLog(cas=ContentAddressedStore(tmp_path / "c"), index_path=tmp_path / "g.txt"))
    first = g.add_node("claim:x", "claim", {"statement": "original"})
    again = g.add_node("claim:x", "claim", {"statement": "rewritten"})
    assert again == first and again.data["statement"] == "original"
    e1 = g.add_edge("a", "b", "relies_on")
    assert g.add_edge("a", "b", "relies_on") == e1
    assert g.current_seq() == 2  # the repeats wrote nothing


# --- recording --------------------------------------------------------------------

def test_a_deliberation_is_recorded_with_its_structure(tmp_path):
    w = World(tmp_path)
    w.ask("q1", "should we believe 17 is prime?")
    answer = latest_answer(w.graph, "q1")
    assert answer.id == "answer:q1:v0"
    relied = {e.target_id for e in w.graph.edges(source_id=answer.id, edge_type="relies_on")}
    assert "claim:Mathematics::17 is prime" in relied
    cites = w.graph.edges(source_id="claim:Mathematics::17 is prime", edge_type="cites")
    assert [e.target_id for e in cites] == ["source:computed:trial_division"]


def test_the_same_claim_from_two_questions_is_one_node(tmp_path):
    w = World(tmp_path)
    w.ask("q1", "is 17 prime?")
    w.ask("q2", "should we believe 17 is prime?")
    incoming = w.graph.edges(target_id="claim:Mathematics::17 is prime", edge_type="relies_on")
    assert sorted(e.source_id for e in incoming) == ["answer:q1:v0", "answer:q2:v0"]


def test_dissent_is_recorded_as_dissent(tmp_path):
    w = World(tmp_path)
    from athenaeum_brain.belief_graph import record_answer
    record_answer(w.graph, "qd", {"question": "q", "committed": [], "dissent": [
        {"claim": {"issuing_agent": "Physics", "statement": "we should ban it", "supporting_provenance": []},
         "challenges": []}]}, version=0)
    assert [e.target_id for e in w.graph.edges(source_id="answer:qd:v0", edge_type="dissents")] == \
        ["claim:Physics::we should ban it"]


def test_a_reopen_is_recorded_as_the_next_version(tmp_path):
    w = World(tmp_path)
    w.ask("q1", "is 17 prime?")
    reopen_question(w.ledger, "q1", reasons=["x"], unit_log=w.fresh(), reputability=w.rep, belief_graph=w.graph)
    assert latest_answer(w.graph, "q1").id == "answer:q1:v1"


# --- 7.1 dependents -----------------------------------------------------------------

def test_graph_dependents_agree_with_the_ledger(tmp_path):
    w = World(tmp_path)
    w.ask("q1", "is 17 prime?")
    w.ask("q2", "should we believe 17 is prime?")
    w.ask("q3", "how should we round 2.5?")
    assert dependents(w.graph, "q1") == ["q2"]
    assert dependents(w.graph, "q3") == []
    for qid in ("q1", "q2", "q3"):
        assert count_dependents(w.ledger, qid, w.graph) == count_dependents(w.ledger, qid)


# --- 7.2 trigger 2 ------------------------------------------------------------------

def test_a_later_claim_about_the_same_subject_is_newly_relevant(tmp_path):
    w = World(tmp_path)
    w.ask("q1", "how should we round 2.5?")        # Mathematics + Engineering, subject 2.5
    assert newly_relevant_claims(w.graph, "q1") == []
    w.ask("q2", "should we round 2.50 up or down?")  # same claims? no: statements say '2.50'
    found = newly_relevant_claims(w.graph, "q1")
    assert {f["from_question"] for f in found} == {"q2"}
    assert all(f["subject"] == "numeric:2.5" for f in found)


def test_unrelated_later_claims_are_not_relevant(tmp_path):
    w = World(tmp_path)
    w.ask("q1", "how should we round 2.5?")
    w.ask("q2", "how should we round 3.5?")
    assert newly_relevant_claims(w.graph, "q1") == []


def test_newly_relevant_claim_reopens_an_important_question(tmp_path):
    w = World(tmp_path)
    w.ask("q1", "how should we round 2.5?", importance=0.9)
    w.ask("q2", "should we round 2.50 up or down?")
    result = reopen_if_material(w.ledger, "q1", reputability=w.rep, unit_log=w.fresh(), belief_graph=w.graph)
    assert result["reopened"] is True
    assert any("newly relevant claim" in c for c in result["answer"]["diff"]["cause"])
    # the reopened version is recorded after q2's claims, so they're no longer "new"
    assert newly_relevant_claims(w.graph, "q1") == []
