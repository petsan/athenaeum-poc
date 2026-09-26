"""Batch 7, Phase AD: the Maintainer's in-memory event history is a bounded
window -- it lives as long as the API process -- while run() still returns
every event it produced."""
import pytest
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.ledger import QuestionLedger
from athenaeum_body.reputability_store import ReputabilityStore
from athenaeum_brain import model_backed_reasoning
from athenaeum_brain.idle_evolution import IdleContext
from athenaeum_brain.maintenance import Maintainer, MaintenancePolicy


@pytest.fixture(autouse=True)
def _no_model_fallback(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)


@pytest.fixture
def maintainer(tmp_path):
    cas = ContentAddressedStore(tmp_path / "cas")
    log = lambda name: CheckpointLog(cas=cas, index_path=tmp_path / f"{name}.txt")
    idle = IdleContext(ledger=QuestionLedger(log("ledger")), reputability=ReputabilityStore(log("rep")))
    return Maintainer(idle=idle, log_for=log, policy=MaintenancePolicy(idle_every_questions=100, event_history=5))


def test_run_returns_everything_while_memory_keeps_a_window(maintainer):
    m = maintainer
    for i in range(8):
        m.submit_question(f"q{i}", f"is {101 + 2 * i} prime?")
    events = m.run()
    assert [e["question_id"] for e in events if e["kind"] == "question"] == [f"q{i}" for i in range(8)]
    assert len(events) > 5
    assert m.events == events[-5:]


def test_the_window_holds_across_many_runs_and_direct_emits(maintainer):
    m = maintainer
    for i in range(3):
        m.submit_question(f"q{i}", "is 17 prime?")
        m.run()
    for n in range(1000):
        m.emit({"kind": "error", "error": str(n)})
    assert len(m.events) == 5 and [e["error"] for e in m.events] == ["995", "996", "997", "998", "999"]
