from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.scheduler.work_unit import WorkUnit, RoundResult
from athenaeum_body.scheduler.runner import SingleUnitRunner

def three_round_handler(state, round_index):
    return RoundResult(proposed_writes={f"r{round_index}": True}, done=(round_index == 2))

def make_runner(tmp_path):
    cas = ContentAddressedStore(tmp_path / "cas")
    log = CheckpointLog(cas=cas, index_path=tmp_path / "index.txt")
    return log, SingleUnitRunner(log, shared_state={})

def test_kill_mid_round_then_resume(tmp_path):
    log, runner = make_runner(tmp_path)
    unit = WorkUnit(id="q1", round_handler=three_round_handler)

    runner.run_round(unit)  # round 0
    assert unit.round_index == 1
    assert unit.status != "completed"

    # simulate a kill: throw away the in-memory runner/unit, build fresh ones
    resumed_index = runner.resume_round_index("q1")
    assert resumed_index == 1  # progress from round 0 was NOT lost

    fresh_log, fresh_runner = make_runner_from_existing(tmp_path)
    fresh_unit = WorkUnit(id="q1", round_handler=three_round_handler, round_index=resumed_index)
    fresh_runner.run_round(fresh_unit)  # this must be round 1, not round 0 again
    fresh_runner.run_round(fresh_unit)  # round 2 -> done
    assert fresh_unit.status == "completed"

    final = fresh_log.read_latest()
    assert final["shared_state"] == {"r0": True, "r1": True, "r2": True}

def make_runner_from_existing(tmp_path):
    cas = ContentAddressedStore(tmp_path / "cas")
    log = CheckpointLog(cas=cas, index_path=tmp_path / "index.txt")
    state = log.read_latest()
    shared_state = state["shared_state"] if state else {}
    return log, SingleUnitRunner(log, shared_state=shared_state)
