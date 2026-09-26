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
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote
import uuid

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
from .calibration_store import CalibrationStore
from .model_fitness_store import ModelFitnessStore
from .reviewers import Reviewers, Identity, reviewers_path
from .ingestion import host_allowed

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from athenaeum_brain.loop import make_deliberation_unit  # noqa: E402
from athenaeum_brain.model_fitness import admit_model, model_standing  # noqa: E402
from athenaeum_brain.model_backed_reasoning import DEFAULT_MODEL  # noqa: E402
from athenaeum_brain.reopening import rate_and_store_importance  # noqa: E402
from athenaeum_brain.verification_routing import sandbox_enabled  # noqa: E402
from athenaeum_brain.idle_evolution import IdleContext  # noqa: E402
from athenaeum_brain.maintenance import Maintainer  # noqa: E402
from athenaeum_brain.human_input import clear_checkpoint, HumanInputError, CheckpointConflictError  # noqa: E402

CLIENT_DIR = Path(__file__).resolve().parents[2] / "client"


MAX_BODY_BYTES = 64 * 1024      # placeholder limits, generous for a question
MAX_QUESTION_CHARS = 2000

# Section 6.7's admission gate, as decided by the owner (decision 4,
# 2026-09-26). Admission grants no weight: an admitted model starts at the
# cold-start fitness of 0.5 per agent and moves only with outcomes. A model
# not listed here can still answer, but its claims weigh 0 at synthesis.
ADMITTED_MODELS = {
    DEFAULT_MODEL: ("Owner decision 4 (2026-09-26): the model every agent's fallback asks. The batch 9 live "
                    "smoke showed correct short answers once run-on output was cut (known-bugs #35)."),
}


class BadRequest(ValueError):
    pass


class ApiError(Exception):
    """A refusal with its HTTP status (the write endpoints, decision 7)."""
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


CHECKPOINT_DECISIONS = ("approve", "reject_with_note", "request_more_deliberation")
INGESTION_ROLES = ("owner", "reviewer")
INGESTION_SPEC_KEYS = {"url", "license", "cites", "is_paid_or_metered"}   # never `content`: fixtures are Python-only
MAX_INGESTION_BATCH = 50   # placeholder


class DeliberationFailed(Exception):
    def __init__(self, question_id: str, error: str):
        super().__init__(error)
        self.question_id, self.error = question_id, error


