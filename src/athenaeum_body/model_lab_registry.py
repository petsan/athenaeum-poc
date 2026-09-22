"""
The six model-lab candidates (infra/proxmox/model-lab/manifest.tsv),
described as ModelSpecs + a LlamaCppBackend endpoint map, so tests and
evaluation code have one place to get "what's actually live right now"
instead of hand-rolling IPs. Kept in sync with manifest.tsv by hand --
if a guest gets destroyed or replaced, update both.

These are real, running CPU-quantized models on isolated LXC guests
(model-lab/README.md) -- NOT the production swap-based router topology
(body-design.md Section 4.5), which remains a postponed decision.
"""
from __future__ import annotations
import json
from .model_serving import ModelSpec, LlamaCppBackend, ModelRegistry

MODEL_LAB_ENDPOINTS = {
    "olmo2-1b": "http://192.168.0.160:8080",
    "qwen-coder-1.5b": "http://192.168.0.161:8080",
    "qwen2.5-1.5b": "http://192.168.0.162:8080",
    "phi-3.5-mini": "http://192.168.0.163:8080",
    "granite-2b": "http://192.168.0.164:8080",
    "mistral-7b": "http://192.168.0.165:8080",
}

# vram_gb here is really "resource footprint" -- these run on CPU/RAM, not
# VRAM, but ModelSpec/ModelServingLayer's eviction math is generic over
# "footprint units" (Section 4.5.3 applies the same discipline to any
# shared, contended resource) and these guests are isolated single-model
# boxes anyway, so eviction never actually triggers for them today.
MODEL_LAB_SPECS = {
    "olmo2-1b": ModelSpec(name="olmo2-1b", vram_gb=0.7, capabilities=("general",)),
    "qwen-coder-1.5b": ModelSpec(name="qwen-coder-1.5b", vram_gb=1.0, capabilities=("coding",)),
    "qwen2.5-1.5b": ModelSpec(name="qwen2.5-1.5b", vram_gb=1.0, capabilities=("general",)),
    "phi-3.5-mini": ModelSpec(name="phi-3.5-mini", vram_gb=2.3, capabilities=("general",)),
    "granite-2b": ModelSpec(name="granite-2b", vram_gb=1.3, capabilities=("general",)),
    "mistral-7b": ModelSpec(name="mistral-7b", vram_gb=4.5, capabilities=("general",)),
}


def build_model_lab_backend(timeout_seconds: float = 60.0) -> LlamaCppBackend:
    return LlamaCppBackend(endpoints=dict(MODEL_LAB_ENDPOINTS), timeout_seconds=timeout_seconds)


def register_model_lab(registry: ModelRegistry) -> None:
    """Admits all six candidates into a ModelRegistry with a placeholder
    weights payload -- the actual multi-GB weight files live on their
    respective guests' disks, not in this process's content-addressed
    store, so what gets hashed here is a small manifest of WHICH model
    this claims to be (name + endpoint), not the weight bytes themselves.
    Verifying multi-GB remote weight integrity against a local CAS mirror
    is future work, not attempted here -- stated explicitly rather than
    silently implied by reusing ContentAddressedStore's tamper-detection
    machinery for something it isn't actually checking."""
    for name, spec in MODEL_LAB_SPECS.items():
        manifest = json.dumps({"name": name, "endpoint": MODEL_LAB_ENDPOINTS[name]}).encode()
        registry.admit(spec, weights=manifest)
