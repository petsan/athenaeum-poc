"""
Local Model Serving Layer (Section 4.5) -- structural stub.

Real backends (vLLM, llama.cpp) aren't wired up here -- no GPU/network in
this environment to validate against. What IS real and tested: the
registry, the router contract, VRAM-budget-aware LRU loading/unloading,
and automatic GPU-unavailable -> CPU-fallback redirection (4.5.2-4.5.3).
A real backend just has to implement the same `Backend` interface.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Protocol, Optional
import time

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
