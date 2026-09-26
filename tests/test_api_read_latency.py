"""Batch 8, Phase AF: reads never wait behind a deliberation. A model call is
held open (as a live one would be, for seconds or minutes) while the lock is
taken; every read endpoint must still answer at once, from the snapshot."""
import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
import pytest
from athenaeum_body.api import make_handler
from athenaeum_brain import model_backed_reasoning


@pytest.fixture
def held_model(monkeypatch):
    """The model call blocks until released; `entered` says one is in progress."""
    entered, release = threading.Event(), threading.Event()

    def ask_model(*a, **k):
        entered.set()
        release.wait(timeout=30)
        return "gravity holds the moon in orbit"
    monkeypatch.setattr(model_backed_reasoning, "ask_model", ask_model)
    yield entered, release
    release.set()


@pytest.fixture
def base(tmp_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(tmp_path / "data"))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def timed(url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json"})
    start = time.time()
    with urllib.request.urlopen(req, timeout=30) as r:
        return time.time() - start, json.loads(r.read())


READS = ["/api/questions", "/api/questions?view=summary", "/api/questions/q-1",
         "/api/maintenance", "/api/checkpoints", "/api/health"]


def test_reads_answer_while_an_async_round_holds_the_lock(base, held_model):
    entered, release = held_model
    timed(f"{base}/api/questions", {"question": "what force holds the moon in orbit?", "async": True})
    assert entered.wait(timeout=10)   # the worker is now inside a round, holding the lock
    for path in READS:
        elapsed, _ = timed(base + path)
        assert elapsed < 1.0, f"{path} waited {elapsed:.2f}s behind the model call"
    _, summary = timed(f"{base}/api/questions?view=summary")
    assert summary[0]["id"] == "q-1" and summary[0]["status"] in ("queued", "active")
    release.set()
    deadline = time.time() + 20
    while timed(f"{base}/api/questions/q-1")[1]["status"] != "completed":
        assert time.time() < deadline
        time.sleep(0.05)


def test_reads_answer_while_a_synchronous_deliberation_is_in_progress(base, held_model):
    entered, release = held_model
    result = {}
    t = threading.Thread(target=lambda: result.update(
        timed(f"{base}/api/questions", {"question": "what force holds the moon in orbit?"})[1]))
    t.start()
    assert entered.wait(timeout=10)
    elapsed, listed = timed(f"{base}/api/questions?view=summary")
    assert elapsed < 1.0 and listed == []   # the snapshot is from before the question began
    release.set()
    t.join(timeout=20)
    assert result["id"] == "q-1"
    _, listed = timed(f"{base}/api/questions?view=summary")
    assert [(q["id"], q["status"]) for q in listed] == [("q-1", "completed")]   # fresh once it's done
