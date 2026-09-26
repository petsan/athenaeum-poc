"""Owner decision 7 (batch 10, Phase AP): per-reviewer tokens on the API's
write endpoints -- clearing a human checkpoint, and submitting ingestion
from allow-listed hosts only (redirects included)."""
import http.server
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
import pytest
from athenaeum_body import api
from athenaeum_body.api import build_app
from athenaeum_body.reviewers import add_reviewer, Reviewers
from athenaeum_brain import model_backed_reasoning
from athenaeum_brain.idle_evolution import amendment_checkpoint_key


@pytest.fixture(autouse=True)
def _no_model(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)


def serve(app):
    class Handler(api.Handler):
        pass
    submit, listq, getq, health = app
    for name, fn in [("submit_question", submit), ("list_questions", listq), ("get_question", getq),
                     ("health", health), ("submit_async", app.submit_async), ("get_version", app.get_version),
                     ("maintenance_status", app.maintenance_status), ("checkpoints", app.checkpoints),
                     ("decide_checkpoint", app.decide_checkpoint), ("submit_ingestion", app.submit_ingestion)]:
        setattr(Handler, name, staticmethod(fn))
    Handler.reviewers = app.reviewers
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def call(url, payload=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read()), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read()), dict(e.headers)


@pytest.fixture
def world(tmp_path):
    app = build_app(tmp_path)
    server, base = serve(app)
    tokens = {}

    def reviewer(rid, role, hosts=()):
        tokens[rid] = add_reviewer(tmp_path / "reviewers.json", rid, role, hosts)
        return tokens[rid]
    yield {"app": app, "base": base, "tmp": tmp_path, "reviewer": reviewer, "tokens": tokens}
    server.shutdown()


def pending(app, key, submitter="idle-evolution"):
    app.maintainer.idle.checkpoints.set_pending(key, reason="r", triggering_claim_id="c1", submitter_id=submitter)


# --- refusals --------------------------------------------------------------------

def test_with_no_reviewers_configured_writes_are_disabled_and_reads_still_work(world):
    base = world["base"]
    assert call(f"{base}/api/checkpoints/q-1/decision", {"decision": "approve"}, token="x")[0] == 503
    assert call(f"{base}/api/ingestion", {"sources": []}, token="x")[0] == 503
    assert call(f"{base}/api/checkpoints")[0] == 200


def test_missing_wrong_and_underprivileged_tokens_are_refused(world):
    base, reviewer = world["base"], world["reviewer"]
    reviewer("rita", "reviewer")
    member = reviewer("mo", "member")
    pending(world["app"], "q-9")
    status, body, headers = call(f"{base}/api/checkpoints/q-9/decision", {"decision": "approve"})
    assert status == 401 and headers.get("WWW-Authenticate") == "Bearer"
    assert call(f"{base}/api/checkpoints/q-9/decision", {"decision": "approve"}, token="not-a-token")[0] == 401
    assert call(f"{base}/api/checkpoints/q-9/decision", {"decision": "approve"}, token=member)[0] == 403
    assert call(f"{base}/api/ingestion", {"sources": [{"url": "https://a.org/x", "license": "cc-by"}]},
                token=member)[0] == 403
    assert world["app"].maintainer.idle.checkpoints.get("q-9")["status"] == "pending_human_checkpoint"


# --- clearing checkpoints -----------------------------------------------------------

def test_a_reviewer_approves_and_the_identity_comes_from_the_token(world):
    base, app = world["base"], world["app"]
    token = world["reviewer"]("rita", "reviewer")
    key = amendment_checkpoint_key("idle-3")                       # has a colon: sent percent-encoded
    pending(app, key)
    status, body, _ = call(f"{base}/api/checkpoints/standard-amendment%3Aidle-3/decision",
                           {"decision": "approve", "reviewer_id": "mallory"}, token=token)
    assert status == 200 and body["key"] == key and body["status"] == "current"
    assert app.maintainer.idle.checkpoints.get(key)["reviewer_id"] == "rita"   # not what the body claimed
    listed = {c["key"]: c for c in call(f"{base}/api/checkpoints")[1]}
    assert listed[key]["status"] == "current"


def test_the_submitter_cannot_clear_their_own_checkpoint(world):
    token = world["reviewer"]("rita", "reviewer")
    pending(world["app"], "q-2", submitter="rita")
    status, body, _ = call(f"{world['base']}/api/checkpoints/q-2/decision", {"decision": "approve"}, token=token)
    assert status == 409 and "must not be the submitter" in body["error"]


@pytest.mark.parametrize("payload, status, message", [
    ({"decision": "reject_with_note"}, 400, "requires a note"),
    ({"decision": "overrule"}, 400, "decision must be one of"),
    ({"decision": "approve", "note": 5}, 400, "note must be a string"),
])
def test_bad_decisions_are_refused(world, payload, status, message):
    token = world["reviewer"]("rita", "reviewer")
    pending(world["app"], "q-3")
    got, body, _ = call(f"{world['base']}/api/checkpoints/q-3/decision", payload, token=token)
    assert got == status and message in body["error"]


def test_an_unknown_checkpoint_is_404_and_a_rejection_keeps_it_pending(world):
    token = world["reviewer"]("rita", "reviewer")
    assert call(f"{world['base']}/api/checkpoints/q-404/decision", {"decision": "approve"}, token=token)[0] == 404
    pending(world["app"], "q-4")
    status, body, _ = call(f"{world['base']}/api/checkpoints/q-4/decision",
                           {"decision": "reject_with_note", "note": "needs a source"}, token=token)
    assert status == 200 and body["status"] == "pending_human_checkpoint" and body["note"] == "needs a source"


