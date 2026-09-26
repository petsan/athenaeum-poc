"""Batch 7, Phase AE: GET /api/questions?view=summary lets a poller notice
changes without downloading every answer; the default listing is unchanged."""
import json
import threading
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
import pytest
from athenaeum_body.api import make_handler
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


def get(url):
    try:
        with urllib.request.urlopen(url) as r:
            raw = r.read()
            return r.status, json.loads(raw), len(raw)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read()), 0


def post(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def test_the_summary_has_what_a_poller_needs_and_no_answers(base):
    for q in ("is 17 prime?", "how should we round 2.5?", "is 21 prime?"):
        post(f"{base}/api/questions", {"question": q})
    _, full, full_bytes = get(f"{base}/api/questions")
    status, summary, summary_bytes = get(f"{base}/api/questions?view=summary")
    assert status == 200
    assert summary == [{"id": e["id"], "status": e["status"], "question": e["question"],
                        "importance": e["importance"], "created_at": e["created_at"],
                        "versions": len(e["versions"])} for e in full]
    assert all(s["versions"] == 1 for s in summary)
    assert summary_bytes * 10 < full_bytes   # a poll no longer carries every answer


def test_the_default_listing_is_unchanged(base):
    post(f"{base}/api/questions", {"question": "is 17 prime?"})
    for url in (f"{base}/api/questions", f"{base}/api/questions?view=full"):
        _, listed, _ = get(url)
        assert listed[0]["versions"][0]["committed"][0]["statement"] == "17 is prime"


def test_an_unknown_view_is_refused(base):
    status, body, _ = get(f"{base}/api/questions?view=everything")
    assert status == 400 and "unknown view" in body["error"]
