"""Spins up the real ThreadingHTTPServer on a random port and hits it
with real HTTP requests -- not mocked, the actual server."""
import json, threading, time, urllib.request, urllib.error
from http.server import ThreadingHTTPServer
from athenaeum_body.api import make_handler

def start_server(tmp_path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(tmp_path / "data"))
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.05)
    return server, f"http://127.0.0.1:{port}"

def get(url):
    with urllib.request.urlopen(url) as r:
        return json.loads(r.read())

def post(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                  headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def test_health_endpoint(tmp_path):
    server, base = start_server(tmp_path)
    try:
        h = get(base + "/api/health")
        assert h["status"] == "ok"
    finally:
        server.shutdown()

def test_submit_and_get_question(tmp_path):
    server, base = start_server(tmp_path)
    try:
        result = post(base + "/api/questions", {"question": "is 17 prime?"})
        assert any("17 is prime" in c["statement"] for c in result["answer"]["committed"])

        listed = get(base + "/api/questions")
        assert len(listed) == 1

        fetched = get(base + f"/api/questions/{result['id']}")
        assert fetched["id"] == result["id"]
        assert len(fetched["versions"]) == 1
    finally:
        server.shutdown()

def test_conflicting_question_returns_plural_answer(tmp_path):
    server, base = start_server(tmp_path)
    try:
        result = post(base + "/api/questions", {"question": "how should we round 2.5?"})
        assert len(result["answer"]["plural_answers"]) == 1
    finally:
        server.shutdown()

def test_bad_request_body_returns_400(tmp_path):
    server, base = start_server(tmp_path)
    try:
        req = urllib.request.Request(base + "/api/questions", data=b"not json",
                                      headers={"Content-Type": "application/json"}, method="POST")
        try:
            urllib.request.urlopen(req)
            assert False, "expected HTTPError"
        except urllib.error.HTTPError as e:
            assert e.code == 400
    finally:
        server.shutdown()

def test_static_client_served(tmp_path):
    server, base = start_server(tmp_path)
    try:
        with urllib.request.urlopen(base + "/") as r:
            body = r.read().decode()
            assert "Athenaeum" in body
    finally:
        server.shutdown()
