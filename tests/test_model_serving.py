import pytest
from athenaeum_body.storage.content_addressed import ContentAddressedStore, IntegrityError
from athenaeum_body.model_serving import ModelRegistry, ModelServingLayer, MockBackend, ModelSpec
from athenaeum_brain.model_backed_reasoning import ask_model as REAL_ASK_MODEL   # before offline mode stubs it

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


@pytest.mark.parametrize("stop, sent", [((), None), (("\n",), ["\n"])])
def test_llama_backend_sends_stop_strings_only_when_given(monkeypatch, stop, sent):
    """Batch 12: generation can end at the first stop string instead of
    running on to n_predict (measured in progress.md §107.3)."""
    import io
    import json
    import urllib.request
    from athenaeum_body.model_serving import LlamaCppBackend
    seen = {}

    def fake_urlopen(req, timeout):
        seen.update(json.loads(req.data))
        return io.BytesIO(json.dumps({"content": " Paris"}).encode())
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    backend = LlamaCppBackend(endpoints={"m": "http://x"}, stop=stop)
    assert backend.infer(ModelSpec(name="m", vram_gb=0), "Q: capital of France?\nA:") == " Paris"
    assert seen.get("stop") == sent and seen["n_predict"] == 64


def test_ask_model_gives_both_backends_the_same_limits(monkeypatch):
    """Both paths stop at a line break by default and honour n_predict;
    the GPU path used to generate 96 tokens even for an 8-token yes/no."""
    from athenaeum_body.model_serving import BackendUnavailable, LlamaCppBackend
    from athenaeum_brain import model_backed_reasoning as mbr
    seen = {}

    class Gpu:
        n_predict, stop = 96, ()

        def infer(self, spec, prompt):
            seen["gpu"] = (self.n_predict, self.stop)
            raise BackendUnavailable("no worker")
    monkeypatch.setattr(mbr, "build_elastic_gpu_backend", Gpu)
    monkeypatch.setattr(LlamaCppBackend, "infer",
                        lambda self, spec, prompt: seen.setdefault("cpu", (self.n_predict, self.stop)) and "yes")
    assert REAL_ASK_MODEL("is it?", "olmo3-7b", n_predict=8) == "yes"
    assert seen == {"gpu": (8, ("\n",)), "cpu": (8, ("\n",))}
