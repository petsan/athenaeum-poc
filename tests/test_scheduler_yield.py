"""Batch 13: quick questions finish first (owner decision, 2026-09-27).
A unit keeps its place unless its round called a model; then it goes to the
back of its priority. Without a policy the scheduler stays round-robin."""
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.scheduler.work_unit import WorkUnit, RoundResult
from athenaeum_body.scheduler.runner import SingleUnitRunner
from athenaeum_body.scheduler.multi_unit import MultiUnitScheduler
from athenaeum_brain import maintenance, model_backed_reasoning
from athenaeum_brain.model_backed_reasoning import ask_model as REAL_ASK_MODEL   # before offline mode stubs it


class Calls:
    """Stands in for the model-call counter: a unit named 'slow*' calls a model every round."""
    n = 0


def scheduler(tmp_path, policy):
    log = CheckpointLog(cas=ContentAddressedStore(tmp_path / "cas"), index_path=tmp_path / "index.txt")
    return MultiUnitScheduler(SingleUnitRunner(log, {}), yield_policy=policy)


def unit(name, rounds=4, priority=0):
    def h(state, i):
        if name.startswith("slow"):
            Calls.n += 1
        return RoundResult(proposed_writes={f"{name}_{i}": True}, done=(i == rounds - 1))
    return WorkUnit(id=name, priority=priority, round_handler=h)


def rounds_in_order(sched):
    ran = []
    while sched._heap:
        ran.append(sched.process_one_round().id)
    return ran


def yielding(tmp_path, monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "model_calls", lambda: Calls.n)
    return scheduler(tmp_path, maintenance.YieldAfterModelCall())


def test_without_a_policy_it_stays_round_robin(tmp_path):
    sched = scheduler(tmp_path, None)
    for n in ("a", "b"):
        sched.submit(unit(n, rounds=2))
    assert rounds_in_order(sched) == ["a", "b", "a", "b"]


def test_quick_units_finish_in_one_go_in_arrival_order(tmp_path, monkeypatch):
    sched = yielding(tmp_path, monkeypatch)
    for n in ("a", "b", "c"):
        sched.submit(unit(n))
    assert rounds_in_order(sched) == ["a"] * 4 + ["b"] * 4 + ["c"] * 4


def test_a_unit_that_calls_a_model_takes_turns(tmp_path, monkeypatch):
    sched = yielding(tmp_path, monkeypatch)
    sched.submit(unit("slow", rounds=3))
    sched.submit(unit("a", rounds=2))
    sched.submit(unit("b", rounds=2))
    # slow gives way after each model call; a and b each run to completion in between
    assert rounds_in_order(sched) == ["slow", "a", "a", "b", "b", "slow", "slow"]


def test_two_model_units_alternate_so_neither_holds_the_queue(tmp_path, monkeypatch):
    sched = yielding(tmp_path, monkeypatch)
    sched.submit(unit("slow1", rounds=2))
    sched.submit(unit("slow2", rounds=2))
    assert rounds_in_order(sched) == ["slow1", "slow2", "slow1", "slow2"]


def test_priority_still_comes_first(tmp_path, monkeypatch):
    sched = yielding(tmp_path, monkeypatch)
    sched.submit(unit("idle", rounds=3, priority=-1))
    sched.process_one_round()                                  # an idle cycle starts on an empty queue
    sched.submit(unit("q", rounds=2, priority=0))
    assert rounds_in_order(sched) == ["q", "q", "idle", "idle"]


def test_every_call_that_reaches_a_model_is_counted(monkeypatch):
    from athenaeum_body.model_serving import LlamaCppBackend
    monkeypatch.setattr(LlamaCppBackend, "infer", lambda self, spec, prompt: "yes")
    before = model_backed_reasoning.model_calls()
    assert REAL_ASK_MODEL("is it?", "olmo3-7b") == "yes"
    assert REAL_ASK_MODEL("is it?", "not-a-lab-model") is None     # never reaches a model: not counted
    assert model_backed_reasoning.model_calls() == before + 1


def test_the_maintainer_uses_the_rule(tmp_path):
    from athenaeum_body.ledger import QuestionLedger
    from athenaeum_body.reputability_store import ReputabilityStore
    from athenaeum_brain.idle_evolution import IdleContext
    cas = ContentAddressedStore(tmp_path / "cas")
    log_for = lambda name: CheckpointLog(cas=cas, index_path=tmp_path / f"{name}.txt")   # noqa: E731
    m = maintenance.Maintainer(idle=IdleContext(ledger=QuestionLedger(log_for("ledger")),
                                                reputability=ReputabilityStore(log_for("rep"))), log_for=log_for)
    assert isinstance(m.scheduler.yield_policy, maintenance.YieldAfterModelCall)
