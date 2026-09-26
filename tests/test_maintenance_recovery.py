"""A Maintainer killed at any point picks up where it left off: in-flight
units resume from their last completed round, finished-but-unrecorded units
are recorded once, and cadence state survives."""
import pytest
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.ledger import QuestionLedger
from athenaeum_body.reputability_store import ReputabilityStore
from athenaeum_body.consolidation_store import ConsolidationStore
from athenaeum_body.human_checkpoint_store import HumanCheckpointStore
from athenaeum_brain import model_backed_reasoning
from athenaeum_brain.idle_evolution import IdleContext
from athenaeum_brain.maintenance import Maintainer, MaintenancePolicy

QUESTIONS = {"q1": "is 17 prime?", "q2": "how should we round 2.5?", "q3": "is 21 prime?"}


@pytest.fixture(autouse=True)
def _no_model_fallback(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)


class Host:
    """Everything durable lives on disk under tmp; a 'process' is just a
    Maintainer object built over it, which a test can throw away (the crash)."""
    def __init__(self, tmp):
        self.tmp, self.cas = tmp, ContentAddressedStore(tmp / "cas")

    def log(self, name):
        return CheckpointLog(cas=self.cas, index_path=self.tmp / f"{name}.txt")

    def maintainer(self, **policy):
        idle = IdleContext(ledger=QuestionLedger(self.log("ledger")), reputability=ReputabilityStore(self.log("rep")),
                           consolidation=ConsolidationStore(self.log("cons"), ContentAddressedStore(self.tmp / "arch")),
                           checkpoints=HumanCheckpointStore(self.log("cp")))
        return Maintainer(idle=idle, log_for=self.log, policy=MaintenancePolicy(**policy))


def _statements(m, qid):
    versions = m.ledger.get(qid).versions
    assert len(versions) == 1, f"{qid} recorded {len(versions)} times"
    return [c["statement"] for c in versions[0]["committed"]]


def test_a_fresh_maintainer_has_nothing_to_recover(tmp_path):
    m = Host(tmp_path).maintainer()
    assert m.recovered == [] and m.scheduler._heap == []


def test_mid_way_questions_resume_and_each_is_answered_once(tmp_path):
    host = Host(tmp_path)
    m = host.maintainer(idle_every_questions=99)
    for qid, q in QUESTIONS.items():
        m.submit_question(qid, q)
    for _ in range(5):
        m.tick()  # interleaved: several questions part-way through
    del m      # the crash

    m2 = host.maintainer(idle_every_questions=99)
    assert sorted(m2.recovered) == sorted(QUESTIONS)
    m2.run()
    assert _statements(m2, "q1") == ["17 is prime"]
    assert _statements(m2, "q3") == ["21 is not prime"]
    assert len(m2.ledger.get("q2").versions[0]["plural_answers"]) == 1


def test_a_question_finished_but_not_recorded_is_recorded_on_restart(tmp_path):
    host = Host(tmp_path)
    m = host.maintainer(idle_every_questions=99)
    m.submit_question("q1", "is 17 prime?")
    while m.scheduler._heap:
        m.scheduler.process_one_round()  # the rounds ran and checkpointed, the harvest never happened
    del m

    m2 = host.maintainer(idle_every_questions=99)
    assert m2.recovered == ["q1"]
    assert _statements(m2, "q1") == ["17 is prime"]
    assert [e["kind"] for e in m2.events] == ["question"]


def test_recording_twice_is_impossible(tmp_path):
    """The answer was recorded, but the process died before the unit left
    the registry: the replay must not append a second version."""
    host = Host(tmp_path)
    m = host.maintainer(idle_every_questions=99)
    m.submit_question("q1", "is 17 prime?")
    while m.scheduler._heap:
        m.scheduler.process_one_round()
    m._on_question_done("q1")  # recorded ... and then the crash, before the registry update
    del m

    m2 = host.maintainer(idle_every_questions=99)
    assert _statements(m2, "q1") == ["17 is prime"]  # exactly one version


def test_an_idle_cycle_mid_way_resumes(tmp_path):
    host = Host(tmp_path)
    m = host.maintainer()
    m.submit_question("q1", "is 17 prime?")
    while not m.events:
        m.tick()                      # the question finishes ...
    m.tick(); m.tick()                # ... and the dry-spell idle cycle gets two rounds in
    del m

    m2 = host.maintainer()
    assert m2.recovered == ["idle-1"]
    [event] = m2.run()
    assert event["kind"] == "idle" and event["cycle_id"] == "idle-1"
    assert m2.cycles == 1             # the counter survived; no second cycle started


def test_cadence_state_and_pending_amendments_survive(tmp_path):
    host = Host(tmp_path)
    m = host.maintainer(idle_every_questions=5)
    m.submit_question("q1", "is 17 prime?")
    m.submit_question("q2", "is 19 prime?")
    while m.scheduler._heap:
        m.tick()
    m._m["pending_amendments"]["idle-x"] = {"params": {}, "rationale": "r"}
    m._save()
    del m

    m2 = host.maintainer(idle_every_questions=5)
    assert m2.answered_since_idle == 2
    assert "idle-x" in m2.pending_amendments
