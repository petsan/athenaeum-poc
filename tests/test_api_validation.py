"""Batch 6, Phase AA: every request gets a JSON answer, bad input is
refused before anything is written, and a failed synchronous deliberation
is suspended visibly (known-bugs #33). Requests are sent as raw bytes
where a well-behaved client would refuse to send them."""
import json
import socket
import threading
from http.server import ThreadingHTTPServer
import pytest
from athenaeum_body import api
from athenaeum_body.api import make_handler, MAX_BODY_BYTES, MAX_QUESTION_CHARS
from athenaeum_brain import model_backed_reasoning


@pytest.fixture(autouse=True)
def _no_model_fallback(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)


@pytest.fixture
def server(tmp_path):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(tmp_path / "data"))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()


def raw(srv, method, path, body=b"", headers=None, timeout=10):
    headers = {"Content-Length": str(len(body)), **(headers or {})}
    head = f"{method} {path} HTTP/1.1\r\nHost: x\r\nConnection: close\r\n" + \
        "".join(f"{k}: {v}\r\n" for k, v in headers.items()) + "\r\n"
    with socket.create_connection(srv.server_address, timeout=timeout) as s:
        s.sendall(head.encode() + body)
        data = b""
        while chunk := s.recv(65536):
            data += chunk
    status_line, _, rest = data.partition(b"\r\n")
    assert status_line, "connection closed without a response"
    return int(status_line.split()[1]), json.loads(rest.partition(b"\r\n\r\n")[2])


def post(srv, payload, **kw):
    return raw(srv, "POST", "/api/questions", json.dumps(payload).encode(), **kw)


def ledger(srv):
    return raw(srv, "GET", "/api/questions")[1]


@pytest.mark.parametrize("payload, message", [
    ({"question": 5}, "question must be a string, not int"),
    ({"question": ["is 17 prime?"]}, "question must be a string, not list"),
    ({"question": None}, "question must be a string, not NoneType"),
    ({"question": ""}, "question is empty"),
    ({"question": " \n\t "}, "question is empty"),
    ({"question": "x" * (MAX_QUESTION_CHARS + 1)}, f"the limit is {MAX_QUESTION_CHARS}"),
    ({"q": "is 17 prime?"}, "expected JSON body"),
    ([1, 2], "expected JSON body"),
    ({"question": 5, "async": True}, "question must be a string"),
])
def test_bad_questions_are_refused_and_nothing_is_recorded(server, payload, message):
    status, body = post(server, payload)
    assert status == 400 and message in body["error"]
    assert ledger(server) == []


def test_malformed_bodies_get_a_json_error(server):
    assert raw(server, "POST", "/api/questions", b"{not json")[0] == 400
    status, body = raw(server, "POST", "/api/questions", b"{}", headers={"Content-Length": "abc"})
    assert status == 400 and body["error"] == "invalid Content-Length"
    assert raw(server, "POST", "/api/questions", b"{}", headers={"Content-Length": "-5"})[0] == 400
    assert ledger(server) == []


def test_an_oversized_body_is_refused_without_being_read(server):
    # the header promises far more than is ever sent: a server that tried to
    # read it would hang until the timeout instead of answering at once
    status, body = raw(server, "POST", "/api/questions", b"{}",
                       headers={"Content-Length": str(MAX_BODY_BYTES + 1)}, timeout=5)
    assert status == 413 and str(MAX_BODY_BYTES) in body["error"]


def test_a_question_at_the_limit_is_accepted_and_stored_trimmed(server):
    status, body = post(server, {"question": "  is 17 prime?  "})
    assert status == 200 and body["question"] == "is 17 prime?"
    status, body = post(server, {"question": "is 17 prime? " + "x" * (MAX_QUESTION_CHARS - 13)})
    assert status == 200


def test_a_failed_synchronous_deliberation_is_suspended_not_left_queued(server, monkeypatch):
    real = api.make_deliberation_unit

    def broken(question, qid, **kw):
        unit = real(question, qid, **kw)
        def handler(state, round_index):
            raise RuntimeError("backend exploded")
        unit.round_handler = handler
        return unit
    monkeypatch.setattr(api, "make_deliberation_unit", broken)
    status, body = post(server, {"question": "is 17 prime?"})
    assert status == 500 and body["id"] == "q-1" and "backend exploded" in body["error"]
    (q,) = ledger(server)
    assert q["status"] == "suspended" and "backend exploded" in q["error"] and q["question"] == "is 17 prime?"
    assert raw(server, "GET", "/api/maintenance")[1]["failed_units"] == ["q-1"]

    monkeypatch.setattr(api, "make_deliberation_unit", real)   # and the server carries on
    status, body = post(server, {"question": "is 19 prime?"})
    assert status == 200 and body["id"] == "q-2"


def test_an_unexpected_error_is_a_json_500_not_a_dropped_connection(server, monkeypatch):
    def explode():
        raise RuntimeError("store unreadable")
    monkeypatch.setattr(server.RequestHandlerClass, "health", staticmethod(explode))
    status, body = raw(server, "GET", "/api/health")
    assert status == 500 and body == {"error": "internal error: RuntimeError"}
