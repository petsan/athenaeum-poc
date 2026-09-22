"""
Real LlamaCppBackend tests -- these hit ACTUAL running llama-server
processes on the model-lab guests (infra/proxmox/model-lab/), no mocking,
same "verify empirically" convention as test_sandbox.py's real kernel
tests and test_distributed_worker.py's real process kills. Needs LAN
reachability to 192.168.0.161-166; will fail if those guests are ever
torn down (model-lab/README.md's guests are explicitly disposable).
"""
import pytest
from athenaeum_body.model_serving import ModelServingLayer, ModelRegistry, LlamaCppBackend, BackendUnavailable
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.model_lab_registry import (
    MODEL_LAB_ENDPOINTS, build_model_lab_backend, register_model_lab,
)


def test_llama_cpp_backend_gets_real_completion_from_olmo():
    backend = LlamaCppBackend(endpoints={"olmo3-7b": MODEL_LAB_ENDPOINTS["olmo3-7b"]})
    from athenaeum_body.model_serving import ModelSpec
    spec = ModelSpec(name="olmo3-7b", vram_gb=4.5)
    result = backend.infer(spec, "Q: What is 2+2?\nA:")
    assert isinstance(result, str) and len(result) > 0


def test_llama_cpp_backend_loaded_reports_all_configured_endpoints():
    backend = build_model_lab_backend()
    assert backend.loaded == set(MODEL_LAB_ENDPOINTS)


def test_llama_cpp_backend_raises_backend_unavailable_on_unreachable_endpoint():
    from athenaeum_body.model_serving import ModelSpec
    backend = LlamaCppBackend(endpoints={"ghost": "http://192.168.0.199:8080"}, timeout_seconds=2.0)
    spec = ModelSpec(name="ghost", vram_gb=1.0)
    with pytest.raises(BackendUnavailable):
        backend.infer(spec, "hello")


def test_model_serving_layer_routes_real_request_through_cpu_fallback(tmp_path):
    """No GPU pool exists (infra-topology.md) -- gpu_available=False is
    the honest current topology, and CPU fallback (Section 4.5.2/4.5.3)
    is exercised for real here, not simulated."""
    cas = ContentAddressedStore(tmp_path / "cas")
    registry = ModelRegistry(cas)
    register_model_lab(registry)
    backend = build_model_lab_backend()
    layer = ModelServingLayer(registry=registry, gpu_backend=backend, cpu_backend=backend, vram_pool_gb=0)
    layer.gpu_available = False

    result = layer.request("qwen2.5-1.5b", "Q: Name the largest planet in our solar system.\nA:")
    assert result["backend"] == "cpu"
    assert result["model"] == "qwen2.5-1.5b"
    assert "jupiter" in result["response"].lower()


def test_all_six_model_lab_candidates_respond_for_real(tmp_path):
    """One real completion from each of the six -- the actual A/B/C
    comparison the model-lab exists for, run as a test rather than only
    ever done manually."""
    cas = ContentAddressedStore(tmp_path / "cas")
    registry = ModelRegistry(cas)
    register_model_lab(registry)
    backend = build_model_lab_backend()
    layer = ModelServingLayer(registry=registry, gpu_backend=backend, cpu_backend=backend, vram_pool_gb=0)
    layer.gpu_available = False

    for name in MODEL_LAB_ENDPOINTS:
        result = layer.request(name, "Q: What color is the sky on a clear day?\nA:")
        assert len(result["response"]) > 0, f"{name} returned an empty response"
