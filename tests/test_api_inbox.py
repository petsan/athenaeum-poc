"""Batch 9, Phase AJ: an async submission never waits behind a round. It is
recorded durably in an inbox and answered at once, the worker registers it
before its next round, and a restart drains what a dead process accepted."""
import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
import pytest
from athenaeum_body import api
from athenaeum_body.api import build_app
from athenaeum_brain import model_backed_reasoning


@pytest.fixture(autouse=True)
def _no_model_fallback(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)


def serve(app):
    """An HTTP server over an app we keep a handle on."""
    class Handler(api.Handler):
        pass
    submit, listq, getq, health = app
    for name, fn in [("submit_question", submit), ("list_questions", listq), ("get_question", getq),
                     ("health", health), ("submit_async", app.submit_async), ("get_version", app.get_version),
                     ("maintenance_status", app.maintenance_status), ("checkpoints", app.checkpoints)]:
        setattr(Handler, name, staticmethod(fn))
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def call(url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json"})
    start = time.time()
    with urllib.request.urlopen(req, timeout=30) as r:
        return time.time() - start, r.status, json.loads(r.read())


def wait_all_completed(base, n, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        _, _, summary = call(f"{base}/api/questions?view=summary")
        if len(summary) == n and all(q["status"] == "completed" for q in summary):
            return summary
        time.sleep(0.05)
    raise AssertionError(summary)


def test_async_submits_answer_at_once_while_a_round_holds_the_lock(tmp_path):
    app = build_app(tmp_path)
    server, base = serve(app)
    try:
        with app.lock:                               # a round in progress, as long as it takes
            results = [call(f"{base}/api/questions", {"question": q, "async": True})
                       for q in ("is 17 prime?", "is 19 prime?", "is 21 prime?")]
            assert all(elapsed < 1.0 and status == 202 for elapsed, status, _ in results)
            assert [body["id"] for _, _, body in results] == ["q-1", "q-2", "q-3"]
            elapsed, _, summary = call(f"{base}/api/questions?view=summary")
            assert elapsed < 1.0
            assert [(q["id"], q["status"], q["question"]) for q in summary] == [
                ("q-1", "queued", "is 17 prime?"), ("q-2", "queued", "is 19 prime?"), ("q-3", "queued", "is 21 prime?")]
        summary = wait_all_completed(base, 3)       # the worker drains the inbox once the round ends
        assert [q["id"] for q in summary] == ["q-1", "q-2", "q-3"]
    finally:
        server.shutdown()


def test_a_restart_drains_what_a_dead_process_accepted(tmp_path):
    first = build_app(tmp_path)
    first.lock.acquire()                              # its worker never gets to drain -- then it "dies"
    first.submit_async("is 23 prime?")
    first.submit_async("is 25 prime?")

    second = build_app(tmp_path)                      # a new process over the same data: drains at startup
    assert second.worker_thread and second.worker_thread[0].is_alive()   # and starts working on it
    _, list_questions, get_question, _ = second
    deadline = time.time() + 20
    while not all(q["status"] == "completed" for q in list_questions("summary")):
        assert time.time() < deadline
        time.sleep(0.05)
    assert [(q["id"], q["status"]) for q in list_questions("summary")] == [("q-1", "completed"), ("q-2", "completed")]
    assert get_question("q-2")["versions"][0]["committed"][0]["statement"] == "25 is not prime"
    # ...and the dead process's ids are never issued again
    assert second.submit_async("is 29 prime?")["id"] == "q-3"


def test_ids_stay_unique_across_both_paths_under_concurrency(tmp_path):
    app = build_app(tmp_path)
    ids, errors = [], []

    def ask(i):
        try:
            if i % 3 == 0:
                ids.append(app[0](f"is {101 + 2 * i} prime?")["id"])
            else:
                ids.append(app.submit_async(f"is {101 + 2 * i} prime?")["id"])
        except Exception as e:
            errors.append(e)
    threads = [threading.Thread(target=ask, args=(i,)) for i in range(15)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert errors == [] and len(ids) == 15 and len(set(ids)) == 15
    deadline = time.time() + 30
    while True:
        listed = app[1]("summary")
        if len(listed) == 15 and all(q["status"] == "completed" for q in listed):
            break
        assert time.time() < deadline, listed
        time.sleep(0.05)
    assert sorted(q["id"] for q in listed) == sorted(ids)


def test_an_existing_data_dir_without_an_inbox_continues_its_numbering(tmp_path):
    app = build_app(tmp_path)
    app[0]("is 17 prime?")
    app[0]("is 19 prime?")
    (tmp_path / "inbox.txt").unlink()                 # as if written before Phase AJ
    again = build_app(tmp_path)
    assert again.submit_async("is 23 prime?")["id"] == "q-3"
