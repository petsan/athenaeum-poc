"""The maintenance cadence (questions and idle cycles on one time-sliced
scheduler), and the concurrency bug it exposed (known-bugs.md #26)."""
import pytest
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.scheduler.runner import SingleUnitRunner
from athenaeum_body.scheduler.multi_unit import MultiUnitScheduler
from athenaeum_body.ledger import QuestionLedger
from athenaeum_body.schemas import QuestionLedgerEntry
from athenaeum_body.reputability_store import ReputabilityStore
from athenaeum_body.consolidation_store import ConsolidationStore
from athenaeum_body.domain_fidelity_store import DomainFidelityStore
from athenaeum_body.human_checkpoint_store import HumanCheckpointStore
from athenaeum_body.belief_graph_store import BeliefGraphStore
from athenaeum_body.audit_store import AuditStore
from athenaeum_brain import model_backed_reasoning
from athenaeum_brain.claims import Claim
from athenaeum_brain.loop import make_deliberation_unit
from athenaeum_brain.human_input import clear_checkpoint
from athenaeum_brain.idle_evolution import IdleContext, make_idle_evolution_unit, amendment_checkpoint_key
from athenaeum_brain.maintenance import Maintainer, MaintenancePolicy


@pytest.fixture(autouse=True)
def _no_model_fallback(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)


def _log(tmp, name):
    return CheckpointLog(cas=ContentAddressedStore(tmp / "cas"), index_path=tmp / f"{name}.txt")


# --- known-bugs #26 ----------------------------------------------------------------

def test_interleaved_deliberations_each_answer_their_own_question(tmp_path):
    ledger = QuestionLedger(_log(tmp_path, "ledger"))
    idle_ctx = IdleContext(ledger=ledger, reputability=ReputabilityStore(_log(tmp_path, "rep")))
    ledger.submit(QuestionLedgerEntry(id="old"))
    ledger.append_version("old", {"question": "q", "frame": {}, "committed": [], "dissent": [], "plural_answers": []})
    sched = MultiUnitScheduler(SingleUnitRunner(_log(tmp_path, "sched"), shared_state={}))
    for unit in (make_deliberation_unit("is 17 prime?", "A"),
                 make_deliberation_unit("how should we round 2.5?", "B"),
                 make_idle_evolution_unit(idle_ctx, "idle-x", priority=0)):
        sched.submit(unit)  # equal priority: strictly interleaved, round by round
    sched.run_to_completion()
    state = sched.runner.shared_state
    assert [c["statement"] for c in state["deliberation:A"]["answer"]["committed"]] == ["17 is prime"]
    assert len(state["deliberation:B"]["answer"]["plural_answers"]) == 1
    assert state["deliberation:A"]["answer"]["question"] == "is 17 prime?"
    assert "idle_result" in state["idle:idle-x"]


# --- the Maintainer ------------------------------------------------------------------

class World:
    def __init__(self, tmp, **policy):
        self.tmp = tmp
        self.cas = ContentAddressedStore(tmp / "cas")
        self.ledger = QuestionLedger(self.log("ledger"))
        self.rep = ReputabilityStore(self.log("rep"))
        self.cp = HumanCheckpointStore(self.log("cp"))
        self.graph = BeliefGraphStore(self.log("graph"))
        self.audits = AuditStore(self.log("audits"))
        idle = IdleContext(ledger=self.ledger, reputability=self.rep, checkpoints=self.cp,
                           consolidation=ConsolidationStore(self.log("cons"), ContentAddressedStore(tmp / "arch")),
                           fidelity=DomainFidelityStore(self.log("fid")))
        self.m = Maintainer(idle=idle, log_for=self.log, belief_graph=self.graph, audits=self.audits,
                            policy=MaintenancePolicy(**policy))

    def log(self, name):
        return CheckpointLog(cas=self.cas, index_path=self.tmp / f"{name}.txt")

    def legacy(self, qid, statements_sources, importance=0.0):
        self.ledger.submit(QuestionLedgerEntry(id=qid, importance=importance))
        committed = [Claim(question_id=qid, round=1, issuing_agent="Physics", statement=s, claim_type="empirical",
                           confidence=0.8, defeat_condition="a measurement", jurisdiction_check=True,
                           supporting_provenance=[src], status="committed").to_dict()
                     for s, src in statements_sources]
        self.ledger.append_version(qid, {"question": "should we ban it?", "frame": {}, "committed": committed,
                                         "dissent": [], "plural_answers": []})


