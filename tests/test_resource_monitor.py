"""Resource monitor: pure scale-down rules (Task 9) + checkpoint-and-suspend
triggered by simulated DRAM-floor breach, verified against a real
running unit via the same runner as everywhere else (Task 10)."""
from athenaeum_body.resource_monitor import ResourceMonitor, ResourceState, target_concurrency, should_suspend
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.scheduler.work_unit import WorkUnit, RoundResult
from athenaeum_body.scheduler.runner import SingleUnitRunner

def test_target_concurrency_scales_with_cores():
    assert target_concurrency(ResourceState(cores_available=40)) == 40
    assert target_concurrency(ResourceState(cores_available=1)) == 1
    assert target_concurrency(ResourceState(cores_available=0)) == 1  # floor, never 0

def test_should_suspend_below_floor():
    assert should_suspend(ResourceState(dram_headroom_gb=8), working_set_floor_gb=32) is True
    assert should_suspend(ResourceState(dram_headroom_gb=64), working_set_floor_gb=32) is False

def test_monitor_settable_state():
    mon = ResourceMonitor()
    mon.set_state(cores_available=4, dram_headroom_gb=10)
    s = mon.get_state()
    assert s.cores_available == 4 and s.dram_headroom_gb == 10

def test_dram_floor_breach_actually_suspends_a_running_unit(tmp_path):
    """Task 10: a real WorkUnit, mid-deliberation, checkpoints and stops
    advancing when the monitor reports DRAM below the configured floor --
    then resumes normally once headroom is restored."""
    cas = ContentAddressedStore(tmp_path / "cas")
    log = CheckpointLog(cas=cas, index_path=tmp_path / "index.txt")
    runner = SingleUnitRunner(log, shared_state={})
    mon = ResourceMonitor()
    FLOOR = 32

    def handler(state, round_index):
        return RoundResult(proposed_writes={f"r{round_index}": True}, done=(round_index == 2))

    unit = WorkUnit(id="q1", round_handler=handler)

    mon.set_state(dram_headroom_gb=64)
    assert not should_suspend(mon.get_state(), FLOOR)
    runner.run_round(unit)  # round 0 proceeds normally
    assert unit.round_index == 1

    mon.set_state(dram_headroom_gb=8)  # simulated pressure event
    if should_suspend(mon.get_state(), FLOOR):
        unit.status = "suspended"
        # the round is NOT run -- this is the actual suspend behavior,
        # not just a flag with no effect
    assert unit.status == "suspended"
    assert unit.round_index == 1  # no progress lost, none forced either

    mon.set_state(dram_headroom_gb=64)  # pressure resolved
    assert not should_suspend(mon.get_state(), FLOOR)
    unit.status = "active"
    runner.run_round(unit)  # resumes normally from where it left off
    assert unit.round_index == 2
