"""The asynchronous API path (submit -> poll) against a real running
server, alongside the unchanged synchronous path."""
import json, threading, time, urllib.request, urllib.error
from http.server import ThreadingHTTPServer
import pytest
from athenaeum_body.api import make_handler, build_app
from athenaeum_brain import model_backed_reasoning


@pytest.fixture(autouse=True)
def _no_model_fallback(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)


@pytest.fixture
def base(tmp_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(tmp_path / "data"))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def call(url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"},
                                 method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def wait_completed(base, qid, timeout=20.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, q = call(f"{base}/api/questions/{qid}")
        if q["status"] == "completed":
            return q
        time.sleep(0.05)
    raise AssertionError(f"{qid} not completed within {timeout}s: {q}")


def test_async_submit_returns_immediately_and_completes_in_the_background(base):
    status, body = call(f"{base}/api/questions", {"question": "is 17 prime?", "async": True})
    assert status == 202 and body["status"] == "queued" and "answer" not in body
    q = wait_completed(base, body["id"])
    assert [c["statement"] for c in q["versions"][0]["committed"]] == ["17 is prime"]
    assert q["importance"] > 0


def test_versions_can_be_fetched_individually(base):
    _, body = call(f"{base}/api/questions", {"question": "how should we round 2.5?", "async": True})
    wait_completed(base, body["id"])
    status, v0 = call(f"{base}/api/questions/{body['id']}/versions/0")
    assert status == 200 and len(v0["plural_answers"]) == 1
    assert call(f"{base}/api/questions/{body['id']}/versions/5")[0] == 404
    assert call(f"{base}/api/questions/{body['id']}/nonsense/0")[0] == 404


def test_several_async_questions_each_get_their_own_answer(base):
    """The concurrency bug (known-bugs #26) through the public API."""
    ids = {q: call(f"{base}/api/questions", {"question": q, "async": True})[1]["id"]
           for q in ("is 17 prime?", "is 21 prime?", "how should we round 2.5?")}
    answers = {q: wait_completed(base, qid)["versions"][0] for q, qid in ids.items()}
    assert [c["statement"] for c in answers["is 17 prime?"]["committed"]] == ["17 is prime"]
    assert [c["statement"] for c in answers["is 21 prime?"]["committed"]] == ["21 is not prime"]
    assert answers["how should we round 2.5?"]["question"] == "how should we round 2.5?"


def test_maintenance_runs_an_idle_cycle_once_the_queue_is_quiet(base):
    _, body = call(f"{base}/api/questions", {"question": "is 17 prime?", "async": True})
    wait_completed(base, body["id"])
    deadline = time.time() + 20
    while time.time() < deadline:
        _, m = call(f"{base}/api/maintenance")
        if any(e["kind"] == "idle" for e in m["recent_events"]):
            break
        time.sleep(0.05)
    assert m["idle_cycles"] == 1 and m["queued_units"] == 0
    assert not any(e["kind"] == "error" for e in m["recent_events"])


def test_synchronous_use_never_starts_the_background_worker(tmp_path):
    app = build_app(tmp_path)
    app[0]("is 17 prime?")
    assert app.worker_thread == []


def test_question_text_is_readable_before_and_after_it_is_answered(tmp_path):
    """Batch 4, Phase V: the client lists questions still in the queue, which
    have no ledger version yet -- their text comes from the Maintainer."""
    app = build_app(tmp_path)
    app.maintainer.submit_question("q-1", "is 17 prime?")  # queued, and no worker to take it
    submit, list_questions, get_question, _ = app
    assert [(q["id"], q["status"], q["question"]) for q in list_questions()] == [("q-1", "queued", "is 17 prime?")]
    assert get_question("q-1")["question"] == "is 17 prime?"
    app.maintainer.run()
    assert get_question("q-1")["status"] == "completed" and get_question("q-1")["question"] == "is 17 prime?"
    assert submit("is 21 prime?")["id"] == "q-2" and get_question("q-2")["question"] == "is 21 prime?"
