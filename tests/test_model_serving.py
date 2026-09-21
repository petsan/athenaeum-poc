import pytest
from athenaeum_body.storage.content_addressed import ContentAddressedStore, IntegrityError
from athenaeum_body.model_serving import ModelRegistry, ModelServingLayer, MockBackend, ModelSpec

def make_layer(tmp_path, vram_gb=48):
    registry = ModelRegistry(ContentAddressedStore(tmp_path / "models"))
    layer = ModelServingLayer(registry, gpu_backend=MockBackend("gpu"),
                               cpu_backend=MockBackend("cpu"), vram_pool_gb=vram_gb)
    return registry, layer

def test_request_routes_to_gpu_by_default(tmp_path):
    registry, layer = make_layer(tmp_path)
    registry.admit(ModelSpec("small-coder", vram_gb=24, capabilities=("coding",)))
    result = layer.request("small-coder", "write a function")
    assert result["backend"] == "gpu"

def test_unadmitted_model_rejected(tmp_path):
    _, layer = make_layer(tmp_path)
    with pytest.raises(KeyError):
        layer.request("nonexistent", "hi")

def test_lru_eviction_under_vram_pressure(tmp_path):
    registry, layer = make_layer(tmp_path, vram_gb=30)
    registry.admit(ModelSpec("a", vram_gb=20))
    registry.admit(ModelSpec("b", vram_gb=20))
    layer.request("a", "p1")
    layer.request("b", "p2")  # forces eviction of 'a' (30GB pool, 20+20 doesn't fit)
    assert "a" not in layer.gpu.loaded
    assert "b" in layer.gpu.loaded

def test_reusing_a_model_protects_it_from_eviction(tmp_path):
    registry, layer = make_layer(tmp_path, vram_gb=45)
    registry.admit(ModelSpec("a", vram_gb=20))
    registry.admit(ModelSpec("b", vram_gb=20))
    registry.admit(ModelSpec("c", vram_gb=20))
    layer.request("a", "p1")
    layer.request("b", "p2")
    layer.request("a", "p3")   # touch 'a' again -> 'b' becomes LRU, not 'a'
    layer.request("c", "p4")   # should evict 'b', not 'a'
    assert "a" in layer.gpu.loaded
    assert "b" not in layer.gpu.loaded

def test_gpu_unavailable_falls_back_to_cpu_transparently(tmp_path):
    registry, layer = make_layer(tmp_path)
    registry.admit(ModelSpec("a", vram_gb=20))
    layer.gpu_available = False
    result = layer.request("a", "p1")
    assert result["backend"] == "cpu"
    assert "a" in layer.cpu.loaded

def test_tampered_weights_detected_before_serving(tmp_path):
    registry, layer = make_layer(tmp_path)
    registry.admit(ModelSpec("a", vram_gb=20))
    registry.cas.corrupt_for_testing(registry.get("a").weights_ref, b"tampered!!")
    with pytest.raises(IntegrityError):
        layer.request("a", "p1")
