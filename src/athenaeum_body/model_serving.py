"""
Local Model Serving Layer (Section 4.5).

Registry, router contract, VRAM-budget-aware LRU loading/unloading, and
automatic GPU-unavailable -> CPU-fallback redirection (4.5.2-4.5.3) were
already real and tested against MockBackend. Added 2026-09-23:
LlamaCppBackend, a REAL backend talking to actual llama.cpp `llama-server`
processes -- the six model-lab guests (infra/proxmox/model-lab/), each
running a real CPU-quantized open-weight model. No GPU pool exists yet
(infra-topology.md), so this backend is wired in as the CPU fallback
with gpu_available=False -- every request routes to it directly, which
is the honest current topology, not a temporary workaround.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Protocol, Optional
import json
import time
import urllib.error
import urllib.request

from .storage.content_addressed import ContentAddressedStore


@dataclass
class ModelSpec:
    name: str
    vram_gb: float
    capabilities: tuple = ()   # e.g. ("coding", "general")
    weights_ref: str = None    # content-address in the registry's CAS (4.5.1)


class Backend(Protocol):
    """What a real vLLM/llama.cpp adapter must implement."""
    def load(self, spec: ModelSpec) -> None: ...
    def unload(self, spec: ModelSpec) -> None: ...
    def infer(self, spec: ModelSpec, prompt: str) -> str: ...


@dataclass
class MockBackend:
    """Deterministic stand-in satisfying the Backend contract, so the
    router/eviction/fallback mechanics can be tested without real weights."""
    kind: str  # "gpu" or "cpu"
    loaded: set = field(default_factory=set)

    def load(self, spec: ModelSpec) -> None:
        self.loaded.add(spec.name)

    def unload(self, spec: ModelSpec) -> None:
        self.loaded.discard(spec.name)

    def infer(self, spec: ModelSpec, prompt: str) -> str:
        if spec.name not in self.loaded:
            raise RuntimeError(f"{spec.name} not loaded on {self.kind} backend")
        return f"[{self.kind}:{spec.name}] response to: {prompt}"


class BackendUnavailable(Exception):
    """A real backend's inference call failed (network, timeout, non-200)
    -- distinct from a KeyError (model never registered) or a RuntimeError
    (MockBackend's own not-loaded case), so a caller can tell 'this model
    doesn't exist' apart from 'this model exists but couldn't be reached
    right now'."""


@dataclass
class LlamaCppBackend:
    """Real backend: talks to an actual llama.cpp `llama-server` process
    over HTTP (stdlib `urllib` only -- matches api.py's/ingestion.py's own
    no-new-dependency convention). Each ModelSpec.name maps to a
    configured endpoint via `endpoints`.

    Deliberately stateless about load/unload: each of the six model-lab
    guests already runs exactly one model for the lifetime of its
    systemd-managed llama-server process (infra/proxmox/model-lab/) --
    there is nothing for THIS backend to load or unload in-process, so
    those two methods are no-ops and `loaded` always reports every
    configured endpoint as loaded. This mirrors the same "stateless
    lease-holder" pattern already used for distributed_worker.py -- the
    actual state lives on the remote process, not here."""
    endpoints: dict  # model name -> "http://host:port"
    timeout_seconds: float = 60.0
    n_predict: int = 64  # real finding, not a guess: 256 tokens on these
    # 2-vCPU CPU-inference guests genuinely exceeded a 60s timeout for the
    # larger candidates (Phi-3.5-mini) -- 64 is comfortably fast for
    # sanity/comparison use while still exercising real generation;
    # callers doing longer real reasoning should raise both this and
    # timeout_seconds together, not just the timeout.

    @property
    def loaded(self) -> set:
        return set(self.endpoints)

    def load(self, spec: ModelSpec) -> None:
        pass

    def unload(self, spec: ModelSpec) -> None:
        pass

    def infer(self, spec: ModelSpec, prompt: str) -> str:
        if spec.name not in self.endpoints:
            raise KeyError(f"'{spec.name}' has no configured endpoint on this backend")
        url = self.endpoints[spec.name]
        payload = json.dumps({"prompt": prompt, "n_predict": self.n_predict}).encode()
        req = urllib.request.Request(
            f"{url}/completion", data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                body = json.loads(resp.read())
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise BackendUnavailable(f"'{spec.name}' at {url!r} unreachable: {e}") from e
        return body["content"]


class ModelRegistry:
    """Content-addressed catalog of admitted models (Section 4.5.1)."""
    def __init__(self, cas: ContentAddressedStore):
        self.cas = cas
        self._specs: dict[str, ModelSpec] = {}

    def admit(self, spec: ModelSpec, weights: bytes = b"placeholder-weights") -> None:
        spec.weights_ref = self.cas.put(weights)  # tamper-evident (3.4)
        self._specs[spec.name] = spec

    def get(self, name: str) -> Optional[ModelSpec]:
        return self._specs.get(name)

    def by_capability(self, capability: str) -> list[ModelSpec]:
        return [s for s in self._specs.values() if capability in s.capabilities]

    def verify_weights_intact(self, name: str) -> bool:
        spec = self._specs[name]
        self.cas.get(spec.weights_ref)  # raises IntegrityError if tampered
        return True


class ModelServingLayer:
    """
    Unified routing interface (4.5.2): callers ask for a model by name or
    capability and get a response, never addressing a backend directly.
    """
    def __init__(self, registry: ModelRegistry, gpu_backend: Backend,
                 cpu_backend: Backend, vram_pool_gb: float):
        self.registry = registry
        self.gpu = gpu_backend
        self.cpu = cpu_backend
        self.vram_pool_gb = vram_pool_gb
        self._gpu_loaded_order: list[str] = []  # LRU order, most-recent last
        self.gpu_available = True

    def _gpu_used_gb(self) -> float:
        return sum(self.registry.get(n).vram_gb for n in self._gpu_loaded_order)

    def _touch(self, name: str) -> None:
        if name in self._gpu_loaded_order:
            self._gpu_loaded_order.remove(name)
        self._gpu_loaded_order.append(name)

    def _evict_lru_until_fits(self, needed_gb: float) -> None:
        while self._gpu_loaded_order and self._gpu_used_gb() + needed_gb > self.vram_pool_gb:
            victim = self._gpu_loaded_order.pop(0)  # least-recently-used
            self.gpu.unload(self.registry.get(victim))

    def request(self, model_name: str, prompt: str) -> dict:
        """Returns {"response": ..., "backend": "gpu"|"cpu", "model": name}."""
        spec = self.registry.get(model_name)
        if spec is None:
            raise KeyError(f"model '{model_name}' not in registry (not admitted -- 4.5.1)")
        self.registry.verify_weights_intact(model_name)  # 3.4 tamper check on every load

        if self.gpu_available:
            if model_name not in self.gpu.loaded:
                self._evict_lru_until_fits(spec.vram_gb)  # 4.5.3 LRU eviction
                self.gpu.load(spec)
            self._touch(model_name)
            return {"response": self.gpu.infer(spec, prompt), "backend": "gpu", "model": model_name}

        # 4.5.2/4.5.3: GPU unavailable -> transparent CPU fallback, not an error
        if model_name not in self.cpu.loaded:
            self.cpu.load(spec)
        return {"response": self.cpu.infer(spec, prompt), "backend": "cpu", "model": model_name}
