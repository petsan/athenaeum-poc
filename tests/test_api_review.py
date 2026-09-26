"""Batch 5, Phase Z: human checkpoints are visible over the API (read-only),
and the static file server no longer serves files outside client/
(known-bugs #32)."""
import json
import socket
import threading
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
import pytest
from athenaeum_body.api import make_handler, build_app
from athenaeum_brain import model_backed_reasoning
from athenaeum_brain.idle_evolution import amendment_checkpoint_key


@pytest.fixture(autouse=True)
def _no_model_fallback(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)


@pytest.fixture
def server(tmp_path):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(tmp_path / "data"))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


def raw_get(srv, path):
    """A request line sent as-is: no client-side path normalization."""
    with socket.create_connection(srv.server_address) as s:
        s.sendall(f"GET {path} HTTP/1.0\r\n\r\n".encode())
        data = b""
        while chunk := s.recv(65536):
            data += chunk
    head, _, body = data.partition(b"\r\n\r\n")
    return int(head.split()[1]), body


def test_checkpoints_are_listed_pending_first_with_the_amendment_proposal(tmp_path):
    app = build_app(tmp_path)
    m, cps = app.maintainer, app.maintainer.idle.checkpoints
    proposal = {"params": {"rejected_min_challenges": 3, "foundational_min_corroborations": 6},
                "rationale": "foundational bar looks too low", "evidence": ["Mathematics::17 is prime"]}
    m.pending_amendments["idle-4"] = proposal
    cps.set_pending(amendment_checkpoint_key("idle-4"), reason=proposal["rationale"],
                    triggering_claim_id="Mathematics::17 is prime", submitter_id="idle-evolution")
    cps.set_pending("q-9", reason="human input on a high-importance question", triggering_claim_id="c1",
                    submitter_id="alice")
    cps.set_pending("domain-fidelity:Physics", reason="drifting", triggering_claim_id="c2", submitter_id="x")
    cps.approve("domain-fidelity:Physics", reviewer_id="rev-2")

    listed = app.checkpoints()
    assert [(c["key"], c["kind"], c["ref"], c["status"]) for c in listed] == [
        ("q-9", "question", "q-9", "pending_human_checkpoint"),
        ("standard-amendment:idle-4", "standard-amendment", "idle-4", "pending_human_checkpoint"),
        ("domain-fidelity:Physics", "domain-fidelity", "Physics", "current"),
    ]
    assert listed[1]["proposal"] == proposal and "proposal" not in listed[0]
    assert listed[2]["reviewer_id"] == "rev-2" and listed[0]["submitter_id"] == "alice"


def test_checkpoints_over_http_are_read_only(server):
    base = f"http://127.0.0.1:{server.server_address[1]}"
    with urllib.request.urlopen(f"{base}/api/checkpoints") as r:
        assert r.status == 200 and json.loads(r.read()) == []
    req = urllib.request.Request(f"{base}/api/checkpoints", data=b"{}", method="POST",
                                 headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 404  # no approval route, by design (owner decision 7)


# --- known-bugs #32 --------------------------------------------------------------

@pytest.mark.parametrize("path", ["/../pyproject.toml", "/../src/athenaeum_body/api.py",
                                  "/../../../../../../etc/hostname", "/%2e%2e/pyproject.toml",
                                  "/..%2fpyproject.toml", "/client/../../pyproject.toml"])
def test_static_files_never_escape_the_client_directory(server, path):
    status, body = raw_get(server, path)
    assert status == 404 and b"[project]" not in body and b"import" not in body


def test_the_client_is_still_served(server):
    for path in ("/", "/index.html", "/standalone-demo.html"):
        status, body = raw_get(server, path)
        assert status == 200 and b"<title>Athenaeum" in body
