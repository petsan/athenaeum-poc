"""Batch 8, Phase AG: /api/health says whether work is moving -- the
worker's state, rounds run, time since the last round, queue length --
and answers even while a round holds the lock."""
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


def call(url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json"})
    start = time.time()
    with urllib.request.urlopen(req, timeout=30) as r:
        return time.time() - start, json.loads(r.read())


def test_health_before_any_background_work(base):
    _, h = call(f"{base}/api/health")
    assert h["status"] == "ok" and h["queued_units"] == 0
    assert h["worker"] == {"started": False, "alive": False, "rounds_run": 0, "seconds_since_last_round": None}


def test_health_during_and_after_background_work(base, held_model):
    entered, release = held_model
    call(f"{base}/api/questions", {"question": "what force holds the moon in orbit?", "async": True})
    assert entered.wait(timeout=10)            # a round is in progress, holding the lock
    elapsed, during = call(f"{base}/api/health")
    assert elapsed < 1.0
    assert during["worker"]["started"] and during["worker"]["alive"] and during["queued_units"] >= 1
    rounds_during = during["worker"]["rounds_run"]

    release.set()
    deadline = time.time() + 20
    while True:
        _, h = call(f"{base}/api/health")
        if h["queued_units"] == 0 and h["worker"]["rounds_run"] > rounds_during:
            break
        assert time.time() < deadline, h
        time.sleep(0.05)
    assert h["worker"]["alive"] and 0 <= h["worker"]["seconds_since_last_round"] < 10
