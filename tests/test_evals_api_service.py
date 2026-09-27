"""Batch 12, phase AY: the API service-level suite, against a real HTTP
server. The full burst (every golden question) runs in the nightly; these
tests use a few questions, and check the gates on constructed timings."""
import pytest

pytest.importorskip("evalcore")

from evalcore import Config, compute_gates                      # noqa: E402
from evalcore.records import Recorder                           # noqa: E402

from athenaeum_brain import maintenance, model_backed_reasoning  # noqa: E402
from athenaeum_evals import api_service                         # noqa: E402

QUESTIONS = ["is 17 prime?", "how should we round 2.5?", "did the moon landing happen before the fall of the Berlin Wall?"]


@pytest.fixture(autouse=True)
def _deterministic(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)


def gates_for(results, metrics):
    rec = Recorder()
    rec.extend(results)
    for name, m in metrics.items():
        rec.set_metric(api_service.KEY, name, m)
    return {g.name: g for g in compute_gates(rec, [api_service.SUITE])}


def test_a_real_server_answers_a_burst():
    results = api_service.evaluate(QUESTIONS, timeout=120)
    assert len(results) == 3 and not any(r.hard_violations for r in results)
    m = api_service.metrics()
    assert m["worker_moving"].value == 1.0
    assert m["submit_p95_s"].n == 3 and m["submit_p95_s"].value < 1.0
    g = gates_for(results, m)
    assert g["submit_p95_s"].status == "INSUFFICIENT_DATA"        # 3 requests is not evidence of a p95
    assert g["worker_moving"].status == "PASS" and g["hard_violations"].status == "PASS"


def test_a_question_that_never_finishes_is_a_hard_violation(monkeypatch):
    monkeypatch.setattr(maintenance.Maintainer, "tick", lambda self: None)     # the worker does nothing
    results = api_service.evaluate(QUESTIONS[:1], timeout=2)
    assert results[0].hard_violations == ["never answered within 2s"]
    assert api_service.metrics()["worker_moving"].value == 0.0


def test_error_responses_are_a_hard_violation():
    from athenaeum_body.api import make_handler

    def failing(data_dir):
        handler = make_handler(data_dir)

        class Failing(handler):
            def do_POST(self):
                self._json(500, {"error": "boom"})
        return Failing
    results = api_service.evaluate(QUESTIONS[:2], timeout=2, handler_factory=failing)
    problem = next(r for r in results if r.case_id == "requests")
    assert any("HTTP Error 500" in v for v in problem.hard_violations)


def fake_run(latency, n=40, answer=5.0, moving=True):
    return {"timings": {"submit": [latency] * n, "poll": [latency] * n, "read": [latency] * n,
                        "answer": [answer] * n},
            "health": [{"queued": 3, "alive": True, "rounds": 1}, {"queued": 1, "alive": True,
                                                                     "rounds": 5 if moving else 1}]}


@pytest.mark.parametrize("latency, answer, moving, failing", [
    (0.01, 5.0, True, set()),
    (0.9, 5.0, True, {"submit_p95_s", "poll_p95_s", "read_p95_s"}),
    (0.01, 500.0, True, {"answer_p95_s"}),
    (0.01, 5.0, False, {"worker_moving"}),
])
def test_the_gates(latency, answer, moving, failing):
    g = gates_for([], api_service.metrics(Config(), fake_run(latency, answer=answer, moving=moving)))
    assert {k for k, v in g.items() if v.status == "FAIL"} == failing


def test_one_slow_request_in_forty_moves_the_pessimistic_p95():
    run = fake_run(0.01)
    run["timings"]["submit"][0] = run["timings"]["submit"][1] = 5.0
    m = api_service.metrics(Config(), run)["submit_p95_s"]
    assert m.ci_high == pytest.approx(5.0) and m.value < 5.0          # the gate reads ci_high
