"""
Elastic, opportunistic worker pool (body-design.md Section 4.3: "Workers
are stateless lease-holders"; Section 6.1: opportunistic compute is
"never a dependency" -- the Body must keep working with or without it).

A worker is any machine running a real llama.cpp-compatible backend --
GPU or CPU, whatever spec it happens to have -- that MAY be online right
now. The whole point of this module is making "may or may not be online"
routine, not a failure: health is checked FRESH before every single call
(never a cached flag that could go stale the moment a worker's owner
closes their laptop), and an offline worker raises BackendUnavailable,
which ModelServingLayer.request() already knows how to turn into a
transparent CPU fallback rather than a crash.

Workers are listed in elastic_workers.yaml (repo root) -- a small,
hand-edited manifest, the same "add a machine = one line" pattern
infra/proxmox/model-lab/manifest.tsv already established for the Proxmox
guests. Deliberately NOT a push-based self-registration service: no new
machine needs to announce itself anywhere, and there's no auth/security
surface for accepting unsolicited registrations from the network. Revisit
only if hand-editing a YAML file actually becomes the real bottleneck --
not speculatively now.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import json
import urllib.error
import urllib.request
import yaml

from .model_serving import ModelSpec, BackendUnavailable

DEFAULT_CONFIG_PATH = "elastic_workers.yaml"


@dataclass
class WorkerSpec:
    name: str
    endpoint: str
    models: list[str]  # which model name(s) this worker can serve


def load_workers(path: str = DEFAULT_CONFIG_PATH) -> list[WorkerSpec]:
    """An empty/missing config is not an error -- it just means no
    elastic workers are configured yet, the same 'gracefully nothing to
    do' shape as every other 'no claim produced' path in this codebase."""
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return []
    return [WorkerSpec(name=w["name"], endpoint=w["endpoint"], models=list(w["models"]))
            for w in data.get("workers", [])]


def _is_healthy(endpoint: str, timeout_seconds: float) -> bool:
    try:
        with urllib.request.urlopen(f"{endpoint}/health", timeout=timeout_seconds) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


@dataclass
class ElasticGPUBackend:
    """Real Backend implementation (Section 4.5's Backend protocol) over a
    pool of opportunistic workers, health-checked live on every call --
    never assumed available from configuration alone. Multiple workers
    may list the same model name (basic failover/spread across whichever
    machines happen to be online for it); the first one that answers a
    live health check is used."""
    workers: list[WorkerSpec] = field(default_factory=list)
    health_timeout_seconds: float = 3.0
    infer_timeout_seconds: float = 120.0
    n_predict: int = 96

    @property
    def loaded(self) -> set:
        """Every model ANY configured worker claims to serve -- this is
        configuration, not a live-health claim (that's checked fresh
        inside infer() itself); matches LlamaCppBackend's own
        'loaded reports what's configured, not what's currently healthy'
        convention, for the same reason: ModelServingLayer only asks
        'should I bother trying to load this' here, and finds out whether
        it's ACTUALLY reachable when it calls infer()."""
        return {m for w in self.workers for m in w.models}

    def load(self, spec: ModelSpec) -> None:
        pass  # stateless lease-holder -- nothing to load in-process

    def unload(self, spec: ModelSpec) -> None:
        pass

    def healthy_workers_for(self, model_name: str) -> list[WorkerSpec]:
        candidates = [w for w in self.workers if model_name in w.models]
        return [w for w in candidates if _is_healthy(w.endpoint, self.health_timeout_seconds)]

    def infer(self, spec: ModelSpec, prompt: str) -> str:
        healthy = self.healthy_workers_for(spec.name)
        if not healthy:
            configured = sum(1 for w in self.workers if spec.name in w.models)
            raise BackendUnavailable(
                f"no healthy elastic worker currently serving '{spec.name}' "
                f"({configured} configured, 0 responding right now -- this is routine, "
                f"not an error, see elastic_workers.py's module docstring)")
        worker = healthy[0]
        payload = json.dumps({"prompt": prompt, "n_predict": self.n_predict}).encode()
        req = urllib.request.Request(
            f"{worker.endpoint}/completion", data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.infer_timeout_seconds) as resp:
                body = json.loads(resp.read())
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise BackendUnavailable(f"'{worker.name}' at {worker.endpoint!r} unreachable: {e}") from e
        return body["content"]


def build_elastic_gpu_backend(config_path: str = DEFAULT_CONFIG_PATH) -> ElasticGPUBackend:
    return ElasticGPUBackend(workers=load_workers(config_path))
