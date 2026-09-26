import os
import sys, pathlib
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "src"))

# Opt-in offline mode (default OFF -- the normal suite still makes real
# model calls). With ATHENAEUM_OFFLINE_MODELS=1, every Master Agent's
# model-backed fallback behaves exactly as it already does when a backend
# is unreachable: ask_model returns None, i.e. "no claim produced". For
# verifying non-model changes while the model-lab guests are down or
# degraded (known-bugs.md, deployment gotchas). The files whose purpose IS
# live-model behaviour -- test_model_backed_reasoning.py,
# test_model_serving_real.py, and test_evaluation.py's B1 baseline -- are
# not meaningful offline and should be deselected in that mode.
OFFLINE_MODELS = os.environ.get("ATHENAEUM_OFFLINE_MODELS") == "1"


@pytest.fixture(autouse=True)
def _offline_models(monkeypatch):
    if OFFLINE_MODELS:
        from athenaeum_brain import model_backed_reasoning
        monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)
