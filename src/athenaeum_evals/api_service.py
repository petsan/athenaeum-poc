"""Does the service meet its SLOs? A real HTTP server, a burst of work.

A ThreadingHTTPServer serving `make_handler` (what `serve()` runs) on a free
local port, with a fresh data directory. Every deliberation golden question
is submitted asynchronously at once; the client then polls the summary list
and health until each is answered, and reads each answer. Measured:
  submit, poll and read latency (p95 of each, over every request);
  time from submission until an answer is available (p95 over questions);
  whether health showed the worker moving while work was queued.
Every p95 is gated on the high end of a bootstrap interval (resampling
requests), so a lucky run can't pass on a thin sample.

Any error response or a question that never finishes is a hard violation.
Thresholds come from runs on LXC 104 (see progress.md §107) plus headroom;
they describe this deployment, not a promise for other hardware.
"""
from __future__ import annotations

import json
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import numpy as np
from evalcore import CaseResult, Config, GateSpec, Suite, SuiteMetric

from . import deliberation

KEY = "api_service"
NAN = float("nan")
OPERATIONS = ("submit", "poll", "read", "answer")

SUITE = Suite(
    key=KEY, title="API service levels (a real server under a burst)",
    suite_gates=[
        GateSpec("submit_p95_s", "p95 submit latency (s)", "<=", "api_max_submit_p95_s"),
        GateSpec("poll_p95_s", "p95 poll latency (s)", "<=", "api_max_poll_p95_s"),
        GateSpec("read_p95_s", "p95 read latency (s)", "<=", "api_max_read_p95_s"),
        GateSpec("answer_p95_s", "p95 time until answered (s)", "<=", "api_max_answer_p95_s"),
        GateSpec("worker_moving", "Health shows the worker moving while work is queued", ">=", 1.0, min_n=1),
    ],
    hard_gate_label="Error responses or unfinished questions",
    defaults={"api_max_submit_p95_s": 0.5, "api_max_poll_p95_s": 0.5, "api_max_read_p95_s": 0.5,
              "api_max_answer_p95_s": 120.0},
)


class _Client:
    def __init__(self, base: str):
        self.base, self.timings = base, {op: [] for op in OPERATIONS}
        self.errors: list[str] = []

    def call(self, op: str, path: str, payload=None, timeout: float = 60):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(self.base + path, data=data, method="POST" if data else "GET",
                                     headers={"Content-Type": "application/json"})
        start = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = json.loads(r.read())
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            self.errors.append(f"{op} {path}: {e}")
            return None
        if op in self.timings:
            self.timings[op].append(time.perf_counter() - start)
        return body


def _serve(data_dir: Path, handler_factory=None):
    from athenaeum_body.api import make_handler
    server = ThreadingHTTPServer(("127.0.0.1", 0), (handler_factory or make_handler)(data_dir))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def drive(base: str, questions: list[str], timeout: float) -> dict:
    """The burst: returns timings, errors, per-question outcome and health samples."""
    client = _Client(base)
    submitted = {}
    for q in questions:
        body = client.call("submit", "/api/questions", {"question": q, "async": True})
        if body:
            submitted[body["id"]] = {"question": q, "at": time.perf_counter()}
    done, health = {}, []
    deadline = time.perf_counter() + timeout
    while len(done) < len(submitted) and time.perf_counter() < deadline:
        summary = client.call("poll", "/api/questions?view=summary") or []
        h = client.call("health", "/api/health")
        if h:
            health.append({"queued": h["queued_units"], "alive": h["worker"]["alive"],
                           "rounds": h["worker"]["rounds_run"]})
        now = time.perf_counter()
        for s in summary:
            if s["id"] in submitted and s["id"] not in done and s["status"] in ("completed", "suspended"):
                done[s["id"]] = {"status": s["status"], "seconds": now - submitted[s["id"]]["at"]}
        time.sleep(0.05)
    for qid in done:
        client.call("read", f"/api/questions/{qid}")
    client.timings["answer"] = [d["seconds"] for d in done.values() if d["status"] == "completed"]
    return {"timings": client.timings, "errors": client.errors, "submitted": submitted, "done": done,
            "health": health}