def parse_question_request(raw: bytes) -> tuple[str, bool]:
    """(question, async) from a POST /api/questions body, or BadRequest
    saying exactly what is wrong. The question is stripped of surrounding
    whitespace and must be a non-empty string of at most MAX_QUESTION_CHARS."""
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        raise BadRequest('expected JSON body: {"question": "..."}')
    if not isinstance(body, dict) or "question" not in body:
        raise BadRequest('expected JSON body: {"question": "..."}')
    question = body["question"]
    if not isinstance(question, str):
        raise BadRequest(f"question must be a string, not {type(question).__name__}")
    question = question.strip()
    if not question:
        raise BadRequest("question is empty")
    if len(question) > MAX_QUESTION_CHARS:
        raise BadRequest(f"question is {len(question)} characters; the limit is {MAX_QUESTION_CHARS}")
    return question, body.get("async") is True


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
    model_fitness = ModelFitnessStore(log_for("model-fitness"))
    for model_id, rationale in ADMITTED_MODELS.items():   # recorded once; a restart is a no-op
        admit_model(model_fitness, model_id, rationale=rationale, admitted_by="owner")
    maintainer = Maintainer(
        idle=IdleContext(ledger=ledger, reputability=reputability,
                         consolidation=ConsolidationStore(log_for("consolidation"),
                                                          ContentAddressedStore(data_dir / "archive")),
                         fidelity=DomainFidelityStore(log_for("fidelity")),
                         checkpoints=HumanCheckpointStore(log_for("checkpoints")),
                         calibration=CalibrationStore(log_for("calibration")),
                         # owner decision 10: the admitted model re-examines model-backed
                         # claims; its challenges count once it is 'established'
                         model_challenger=DEFAULT_MODEL, model_fitness=model_fitness),
        log_for=log_for, belief_graph=graph, audits=AuditStore(log_for("audits")),
        verification=verification, ingestion_cas=cas, model_fitness=model_fitness)
    # Ingestion over HTTP needs a reviewer token and allow-listed hosts
    # (owner decision 7, POST /api/ingestion below); Python callers may still
    # call maintainer.submit_ingestion directly.
    work_available = threading.Event()

    # --- the inbox (batch 9, Phase AJ) -------------------------------------------
    # An async submission must not wait for the lock a worker round holds
    # (through a whole model call). It is written durably to its own small
    # log under its own lock, and the worker registers it with the Maintainer
    # before its next round. The inbox also issues question ids for both
    # paths, so ids stay unique without the main lock. Draining skips any id
    # the ledger already has, so a crash between registering and clearing
    # is harmless, and a restart drains whatever was left.
    inbox_log = log_for("inbox")
    inbox_lock = threading.Lock()
    saved_inbox = inbox_log.read_latest() or {"items": [], "issued": 0}
    inbox = {"items": list(saved_inbox["items"]),
             "issued": max(saved_inbox["issued"], ledger.count())}

    def _new_id() -> str:
        """Caller holds inbox_lock."""
        inbox["issued"] += 1
        return f"q-{inbox['issued']}"

    def _save_inbox() -> None:
        """Caller holds inbox_lock."""
        inbox_log.write_checkpoint({"items": inbox["items"], "issued": inbox["issued"]}, label="inbox")

    def _drain_inbox_locked() -> int:
        """Caller holds `lock`. Registers every waiting submission, in order."""
        with inbox_lock:
            waiting = list(inbox["items"])
        for item in waiting:
            if ledger.get(item["id"]) is None:
                maintainer.submit_question(item["id"], item["question"])
        if waiting:
            # snapshot first, then clear: a reader must see each submission in
            # one place or the other throughout, never in neither
            _refresh_locked()
            with inbox_lock:
                drained = {i["id"] for i in waiting}
                inbox["items"] = [i for i in inbox["items"] if i["id"] not in drained]
                _save_inbox()
        return len(waiting)

    def submit_question(question: str) -> dict:
        with lock:                 # lock order everywhere: lock, then inbox_lock
            with inbox_lock:
                # questions registered with the Maintainer directly (not via
                # this API) also take ids; the ledger is safe to read here
                inbox["issued"] = max(inbox["issued"], ledger.count())
                qid = _new_id()
                _save_inbox()      # the id is issued durably, so it is never reused
            ledger.submit(QuestionLedgerEntry(id=qid, importance=0.5))
            unit_log = CheckpointLog(cas=cas, index_path=data_dir / f"unit-{qid}.txt")
            runner = SingleUnitRunner(unit_log, shared_state={})
            try:
                unit = make_deliberation_unit(question, qid, reputability=reputability,
                                              verification=verification, belief_graph=graph,
                                              model_fitness=model_fitness)
                while unit.status != "completed":
                    runner.run_round(unit)
            except Exception as e:
                # never leave it 'queued' with nothing to run it (known-bugs #33)
                ledger.set_status(qid, "suspended")
                maintainer.record_failure(qid, {"kind": "question", "question": question}, e)
                _refresh_locked()
                raise DeliberationFailed(qid, maintainer.failed[qid]["last_error"]) from e
            answer = unit_log.read_latest()["shared_state"]["answer"]
            with ledger.batch(qid):   # the answer and its rating: one checkpoint
                ledger.append_version(qid, answer)
                # Section 7.1: replace the 0.5 placeholder with a computed rating.
                importance = rate_and_store_importance(ledger, qid, graph=graph)["importance"]
            _refresh_locked()
            return {"id": qid, "question": question, "answer": answer, "importance": importance}

    worker_thread: list[threading.Thread] = []

    def submit_async(question: str) -> dict:
        with inbox_lock:
            qid = _new_id()
            inbox["items"].append({"id": qid, "question": question, "submitted_at": time.time()})
            _save_inbox()          # durable before the 202
        _start_worker()
        return {"id": qid, "question": question, "status": "queued"}

    def _start_worker() -> None:
        # Started on first use, so a purely synchronous user never gets
        # background idle cycles running over their questions.
        with inbox_lock:
            if not worker_thread:
                worker_thread.append(threading.Thread(target=worker, name="athenaeum-maintainer", daemon=True))
                worker_thread[0].start()
        work_available.set()

    def worker() -> None:
        """One thread drives the Maintainer, one round at a time, taking the
        lock per round so synchronous requests interleave; reads and async
        submissions never wait for it (the snapshot and the inbox)."""
        while True:
            with lock:
                try:
                    _drain_inbox_locked()
                    maintainer.tick()
                except Exception as e:  # a failing round is the Maintainer's to retry; this catches
                    # anything else (e.g. a completed unit's follow-ups) so the worker never dies silently
                    maintainer.emit({"kind": "error", "error": repr(e)})
                busy = bool(maintainer.scheduler._heap)
                _refresh_locked()
            if not busy:
                work_available.wait(timeout=1.0)
                work_available.clear()

    # --- reads (batch 8, Phase AF) ---------------------------------------------
    # The lock is held for a whole worker round (model calls included) and a
    # whole synchronous deliberation, so a read never waits for it: it takes
    # the lock only if it is free (and refreshes the snapshot, so a read is
    # fresh whenever nothing is running); otherwise it answers from the
    # snapshot taken after the last completed write. Writers refresh it while
    # they still hold the lock. The snapshot is replaced wholesale, never
    # mutated, so a reader can serialize what it got without copying.
    snapshot: dict = {}
    snapshot_lock = threading.Lock()

    def _refresh_locked() -> None:
        """Caller holds `lock`."""
        entries = sorted((_with_question(q) for q in ledger._state()["questions"].values()),
                         key=lambda e: _number(e["id"]))
        fresh = {
            "questions": entries,
            "by_id": {e["id"]: e for e in entries},
            "maintenance": {"idle_cycles": maintainer.cycles, "queued_units": len(maintainer.scheduler._heap),
                            "pending_amendments": sorted(maintainer.pending_amendments),
                            "failed_units": sorted(maintainer.failed),
                            "models": {m: model_standing(model_fitness, m) for m in ADMITTED_MODELS},
                            "recent_events": list(maintainer.events[-10:])},
            "checkpoints": _checkpoints_locked(),
        }
        with snapshot_lock:
            snapshot.clear()
            snapshot.update(fresh)

    def _number(qid: str) -> int:
        tail = qid.rsplit("-", 1)[-1]
        return int(tail) if tail.isdigit() else 0

    def _view() -> dict:
        if lock.acquire(blocking=False):
            try:
                _refresh_locked()
            finally:
                lock.release()
        with snapshot_lock:
            view = dict(snapshot)
        # Submissions still in the inbox are already questions to the caller
        # (they got a 202 and an id): show them as queued (Phase AJ).
        with inbox_lock:
            waiting = [i for i in inbox["items"] if i["id"] not in view["by_id"]]
        if waiting:
            pending = [{"id": i["id"], "status": "queued", "importance": 0.5, "created_at": i["submitted_at"],
                        "versions": [], "question": i["question"]} for i in waiting]
            view["questions"] = sorted(view["questions"] + pending, key=lambda e: _number(e["id"]))
            view["by_id"] = {**view["by_id"], **{e["id"]: e for e in pending}}
        return view

    def get_version(qid: str, n: int):
        entry = _view()["by_id"].get(qid)
        if entry is None or not 0 <= n < len(entry["versions"]):
            return None
        return entry["versions"][n]

    def maintenance_status() -> dict:
        return _view()["maintenance"]

    def _with_question(entry: dict) -> dict:
        # A queued question has no version yet, so its text comes from the
        # Maintainer's registry; once answered, from its latest version.
        if entry["versions"]:
            question = entry["versions"][-1].get("question")
        else:
            question = (maintainer._m["units"].get(entry["id"])
                        or maintainer.failed.get(entry["id"], {})).get("question")
        failed = maintainer.failed.get(entry["id"])
        return {**entry, "question": question, **({"error": failed["last_error"]} if failed else {})}

    SUMMARY_FIELDS = ("id", "status", "question", "importance", "created_at", "error")

    def list_questions(view: str = "full") -> list:
        """view="full" (the default): every entry with every answer version.
        view="summary": what a poller needs to notice a change -- no answers,
        just `versions` as a count (batch 7, Phase AE)."""
        entries = _view()["questions"]
        if view == "summary":
            return [{**{k: e[k] for k in SUMMARY_FIELDS if k in e}, "versions": len(e["versions"])}
                    for e in entries]
        return entries

    def get_question(qid: str):
        return _view()["by_id"].get(qid)

    def _checkpoints_locked() -> list:
        found = []
        for key, cp in maintainer.idle.checkpoints.all().items() if maintainer.idle.checkpoints else []:
            kind, _, ref = key.partition(":") if ":" in key else ("question", "", key)
            item = {"key": key, "kind": kind, "ref": ref, **cp}
            if kind == "standard-amendment" and ref in maintainer.pending_amendments:
                item["proposal"] = maintainer.pending_amendments[ref]
            found.append(item)
        return sorted(found, key=lambda c: (c["status"] != "pending_human_checkpoint", c["key"]))

    def checkpoints() -> list:
        """Section 11.5's human checkpoints, read-only: what waits for a
        reviewer, and why. Pending first. A standard amendment carries the
        proposal itself so a reviewer can see what would change. Approving
        is deliberately not exposed here: this API has no authentication."""
        return _view()["checkpoints"]

    def health() -> dict:
        """Resources, plus whether work is moving (batch 8, Phase AG). Never
        waits for the lock: the queue length comes from the read snapshot and
        the worker's progress from attributes it rebinds atomically."""
        s = monitor.get_state()
        last = maintainer.last_round_at
        return {"status": "ok", "cores_available": s.cores_available,
                "dram_headroom_gb": s.dram_headroom_gb,
                "worker": {"started": bool(worker_thread),
                           "alive": bool(worker_thread) and worker_thread[0].is_alive(),
                           "rounds_run": maintainer.rounds_run,
                           "seconds_since_last_round": None if last is None else round(time.time() - last, 3)},
                "queued_units": _view()["maintenance"]["queued_units"]}

    # --- writes that need a reviewer (owner decision 7) -------------------------
    reviewers = Reviewers(reviewers_path(data_dir))

    def decide_checkpoint(identity: Identity, key: str, body: dict) -> dict:
        """Section 11.5/11.7 over HTTP: the reviewer's identity comes from
        their token, never from the request body, so the role check and the
        conflict-of-interest check in clear_checkpoint apply to who is
        really asking."""
        decision, note = body.get("decision"), body.get("note")
        if decision not in CHECKPOINT_DECISIONS:
            raise ApiError(400, f"decision must be one of {list(CHECKPOINT_DECISIONS)}")
        if note is not None and (not isinstance(note, str) or len(note) > MAX_QUESTION_CHARS):
            raise ApiError(400, f"note must be a string of at most {MAX_QUESTION_CHARS} characters")
        if identity.role != "reviewer":
            raise ApiError(403, f"role {identity.role!r} may not clear checkpoints; only a reviewer may (Section 11.7)")
        with lock:
            checkpoints_store = maintainer.idle.checkpoints
            if checkpoints_store is None or checkpoints_store.get(key) is None:
                raise ApiError(404, f"no checkpoint {key!r}")
            try:
                result = clear_checkpoint(checkpoints_store, key, reviewer_id=identity.reviewer_id,
                                          reviewer_role=identity.role, decision=decision, note=note)
            except CheckpointConflictError as e:
                raise ApiError(409, str(e))
            except HumanInputError as e:
                raise ApiError(400, str(e))
            _refresh_locked()
        return {"key": key, **result}

    def submit_ingestion(identity: Identity, body: dict) -> dict:
        """Section 9 over HTTP: only allow-listed hosts, checked here for
        every URL and again, with every redirect, when fetched."""
        if identity.role not in INGESTION_ROLES:
            raise ApiError(403, f"role {identity.role!r} may not submit ingestion")
        sources = body.get("sources")
        if not isinstance(sources, list) or not 1 <= len(sources) <= MAX_INGESTION_BATCH:
            raise ApiError(400, f"sources must be a list of 1 to {MAX_INGESTION_BATCH} source specs")
        allowlist = reviewers.allowlist
        for spec in sources:
            if not isinstance(spec, dict) or set(spec) - INGESTION_SPEC_KEYS:
                raise ApiError(400, f"each source takes only {sorted(INGESTION_SPEC_KEYS)}")
            if not isinstance(spec.get("url"), str) or not isinstance(spec.get("license"), str) \
                    or not spec["license"].strip():
                raise ApiError(400, "each source needs a url and a license")
            if not isinstance(spec.get("cites", []), list) or not all(isinstance(c, str) for c in spec.get("cites", [])):
                raise ApiError(400, "cites must be a list of source ids")
            if not isinstance(spec.get("is_paid_or_metered", False), bool):
                raise ApiError(400, "is_paid_or_metered must be true or false")
            if not host_allowed(spec["url"], allowlist):
                raise ApiError(400, f"{spec['url']!r} is not an http(s) URL on the ingestion allow-list")
        batch_id = f"ingest-{uuid.uuid4().hex[:12]}"
        with lock:
            maintainer.submit_ingestion(batch_id, sources, allowlist=allowlist, submitted_by=identity.reviewer_id)
            _refresh_locked()
        _start_worker()
        return {"batch_id": batch_id, "sources": len(sources), "status": "queued"}

    with lock:
        drained = _drain_inbox_locked()   # what a previous process accepted but never registered
        _refresh_locked()
    if drained:
        _start_worker()
    app = App((submit_question, list_questions, get_question, health))
    app.submit_async, app.get_version, app.maintenance_status = submit_async, get_version, maintenance_status
    app.maintainer, app.worker_thread, app.checkpoints = maintainer, worker_thread, checkpoints
    app.reviewers, app.decide_checkpoint, app.submit_ingestion = reviewers, decide_checkpoint, submit_ingestion
    app.lock = lock   # a test seam: holding it stands in for a round in progress
    return app


