"""
Minimal HTTP API + static client host, stdlib-only (no new dependencies --
matches tech-stack.md's dependency-light storage philosophy).

Exposes the existing deliberation engine (athenaeum_brain.loop) and
Question Ledger over HTTP, and serves the mobile client from ../client/
on the same origin, so a single process + a single forwarded port is all
that's needed to access this from a phone on the same network or via a
tunnel/reverse proxy.

Two ways to ask (2026-09-26, batch 2 Phase N):
- synchronous (the default, unchanged): POST /api/questions deliberates
  inside the request and returns the answer -- fine for the deterministic
  agents, which finish in milliseconds;
- asynchronous: POST /api/questions with {"async": true} returns 202 and
  the question id at once; a single background worker drives a
  `Maintainer` (athenaeum_brain.maintenance) that moves the question through
  the Question Ledger's queued -> active -> completed lifecycle, interleaved
  with idle-evolution cycles. Poll GET /api/questions/<id>. This is the
  path LLM-backed deliberations need, since they take minutes, not
  milliseconds.
Both paths share one set of stores, and every ledger access happens under
one lock, so they can't interleave writes.
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
from .consolidation_store import ConsolidationStore
from .domain_fidelity_store import DomainFidelityStore
from .human_checkpoint_store import HumanCheckpointStore
from .belief_graph_store import BeliefGraphStore
from .audit_store import AuditStore

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from athenaeum_brain.loop import make_deliberation_unit  # noqa: E402
from athenaeum_brain.reopening import rate_and_store_importance  # noqa: E402
from athenaeum_brain.verification_routing import sandbox_enabled  # noqa: E402
from athenaeum_brain.idle_evolution import IdleContext  # noqa: E402
from athenaeum_brain.maintenance import Maintainer  # noqa: E402

CLIENT_DIR = Path(__file__).resolve().parents[2] / "client"


class App(tuple):
    """(submit_question, list_questions, get_question, health) -- the shape
    callers have always unpacked -- plus the async path as attributes:
    submit_async, get_version, maintenance_status, and the worker thread."""


def build_app(data_dir: Path) -> App:
    cas = ContentAddressedStore(data_dir / "cas")
    log_for = lambda name: CheckpointLog(cas=cas, index_path=data_dir / f"{name}.txt")
    log = CheckpointLog(cas=cas, index_path=data_dir / "index.txt")
    ledger = QuestionLedger(log)
    monitor = ResourceMonitor()
    reputability = ReputabilityStore(log_for("reputability-index"))
    graph = BeliefGraphStore(log_for("belief-graph"))
    # Task 44 routing follows config's execution_sandbox.enabled (false by
    # default and by hard constraint until the sandbox review passes).
    verification = {"enabled": sandbox_enabled()}
    lock = threading.Lock()
    maintainer = Maintainer(
        idle=IdleContext(ledger=ledger, reputability=reputability,
                         consolidation=ConsolidationStore(log_for("consolidation"),
                                                          ContentAddressedStore(data_dir / "archive")),
                         fidelity=DomainFidelityStore(log_for("fidelity")),
                         checkpoints=HumanCheckpointStore(log_for("checkpoints"))),
        log_for=log_for, belief_graph=graph, audits=AuditStore(log_for("audits")),
        verification=verification)
    work_available = threading.Event()

    def _new_id() -> str:
        return f"q-{len(ledger._state()['questions']) + 1}"

    def submit_question(question: str) -> dict:
        with lock:
            qid = _new_id()
            ledger.submit(QuestionLedgerEntry(id=qid, importance=0.5))
            unit_log = CheckpointLog(cas=cas, index_path=data_dir / f"unit-{qid}.txt")
            runner = SingleUnitRunner(unit_log, shared_state={})
            unit = make_deliberation_unit(question, qid, reputability=reputability,
                                          verification=verification, belief_graph=graph)
            while unit.status != "completed":
                runner.run_round(unit)
            answer = unit_log.read_latest()["shared_state"]["answer"]
            ledger.append_version(qid, answer)
            # Section 7.1: replace the 0.5 placeholder with a computed rating.
            importance = rate_and_store_importance(ledger, qid, graph=graph)["importance"]
            return {"id": qid, "question": question, "answer": answer, "importance": importance}

    worker_thread: list[threading.Thread] = []

    def submit_async(question: str) -> dict:
        with lock:
            qid = _new_id()
            maintainer.submit_question(qid, question)
            # Started on first use, so a purely synchronous user never gets
            # background idle cycles running over their questions.
            if not worker_thread:
                worker_thread.append(threading.Thread(target=worker, name="athenaeum-maintainer", daemon=True))
                worker_thread[0].start()
        work_available.set()
        return {"id": qid, "question": question, "status": "queued"}

    def worker() -> None:
        """One thread drives the Maintainer, one round at a time, taking the
        lock per round so synchronous requests and reads interleave."""
        while True:
            with lock:
                try:
                    maintainer.tick()
                except Exception as e:  # never let one bad round kill the worker silently
                    maintainer.events.append({"kind": "error", "error": repr(e)})
                busy = bool(maintainer.scheduler._heap)
            if not busy:
                work_available.wait(timeout=1.0)
                work_available.clear()

    def get_version(qid: str, n: int):
        with lock:
            entry = ledger.get(qid)
            if entry is None or not 0 <= n < len(entry.versions):
                return None
            return entry.versions[n]

    def maintenance_status() -> dict:
        with lock:
            return {"idle_cycles": maintainer.cycles, "queued_units": len(maintainer.scheduler._heap),
                    "pending_amendments": sorted(maintainer.pending_amendments),
                    "recent_events": maintainer.events[-10:]}

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

    app = App((submit_question, list_questions, get_question, health))
    app.submit_async, app.get_version, app.maintenance_status = submit_async, get_version, maintenance_status
    app.maintainer, app.worker_thread = maintainer, worker_thread
    return app


class Handler(BaseHTTPRequestHandler):
    submit_question = list_questions = get_question = health = None  # set by make_handler
    submit_async = get_version = maintenance_status = None

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
        elif path == "/api/maintenance":
            self._json(200, self.maintenance_status())
        elif path.startswith("/api/questions/"):
            parts = path[len("/api/questions/"):].split("/")
            if len(parts) == 3 and parts[1] == "versions" and parts[2].isdigit():
                result = self.get_version(parts[0], int(parts[2]))
            elif len(parts) == 1:
                result = self.get_question(parts[0])
            else:
                result = None
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
            if body.get("async") is True:
                self._json(202, self.submit_async(question))
            else:
                self._json(200, self.submit_question(question))
        else:
            self._json(404, {"error": "not found"})

    def log_message(self, fmt, *args):
        pass  # quiet by default; remove to debug


def make_handler(data_dir: Path):
    app = build_app(data_dir)
    submit, listq, getq, health = app

    class BoundHandler(Handler):
        pass
    BoundHandler.submit_question = staticmethod(submit)
    BoundHandler.list_questions = staticmethod(listq)
    BoundHandler.get_question = staticmethod(getq)
    BoundHandler.health = staticmethod(health)
    BoundHandler.submit_async = staticmethod(app.submit_async)
    BoundHandler.get_version = staticmethod(app.get_version)
    BoundHandler.maintenance_status = staticmethod(app.maintenance_status)
    return BoundHandler


def serve(host="0.0.0.0", port=8080, data_dir: Path = Path("data/api-run")):
    data_dir.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((host, port), make_handler(data_dir))
    print(f"Athenaeum API + mobile client on http://{host}:{port}  "
          f"(open on your phone via LAN IP or a tunnel to this port)")
    server.serve_forever()


if __name__ == "__main__":
    serve()
