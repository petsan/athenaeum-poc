"""Runs a real deliberation through the SAME Body engine proven in the
Body POC -- checkpointing, and kill-mid-deliberation-then-resume."""
import sys, pathlib
sys.path.insert(0, "src")
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.scheduler.runner import SingleUnitRunner
from athenaeum_brain.loop import make_deliberation_unit

def make_runner(tmp_path):
    cas = ContentAddressedStore(tmp_path / "cas")
    log = CheckpointLog(cas=cas, index_path=tmp_path / "index.txt")
    return log, SingleUnitRunner(log, shared_state={})

def test_deliberation_runs_to_completion_on_body_engine(tmp_path):
    log, runner = make_runner(tmp_path)
    unit = make_deliberation_unit("is 17 prime?", "q1")
    while unit.status != "completed":
        runner.run_round(unit)
    final = log.read_latest()
    answer = final["shared_state"]["answer"]
    assert any("17 is prime" in c["statement"] for c in answer["committed"])
    # Section 5.4: the structured output-type section rides along on the
    # same answer, built from the same synthesis result, not bolted on
    assert answer["output_answer"]["output_types"] == ["research"]
    assert "17 is prime" in answer["output_answer"]["sections"]["research"]["leading_conclusion"]["statement"]

def test_deliberation_survives_kill_and_resume(tmp_path):
    log, runner = make_runner(tmp_path)
    unit = make_deliberation_unit("is 17 prime?", "q1")
    runner.run_round(unit)  # framing only
    runner.run_round(unit)  # + exploration
    assert unit.round_index == 2

    # simulate kill: fresh log/runner from disk, like a real process restart
    cas2 = ContentAddressedStore(tmp_path / "cas")
    log2 = CheckpointLog(cas=cas2, index_path=tmp_path / "index.txt")
    state = log2.read_latest()
    runner2 = SingleUnitRunner(log2, shared_state=state["shared_state"])
    resumed_index = runner2.resume_round_index("q1")
    assert resumed_index == 2  # nothing lost

    fresh_unit = make_deliberation_unit("is 17 prime?", "q1")
    fresh_unit.round_index = resumed_index
    while fresh_unit.status != "completed":
        runner2.run_round(fresh_unit)
    answer = log2.read_latest()["shared_state"]["answer"]
    assert any("17 is prime" in c["statement"] for c in answer["committed"])

def test_jurisdictional_conflict_survives_body_engine_and_resume(tmp_path):
    log, runner = make_runner(tmp_path)
    unit = make_deliberation_unit("how should we round 2.5?", "q-conflict")
    runner.run_round(unit)  # framing
    runner.run_round(unit)  # exploration

    # kill here, resume fresh -- same pattern as the primality kill/resume test
    cas2 = ContentAddressedStore(tmp_path / "cas")
    log2 = CheckpointLog(cas=cas2, index_path=tmp_path / "index.txt")
    state = log2.read_latest()["shared_state"]
    runner2 = SingleUnitRunner(log2, shared_state=state)
    fresh = make_deliberation_unit("how should we round 2.5?", "q-conflict")
    fresh.round_index = runner2.resume_round_index("q-conflict")
    while fresh.status != "completed":
        runner2.run_round(fresh)

    answer = log2.read_latest()["shared_state"]["answer"]
    assert len(answer["plural_answers"]) == 1
    # Mathematics + Engineering's conflicting conclusions, plus Philosophy's
    # standalone is-ought claim on this normative-phrased question
    assert len(answer["committed"]) == 3
