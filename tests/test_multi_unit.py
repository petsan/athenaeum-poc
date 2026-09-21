from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.scheduler.work_unit import WorkUnit, RoundResult
from athenaeum_body.scheduler.runner import SingleUnitRunner
from athenaeum_body.scheduler.multi_unit import MultiUnitScheduler

def make(tmp_path):
    cas = ContentAddressedStore(tmp_path / "cas")
    log = CheckpointLog(cas=cas, index_path=tmp_path / "index.txt")
    shared = {}
    runner = SingleUnitRunner(log, shared)
    return MultiUnitScheduler(runner), shared

def handler_factory(name, rounds=2):
    def h(state, round_index):
        return RoundResult(proposed_writes={f"{name}_r{round_index}": True}, done=(round_index == rounds - 1))
    return h

def test_time_sliced_round_robin_and_cross_unit_visibility(tmp_path):
    sched, shared = make(tmp_path)
    a = WorkUnit(id="a", priority=1, round_handler=handler_factory("a"))
    b = WorkUnit(id="b", priority=1, round_handler=handler_factory("b"))
    sched.submit(a)
    sched.submit(b)

    sched.process_one_round()  # a: round 0
    sched.process_one_round()  # b: round 0 -- must see a's round-0 write already
    assert "a_r0" in shared  # cross-unit visibility: b's round sees a's committed write

    completed = sched.run_to_completion()
    assert set(completed) == {"a", "b"}

def test_priority_ordering(tmp_path):
    sched, shared = make(tmp_path)
    low = WorkUnit(id="low", priority=0, round_handler=handler_factory("low", rounds=1))
    high = WorkUnit(id="high", priority=10, round_handler=handler_factory("high", rounds=1))
    sched.submit(low)
    sched.submit(high)
    first = sched.process_one_round()
    assert first.id == "high"
