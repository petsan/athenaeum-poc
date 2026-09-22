"""
Real distributed worker dispatch (body-design.md Section 4.2, Task 23) --
a genuinely separate OS process (multiprocessing, fork context -- Task 23
was blocked on "needs a second process/host to be meaningful"; a second
process on the same LXC 104 host satisfies that honestly without the
extra cost/risk of provisioning a brand-new guest for this one test), real
TCP/HTTP between dispatcher and worker, real process termination to prove
worker-loss recovery -- no mocking of the network boundary.
"""
import multiprocessing
import socket
import time
import pytest
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.scheduler.runner import SingleUnitRunner
from athenaeum_body.scheduler.work_unit import WorkUnit
from athenaeum_body.distributed_worker import serve_worker, remote_round_handler, WorkerUnavailable

CTX = multiprocessing.get_context("fork")  # explicit: this test relies on fork's
# closure-sharing (no pickling of the handler_factory needed), which is Linux's
# default but not guaranteed on every platform -- made explicit rather than assumed.


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run_worker_process(port: int, question: str, question_id: str):
    # Runs in the CHILD process. Brain import happens HERE, not at module
    # level -- distributed_worker.py itself stays Brain-agnostic (see its
    # own module docstring); only this test's worker wiring knows it's
    # serving a deliberation unit specifically.
    from athenaeum_brain.loop import make_deliberation_handler

    def factory(unit_spec):
        return make_deliberation_handler(unit_spec["question"], unit_spec["question_id"])

    server = serve_worker("127.0.0.1", port, factory)
    server.serve_forever()


@pytest.fixture
def worker(request):
    question = getattr(request, "param", ("is 17 prime?", "dist-q1"))
    port = _free_port()
    proc = CTX.Process(target=_run_worker_process, args=(port, question[0], question[1]), daemon=True)
    proc.start()
    time.sleep(0.3)  # real process startup -- not instantaneous, unlike an in-process mock
    yield port, proc, question
    if proc.is_alive():
        proc.terminate()
        proc.join(timeout=2)


def test_full_deliberation_runs_via_real_remote_worker(tmp_path, worker):
    port, proc, (question, question_id) = worker
    cas = ContentAddressedStore(tmp_path / "cas")
    log = CheckpointLog(cas=cas, index_path=tmp_path / "index.txt")
    runner = SingleUnitRunner(log, shared_state={})
    handler = remote_round_handler(f"http://127.0.0.1:{port}", {"question": question, "question_id": question_id})
    unit = WorkUnit(id=question_id, round_handler=handler)

    while unit.status != "completed":
        runner.run_round(unit)

    answer = log.read_latest()["shared_state"]["answer"]
    assert any("17 is prime" in c["statement"] for c in answer["committed"])


def test_worker_loss_mid_task_leaves_checkpoint_retryable_then_recovers(tmp_path, worker):
    """Section 4.2: 'loss of a worker mid-task simply requeues the unit.'
    Proven here with a REAL kill -9-equivalent (terminate()) of a real
    process, not a simulated error."""
    port, proc, (question, question_id) = worker
    cas = ContentAddressedStore(tmp_path / "cas")
    log = CheckpointLog(cas=cas, index_path=tmp_path / "index.txt")
    runner = SingleUnitRunner(log, shared_state={})
    handler = remote_round_handler(f"http://127.0.0.1:{port}", {"question": question, "question_id": question_id},
                                    timeout_seconds=3.0)
    unit = WorkUnit(id=question_id, round_handler=handler)

    runner.run_round(unit)  # framing -- succeeds, real worker still alive
    assert unit.round_index == 1
    checkpoint_after_round_0 = log.read_latest()

    proc.terminate()
    proc.join(timeout=2)

    with pytest.raises(WorkerUnavailable):
        runner.run_round(unit)

    # the failed round never checkpointed -- state is exactly where it was,
    # ready to retry (against a fresh worker, or fall back to local
    # execution), never corrupted or silently advanced
    assert unit.round_index == 1
    assert log.read_latest() == checkpoint_after_round_0

    # bring up a FRESH worker on the same port and retry -- this is the
    # "requeues the unit" half of Section 4.2, not just "it fails safely"
    new_port_proc = CTX.Process(target=_run_worker_process, args=(port, question, question_id), daemon=True)
    new_port_proc.start()
    time.sleep(0.3)
    try:
        runner.run_round(unit)  # exploration -- succeeds against the new worker
        assert unit.round_index == 2
    finally:
        new_port_proc.terminate()
        new_port_proc.join(timeout=2)


def test_worker_unavailable_when_nothing_is_listening(tmp_path):
    handler = remote_round_handler("http://127.0.0.1:1", {"question": "x", "question_id": "y"},
                                    timeout_seconds=2.0)
    with pytest.raises(WorkerUnavailable):
        handler({}, 0)


def test_worker_reports_handler_error_as_worker_unavailable(tmp_path, worker):
    port, proc, (question, question_id) = worker
    # a malformed unit_spec the handler_factory can't use -- the worker
    # catches this and reports it as a real 500, not a crash
    handler = remote_round_handler(f"http://127.0.0.1:{port}", {"not_a_question": True})
    with pytest.raises(WorkerUnavailable):
        handler({}, 0)