class Handler(BaseHTTPRequestHandler):
    submit_question = list_questions = get_question = health = None  # set by make_handler
    submit_async = get_version = maintenance_status = checkpoints = None
    reviewers = decide_checkpoint = submit_ingestion = None

    def _json(self, code: int, payload, headers: dict | None = None) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _static(self) -> None:
        path = urlparse(self.path).path
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        f = (CLIENT_DIR / rel).resolve()
        # Only files inside client/ are served: a raw "GET /../x" is not
        # normalized by the server, and must never escape it (known-bugs #32).
        if not f.is_relative_to(CLIENT_DIR.resolve()) or not f.is_file():
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
        self._guarded(self._get)

    def do_POST(self):
        self._guarded(self._post)

    def _guarded(self, handle) -> None:
        """Every request gets a JSON answer: an unexpected exception is a
        500, never a dropped connection (known-bugs #33)."""
        try:
            handle()
        except Exception as e:
            self.close_connection = True
            self._json(500, {"error": f"internal error: {type(e).__name__}"})

    def _get(self):
        url = urlparse(self.path)
        path = url.path
        if path == "/api/health":
            self._json(200, self.health())
        elif path == "/api/questions":
            view = parse_qs(url.query).get("view", ["full"])[-1]
            if view not in ("full", "summary"):
                self._json(400, {"error": f"unknown view {view!r}; expected 'full' or 'summary'"})
            else:
                self._json(200, self.list_questions(view))
        elif path == "/api/maintenance":
            self._json(200, self.maintenance_status())
        elif path == "/api/checkpoints":
            self._json(200, self.checkpoints())
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

    def _read_body(self) -> bytes | None:
        """The request body, or None after answering 400/413 (an oversized
        body is never read)."""
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            length = -1
        if length < 0:
            self.close_connection = True
            self._json(400, {"error": "invalid Content-Length"})
            return None
        if length > MAX_BODY_BYTES:
            self.close_connection = True  # the body is never read
            self._json(413, {"error": f"request body is {length} bytes; the limit is {MAX_BODY_BYTES}"})
            return None
        return self.rfile.read(length)

    def _authorized(self) -> Identity | None:
        """The caller's identity for a write endpoint, or None after
        answering 503 (no reviewers configured: writes are off) or 401. The
        body is not read before this, so a refused caller costs nothing."""
        if not self.reviewers.configured:
            self.close_connection = True
            self._json(503, {"error": "no reviewers are configured, so write endpoints are disabled "
                                      "(see scripts/add_reviewer.py)"})
            return None
        identity = self.reviewers.authenticate(self.headers.get("Authorization"))
        if identity is None:
            self.close_connection = True
            self._json(401, {"error": "a valid reviewer token is required (Authorization: Bearer <token>)"},
                       headers={"WWW-Authenticate": "Bearer"})
        return identity

    def _authorized_write(self, action) -> None:
        identity = self._authorized()
        if identity is None:
            return
        raw = self._read_body()
        if raw is None:
            return
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            body = None
        if not isinstance(body, dict):
            self._json(400, {"error": "expected a JSON object"})
            return
        try:
            self._json(200, action(identity, body))
        except ApiError as e:
            self._json(e.status, {"error": e.message})

    def _post(self):
        path = urlparse(self.path).path
        if path == "/api/ingestion":
            self._authorized_write(lambda identity, body: self.submit_ingestion(identity, body))
            return
        prefix, suffix = "/api/checkpoints/", "/decision"
        if path.startswith(prefix) and path.endswith(suffix) and len(path) > len(prefix) + len(suffix):
            key = unquote(path[len(prefix):-len(suffix)])
            self._authorized_write(lambda identity, body: self.decide_checkpoint(identity, key, body))
            return
        if path != "/api/questions":
            self._json(404, {"error": "not found"})
            return
        raw = self._read_body()
        if raw is None:
            return
        try:
            question, is_async = parse_question_request(raw)
        except BadRequest as e:
            self._json(400, {"error": str(e)})
            return
        if is_async:
            self._json(202, self.submit_async(question))
            return
        try:
            self._json(200, self.submit_question(question))
        except DeliberationFailed as e:
            self._json(500, {"error": f"deliberation failed: {e.error}", "id": e.question_id})

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
    BoundHandler.checkpoints = staticmethod(app.checkpoints)
    BoundHandler.reviewers = app.reviewers
    BoundHandler.decide_checkpoint = staticmethod(app.decide_checkpoint)
    BoundHandler.submit_ingestion = staticmethod(app.submit_ingestion)
    return BoundHandler


def serve(host="0.0.0.0", port=8080, data_dir: Path = Path("data/api-run")):
    data_dir.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((host, port), make_handler(data_dir))
    print(f"Athenaeum API + mobile client on http://{host}:{port}  "
          f"(open on your phone via LAN IP or a tunnel to this port)")
    server.serve_forever()


if __name__ == "__main__":
    serve()
