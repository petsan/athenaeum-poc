"""
Minimal HTTP API + static client host, stdlib-only (no new dependencies --
matches tech-stack.md's dependency-light storage philosophy).

Exposes the existing deliberation engine (athenaeum_brain.loop) and
Question Ledger over HTTP, and serves the mobile client from ../client/
on the same origin, so a single process + a single forwarded port is all
that's needed to access this from a phone on the same network or via a
tunnel/reverse proxy.

Deliberately synchronous per request: the toy deliberation loop finishes
in milliseconds. A real deployment with LLM-backed agents (Section 4.5)
would need this to become async (submit -> poll), matching the Question
Ledger's queued/active/completed lifecycle already modeled in ledger.py --
flagged here as a known limitation, not hidden.
"""
from __future__ import annotations
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .storage.content_addressed import ContentAddressedStore
from .storage.checkpoint import CheckpointLog
from .scheduler.runner import SingleUnitRunner
from .ledger import QuestionLedger
from .schemas import QuestionLedgerEntry
from .resource_monitor import ResourceMonitor
from .reputability_store import ReputabilityStore

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from athenaeum_brain.loop import make_deliberation_unit  # noqa: E402
from athenaeum_brain.reopening import rate_and_store_importance  # noqa: E402

CLIENT_DIR = Path(__file__).resolve().parents[2] / "client"


def build_app(data_dir: Path):
    cas = ContentAddressedStore(data_dir / "cas")
    log = CheckpointLog(cas=cas, index_path=data_dir / "index.txt")
    ledger = QuestionLedger(log)
    monitor = ResourceMonitor()
    rep_log = CheckpointLog(cas=cas, index_path=data_dir / "reputability-index.txt")
    reputability = ReputabilityStore(rep_log)
    lock = threading.Lock()

    def submit_question(question: str) -> dict:
        with lock:
            qid = f"q-{len(ledger._state()['questions']) + 1}"
            ledger.submit(QuestionLedgerEntry(id=qid, importance=0.5))
            unit_log = CheckpointLog(cas=cas, index_path=data_dir / f"unit-{qid}.txt")
            runner = SingleUnitRunner(unit_log, shared_state={})
            unit = make_deliberation_unit(question, qid, reputability=reputability)
            while unit.status != "completed":
                runner.run_round(unit)
            answer = unit_log.read_latest()["shared_state"]["answer"]
            ledger.append_version(qid, answer)
            # Section 7.1: replace the 0.5 placeholder with a computed rating.
            importance = rate_and_store_importance(ledger, qid)["importance"]
            return {"id": qid, "question": question, "answer": answer, "importance": importance}

    def list_questions() -> list:
        with lock:
            return list(ledger._state()["questions"].values())

    def get_question(qid: str):
        with lock:
            entry = ledger.get(qid)
            return entry.to_dict() if entry else None

    def health() -> dict:
        s = monitor.get_state()
        return {"status": "ok", "cores_available": s.cores_available,
                "dram_headroom_gb": s.dram_headroom_gb}

    return submit_question, list_questions, get_question, health


class Handler(BaseHTTPRequestHandler):
    submit_question = list_questions = get_question = health = None  # set by make_handler

    def _json(self, code: int, payload) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _static(self) -> None:
        path = urlparse(self.path).path
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        f = CLIENT_DIR / rel
        if not f.exists() or not f.is_file():
            self._json(404, {"error": "not found"})
            return
        ctype = "text/html" if f.suffix == ".html" else "application/octet-stream"
        body = f.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            self._json(200, self.health())
        elif path == "/api/questions":
            self._json(200, self.list_questions())
        elif path.startswith("/api/questions/"):
            qid = path.rsplit("/", 1)[-1]
            result = self.get_question(qid)
            self._json(200 if result else 404, result or {"error": "not found"})
        else:
            self._static()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/questions":
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                question = body["question"]
            except Exception:
                self._json(400, {"error": "expected JSON body: {\"question\": \"...\"}"})
                return
            self._json(200, self.submit_question(question))
        else:
            self._json(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        pass  # quiet by default; remove to debug


def make_handler(data_dir: Path):
    submit, listq, getq, health = build_app(data_dir)

    class BoundHandler(Handler):
        pass
    BoundHandler.submit_question = staticmethod(submit)
    BoundHandler.list_questions = staticmethod(listq)
    BoundHandler.get_question = staticmethod(getq)
    BoundHandler.health = staticmethod(health)
    return BoundHandler


def serve(host="0.0.0.0", port=8080, data_dir: Path = Path("data/api-run")):
    data_dir.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((host, port), make_handler(data_dir))
    print(f"Athenaeum API + mobile client on http://{host}:{port}  "
          f"(open on your phone via LAN IP or a tunnel to this port)")
    server.serve_forever()


if __name__ == "__main__":
    serve()
