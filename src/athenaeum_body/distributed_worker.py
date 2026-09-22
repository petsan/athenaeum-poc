"""
Distributed compute (body-design.md Section 4.2): stateless lease-holder
workers, dispatched by a scheduler over the network. "Stateless" here
means literally that -- a worker receives an opaque `unit_spec` plus the
current round's state, computes one round via a caller-supplied
`round_handler_factory`, and returns the result; it holds nothing between
requests. Loss of a worker mid-task simply means the request fails and
the caller retries (locally, or against a different worker) -- because
SingleUnitRunner.run_round (scheduler/runner.py) only checkpoints AFTER a
round completes, a failed remote round leaves the checkpoint log exactly
where it was, so retrying is just calling run_round again, no special
recovery path needed.

Deliberately Body-only and Brain-agnostic: this module has no import of
athenaeum_brain anywhere, matching the same layering discipline loop.py
established (the Brain adapts itself to the Body's contract, not the
other way around) -- a caller supplies round_handler_factory, this module
never hardcodes what kind of unit it's running.

Stdlib only (http.server / urllib.request / json), matching api.py's own
no-new-dependency convention.
"""
from __future__ import annotations
import json
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable
from .scheduler.work_unit import RoundResult, RoundHandler


class WorkerUnavailable(Exception):
    """Raised by a dispatched round when the remote worker couldn't be
    reached or errored -- the caller's own retry/failover policy decides
    what happens next (retry the same worker, fail over to a different
    one, or run the round locally instead); this module doesn't decide
    that for the caller."""


def _make_request_handler(round_handler_factory: Callable[[dict], RoundHandler]):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # quiet -- this project's tests don't want per-request stderr noise

        def do_POST(self):
            if self.path != "/run_round":
                self.send_response(404)
                self.end_headers()
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length))
                handler = round_handler_factory(body["unit_spec"])
                result = handler(body["state"], body["round_index"])
                payload = json.dumps({"proposed_writes": result.proposed_writes, "done": result.done}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except Exception as e:
                payload = json.dumps({"error": str(e)}).encode()
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

    return Handler


def serve_worker(host: str, port: int, round_handler_factory: Callable[[dict], RoundHandler]) -> HTTPServer:
    """Builds and returns a ready-to-serve HTTPServer -- caller decides how
    to run it (serve_forever() in a thread/process, or handle_request()
    once for a test). Not started automatically, so tests can control
    exactly one request at a time when that's useful."""
    server = HTTPServer((host, port), _make_request_handler(round_handler_factory))
    return server


def remote_round_handler(worker_url: str, unit_spec: dict, timeout_seconds: float = 10.0) -> RoundHandler:
    """Returns a RoundHandler (same (state, round_index) -> RoundResult
    signature as any local handler, e.g. loop.make_deliberation_handler)
    that dispatches each round to a remote worker instead of computing it
    locally. Drop-in for WorkUnit.round_handler -- SingleUnitRunner and
    the multi-unit scheduler need no changes to use a distributed unit,
    since the RoundResult contract is identical either way."""

    def handler(state: dict, round_index: int) -> RoundResult:
        payload = json.dumps({"unit_spec": unit_spec, "state": state, "round_index": round_index}).encode()
        req = urllib.request.Request(
            f"{worker_url}/run_round", data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                body = json.loads(resp.read())
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise WorkerUnavailable(f"worker at {worker_url!r} unreachable: {e}") from e
        if "error" in body:
            raise WorkerUnavailable(f"worker at {worker_url!r} round failed: {body['error']}")
        return RoundResult(proposed_writes=body["proposed_writes"], done=body["done"])

    return handler