def test_an_approved_amendment_is_adopted_by_the_next_idle_cycle(world):
    app, base = world["app"], world["base"]
    token = world["reviewer"]("rita", "reviewer")
    m = app.maintainer
    params = dict(m.idle.reputability.current_standard()["params"])
    params["foundational_min_corroborations"] += 1
    m.pending_amendments["idle-7"] = {"params": params, "rationale": "bar too low", "evidence": ["x"]}
    pending(app, amendment_checkpoint_key("idle-7"))
    assert call(f"{base}/api/checkpoints/standard-amendment%3Aidle-7/decision", {"decision": "approve"},
                token=token)[0] == 200
    m.submit_question("q-50", "is 17 prime?")
    events = m.run()
    assert any(e["kind"] == "idle" and e["amendments_adopted"] == ["idle-7"] for e in events)
    standard = m.idle.reputability.current_standard()
    assert standard["version"] == 1 and "reviewer=rita" in standard["rationale"]


# --- ingestion ------------------------------------------------------------------------

class Site:
    """A local HTTP server: `pages` path -> body, `redirects` path -> URL; counts hits."""
    def __init__(self, pages=None, redirects=None):
        self.hits = []
        site = self

        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                site.hits.append(self.path)
                if self.path in (redirects or {}):
                    self.send_response(302)
                    self.send_header("Location", redirects[self.path])
                    self.end_headers()
                elif self.path in (pages or {}):
                    body = pages[self.path].encode()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()

            def log_message(self, *a):
                pass
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()


def wait_ingestion(app, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        events = [e for e in app.maintenance_status()["recent_events"] if e["kind"] == "ingestion"]
        if events:
            return events[-1]
        time.sleep(0.05)
    raise AssertionError(app.maintenance_status())


def test_ingestion_from_an_allow_listed_host(world):
    site = Site(pages={"/paper.txt": "a paper"})
    token = world["reviewer"]("olga", "owner", hosts=["127.0.0.1"])
    status, body, _ = call(f"{world['base']}/api/ingestion",
                           {"sources": [{"url": f"http://127.0.0.1:{site.port}/paper.txt", "license": "cc-by",
                                         "cites": ["arxiv:1"]}]}, token=token)
    assert status == 200 and body["status"] == "queued" and body["batch_id"].startswith("ingest-")
    event = wait_ingestion(world["app"])
    assert event["accepted"] == [f"http://127.0.0.1:{site.port}/paper.txt"]
    graph = world["app"].maintainer.belief_graph
    assert graph.node(f"source:http://127.0.0.1:{site.port}/paper.txt").data["license"] == "cc-by"
    site.server.shutdown()


@pytest.mark.parametrize("spec, message", [
    ({"url": "https://elsewhere.example/x", "license": "cc-by"}, "not an http(s) URL on the ingestion allow-list"),
    ({"url": "file:///etc/passwd", "license": "cc-by"}, "not an http(s) URL on the ingestion allow-list"),
    ({"url": "http://127.0.0.1/x", "license": "cc-by", "content": "forged"}, "each source takes only"),
    ({"url": "http://127.0.0.1/x", "license": ""}, "needs a url and a license"),
    ({"url": "http://127.0.0.1/x", "license": "cc-by", "cites": "a"}, "cites must be a list"),
])
def test_bad_ingestion_requests_are_refused_before_anything_is_queued(world, spec, message):
    token = world["reviewer"]("rita", "reviewer", hosts=["127.0.0.1"])
    status, body, _ = call(f"{world['base']}/api/ingestion", {"sources": [spec]}, token=token)
    assert status == 400 and message in body["error"]
    assert world["app"].maintenance_status()["queued_units"] == 0


def test_a_redirect_off_the_allow_list_is_refused_without_being_followed(world):
    inside = Site(pages={"/secret": "internal only"})          # reached as 'localhost': not allow-listed
    outside = Site(redirects={"/paper.txt": f"http://localhost:{inside.port}/secret"})
    token = world["reviewer"]("rita", "reviewer", hosts=["127.0.0.1"])
    status, _, _ = call(f"{world['base']}/api/ingestion",
                        {"sources": [{"url": f"http://127.0.0.1:{outside.port}/paper.txt", "license": "cc-by"}]},
                        token=token)
    assert status == 200
    event = wait_ingestion(world["app"])
    assert event["accepted"] == []
    (reason,) = event["rejected"].values()
    assert "refused: not on the ingestion allow-list" in reason
    assert inside.hits == []                                    # the internal host was never contacted
    inside.server.shutdown(); outside.server.shutdown()


# --- the reviewers file ---------------------------------------------------------------

def test_the_file_holds_hashes_only_and_re_adding_revokes(tmp_path):
    path = tmp_path / "reviewers.json"
    first = add_reviewer(path, "rita", "reviewer", ["Example.org"])
    text = path.read_text()
    assert first not in text and "token_sha256" in text and "example.org" in text
    second = add_reviewer(path, "rita", "reviewer")
    r = Reviewers(path)
    assert r.authenticate(f"Bearer {first}") is None               # the old token no longer works
    assert r.authenticate(f"Bearer {second}").reviewer_id == "rita"
    assert r.authenticate(second) is None                          # the scheme is required
    with pytest.raises(ValueError):
        add_reviewer(path, "x", "superuser")
