"""Batch 5, Phase W: a round that raises used to drop its unit silently
(MultiUnitScheduler pops a unit before running it and requeues only on
success), leaving the question 'active' forever. Now the Maintainer retries
it from its last completed round, and gives it up visibly after
max_round_failures."""
import pytest
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.ledger import QuestionLedger
from athenaeum_body.reputability_store import ReputabilityStore
from athenaeum_brain import model_backed_reasoning, maintenance
from athenaeum_brain.idle_evolution import IdleContext
from athenaeum_brain.maintenance import Maintainer, MaintenancePolicy


@pytest.fixture(autouse=True)
def _no_model_fallback(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)


class Faults:
    """Wraps the unit factories so chosen units raise on a chosen round --
    `times` times in total (None: always), counted across retries and
    Maintainer restarts alike. A failing handler first scribbles on its own
    namespace, as a real handler might before hitting an error."""
    def __init__(self, monkeypatch):
        self.plan = {}   # unit id -> {"round": r, "times": n or None}
        self.raised = {}
        for name in ("make_deliberation_unit", "make_idle_evolution_unit"):
            real = getattr(maintenance, name)
            monkeypatch.setattr(maintenance, name, self._wrap(real, name))

    def _wrap(self, real, name):
        def factory(*args, **kwargs):
            unit = real(*args, **kwargs)
            handler, uid = unit.round_handler, unit.id
            ns = f"deliberation:{uid}" if name == "make_deliberation_unit" else f"idle:{uid}"

            def round_handler(state, round_index):
                plan = self.plan.get(uid)
                if plan and plan["round"] == round_index and (
                        plan["times"] is None or self.raised.get(uid, 0) < plan["times"]):
                    self.raised[uid] = self.raised.get(uid, 0) + 1
                    state.setdefault(ns, {})["poison"] = True
                    raise RuntimeError(f"injected failure in {uid} round {round_index}")
                return handler(state, round_index)
            unit.round_handler = round_handler
            return unit
        return factory


class Host:
    def __init__(self, tmp):
        self.tmp, self.cas = tmp, ContentAddressedStore(tmp / "cas")

    def log(self, name):
        return CheckpointLog(cas=self.cas, index_path=self.tmp / f"{name}.txt")

    def maintainer(self, **policy):
        idle = IdleContext(ledger=QuestionLedger(self.log("ledger")), reputability=ReputabilityStore(self.log("rep")))
        return Maintainer(idle=idle, log_for=self.log,
                          policy=MaintenancePolicy(**{"idle_every_questions": 100, **policy}))


def _statements(m, qid):
    return [c["statement"] for c in m.ledger.get(qid).versions[-1]["committed"]]


def test_a_transient_failure_is_retried_and_the_answer_is_unchanged(tmp_path, monkeypatch):
    clean = Host(tmp_path / "clean").maintainer()
    clean.submit_question("q1", "how should we round 2.5?")
    clean.run()

    faults = Faults(monkeypatch)
    faults.plan["q1"] = {"round": 1, "times": 1}
    m = Host(tmp_path / "faulty").maintainer()
    m.submit_question("q1", "how should we round 2.5?")
    events = m.run()
    errors = [e for e in events if e["kind"] == "unit_error"]
    assert len(errors) == 1 and errors[0]["retrying"] and "injected failure in q1 round 1" in errors[0]["error"]
    assert m.ledger.get("q1").status == "completed" and len(m.ledger.get("q1").versions) == 1
    assert _statements(m, "q1") == _statements(clean, "q1")
    assert m.failed == {} and m.scheduler._heap == []


def test_the_failing_round_does_not_leave_partial_state_behind(tmp_path, monkeypatch):
    faults = Faults(monkeypatch)
    faults.plan["q1"] = {"round": 2, "times": 1}
    m = Host(tmp_path).maintainer()
    m.submit_question("q1", "is 17 prime?")
    while not any(e["kind"] == "unit_error" for e in m.events):
        m.tick()
    ns = m.scheduler.runner.shared_state["deliberation:q1"]
    assert "poison" not in ns  # rolled back to the round-1 checkpoint
    m.run()
    assert _statements(m, "q1") == ["17 is prime"]


def test_a_persistent_failure_suspends_the_question_and_spares_the_rest(tmp_path, monkeypatch):
    faults = Faults(monkeypatch)
    faults.plan["bad"] = {"round": 1, "times": None}
    m = Host(tmp_path).maintainer()
    m.submit_question("bad", "is 17 prime?")
    m.submit_question("good", "is 21 prime?")
    events = m.run()
    assert [e["failures"] for e in events if e["kind"] == "unit_error"] == [1, 2]
    (gave_up,) = [e for e in events if e["kind"] == "unit_failed"]
    assert gave_up["unit_id"] == "bad" and gave_up["failures"] == 3 and not gave_up["retrying"]
    assert m.ledger.get("bad").status == "suspended" and m.ledger.get("bad").versions == []
    assert m.failed["bad"]["question"] == "is 17 prime?" and "injected failure" in m.failed["bad"]["last_error"]
    assert "bad" not in m._m["units"] and "deliberation:bad" not in m.scheduler.runner.shared_state
    assert _statements(m, "good") == ["21 is not prime"]
    assert m.run() == []  # nothing left spinning


def test_the_failure_count_survives_a_restart(tmp_path, monkeypatch):
    faults = Faults(monkeypatch)
    faults.plan["q1"] = {"round": 0, "times": None}
    host = Host(tmp_path)
    m = host.maintainer()
    m.submit_question("q1", "is 17 prime?")
    m.tick()
    assert m._m["units"]["q1"]["failures"] == 1
    del m
    m = host.maintainer()   # a restart must not grant three fresh attempts
    assert m.recovered == ["q1"]
    events = m.run()
    assert [e["kind"] for e in events if e["kind"].startswith("unit_")] == ["unit_error", "unit_failed"]
    assert m.failed["q1"]["failures"] == 3 and faults.raised["q1"] == 3
    assert host.maintainer().failed["q1"]["failures"] == 3  # persisted


def test_a_failing_idle_cycle_is_given_up_without_touching_questions(tmp_path, monkeypatch):
    faults = Faults(monkeypatch)
    faults.plan["idle-1"] = {"round": 1, "times": None}
    m = Host(tmp_path).maintainer(idle_every_questions=1)
    m.submit_question("q1", "is 17 prime?")
    events = m.run()
    assert [e["kind"] for e in events] == ["question", "unit_error", "unit_error", "unit_failed"]
    assert m.failed["idle-1"]["kind"] == "idle" and m.ledger.get("q1").status == "completed"
    m.submit_question("q2", "is 21 prime?")
    assert any(e["kind"] == "idle" and e["cycle_id"] == "idle-2" for e in m.run())  # later cycles still run


def test_the_api_reports_a_suspended_question_and_its_error(tmp_path, monkeypatch):
    from athenaeum_body.api import build_app
    faults = Faults(monkeypatch)
    faults.plan["q-1"] = {"round": 1, "times": None}
    app = build_app(tmp_path)
    app.maintainer.submit_question("q-1", "is 17 prime?")
    app.maintainer.run()
    _, list_questions, get_question, _ = app
    q = get_question("q-1")
    assert q["status"] == "suspended" and q["question"] == "is 17 prime?"
    assert "injected failure in q-1 round 1" in q["error"]
    assert list_questions()[0]["error"] == q["error"]
    assert app.maintenance_status()["failed_units"] == ["q-1"]