def _p95(values: list[float], config: Config, seed_offset: int) -> SuiteMetric:
    if not values:
        return SuiteMetric(NAN, n=0, detail={"note": "no measurements"})
    v = np.asarray(values, dtype=float)
    rng = np.random.default_rng(config.seed + seed_offset)
    boots = [np.percentile(v[rng.integers(0, v.size, v.size)], 95) for _ in range(config.bootstrap_iterations)]
    alpha = (1 - config.confidence) / 2
    point = float(np.percentile(v, 95))
    return SuiteMetric(point, float(np.quantile(boots, alpha)), float(np.quantile(boots, 1 - alpha)), n=v.size,
                       detail={"note": f"median {np.median(v):.3f}s, max {v.max():.3f}s over {v.size}"})


def _worker_moving(health: list[dict]) -> SuiteMetric:
    busy = [h for h in health if h["queued"]]
    if len(health) < 2 or not busy:
        return SuiteMetric(NAN, n=0, detail={"note": "health never saw queued work"})
    moved = health[-1]["rounds"] > health[0]["rounds"] and all(h["alive"] for h in busy)
    return SuiteMetric(float(moved), n=1, detail={"note": (
        f"{len(busy)} of {len(health)} health samples had queued work; rounds {health[0]['rounds']} -> "
        f"{health[-1]['rounds']}; worker {'alive throughout' if all(h['alive'] for h in busy) else 'NOT alive'}")})


_RUN: dict = {}


def evaluate(questions: list[str] | None = None, *, timeout: float = 600, handler_factory=None,
             config: Config | None = None) -> list[CaseResult]:
    """One CaseResult per submitted question; the latency metrics are kept
    for `metrics()` (the runner calls it right after)."""
    questions = questions if questions is not None else [i["question"] for i in deliberation.items()]
    with tempfile.TemporaryDirectory(prefix="athenaeum-api-") as tmp:
        server, base = _serve(Path(tmp), handler_factory)
        try:
            run = drive(base, questions, timeout)
        finally:
            server.shutdown()
            server.server_close()
            server.RequestHandlerClass.app.stop_worker()      # before its data directory goes
    _RUN.clear()
    _RUN.update(run)
    results = []
    for qid, info in run["submitted"].items():
        r = CaseResult(KEY, qid, "question", "original", 0)
        d = run["done"].get(qid)
        r.latency_s = d["seconds"] if d else None
        r.detail["question"] = info["question"]
        if d is None:
            r.hard_violations.append(f"never answered within {timeout:.0f}s")
        elif d["status"] != "completed":
            r.hard_violations.append(f"ended {d['status']}")
        if r.hard_violations:
            r.detail["problem"] = f"{qid} ({info['question']}): {'; '.join(r.hard_violations)}"
        results.append(r)
    if run["errors"] or len(run["submitted"]) < len(questions):
        r = CaseResult(KEY, "requests", "requests", "original", 0)
        r.hard_violations += run["errors"][:20] or [f"only {len(run['submitted'])} of {len(questions)} submissions accepted"]
        r.detail["problem"] = "; ".join(r.hard_violations)[:500]
        results.append(r)
    return results


def metrics(config: Config | None = None, run: dict | None = None) -> dict[str, SuiteMetric]:
    config = config or Config()
    run = _RUN if run is None else run
    if not run:
        return {name: SuiteMetric(NAN, n=0, detail={"note": "the service was not driven"})
                for name in ("submit_p95_s", "poll_p95_s", "read_p95_s", "answer_p95_s", "worker_moving")}
    out = {f"{op}_p95_s": _p95(run["timings"][op], config, i) for i, op in enumerate(OPERATIONS)}
    out["worker_moving"] = _worker_moving(run["health"])
    return out