def test_questions_are_answered_recorded_and_rated_then_an_idle_cycle_runs(tmp_path):
    w = World(tmp_path, idle_every_questions=3)
    for i, q in enumerate(["is 17 prime?", "how should we round 2.5?", "did world war i cause world war ii?"]):
        w.m.submit_question(f"q{i}", q)
    events = w.m.run()
    assert [e["kind"] for e in events] == ["question", "question", "question", "idle"]
    assert [c["statement"] for c in w.ledger.get("q0").versions[-1]["committed"]] == ["17 is prime"]
    assert w.ledger.get("q1").importance > 0
    assert w.graph.node("answer:q2:v0") is not None
    leftovers = [k for k in w.m.scheduler.runner.shared_state if k.startswith(("deliberation:", "idle:"))]
    assert leftovers == []  # harvested namespaces are removed: checkpoints stay bounded


def test_questions_are_served_before_idle_work(tmp_path):
    w = World(tmp_path, idle_every_questions=1)
    w.m.submit_question("q1", "is 17 prime?")
    w.m.submit_question("q2", "is 19 prime?")
    # q1 finishing queues an idle cycle while q2 is still running; q2 still finishes first
    order = [e.get("question_id", e.get("cycle_id")) for e in w.m.run()]
    assert order[:3] == ["q1", "q2", "idle-1"]


def test_an_idle_system_does_not_spin(tmp_path):
    w = World(tmp_path, idle_every_questions=99)
    w.m.submit_question("q1", "is 17 prime?")
    assert [e["kind"] for e in w.m.run()] == ["question", "idle"]  # one cycle for the dry spell
    assert w.m.run() == []                                          # nothing new: nothing to do
    w.m.submit_question("q2", "is 19 prime?")
    assert [e["kind"] for e in w.m.run()] == ["question", "idle"]


def test_idle_findings_reopen_important_questions(tmp_path):
    w = World(tmp_path)
    w.legacy("q-hi", [("the data shows we should ban it", "study:1")], importance=0.9)
    [event] = w.m.run()
    assert event["kind"] == "idle" and event["reopened"] == ["q-hi"]
    assert len(w.ledger.get("q-hi").versions) == 2
    assert w.graph.node("answer:q-hi:v1") is not None  # the reopened version is in the graph


def test_an_approved_amendment_is_adopted_on_the_next_cycle(tmp_path):
    w = World(tmp_path)
    for src in ("journal:a", "journal:b"):
        for _ in range(5):
            w.rep.record_outcome(src, "source", "corroborated")
    w.legacy("q1", [("the data shows we should ban it", "journal:a"), ("the trial shows we must stop it", "journal:b")])
    first = w.m.run()[-1]
    assert first["amendments_adopted"] == [] and "idle-1" in w.m.pending_amendments
    clear_checkpoint(w.cp, amendment_checkpoint_key("idle-1"), reviewer_id="rev", reviewer_role="reviewer",
                     decision="approve")
    w.m.submit_question("q2", "is 17 prime?")
    second = w.m.run()[-1]
    assert "idle-1" in second["amendments_adopted"]
    assert w.rep.current_standard()["version"] == 1


def test_audits_run_on_their_cadence(tmp_path):
    w = World(tmp_path, audit_every_cycles=2)
    w.m.submit_question("q1", "is 17 prime?")
    assert w.m.run()[-1]["audited"] is False
    w.m.submit_question("q2", "is 19 prime?")
    assert w.m.run()[-1]["audited"] is True
    assert w.audits.history("reevaluation") and w.audits.history("consolidation") is not None
