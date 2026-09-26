"""Owner decision 4 (batch 10, Phase AM): the API admits OLMo 3 7B and
weights model-backed claims by fitness -- on the synchronous path, the
Maintainer's path, and reopens alike."""
import pytest
from athenaeum_body.api import build_app, ADMITTED_MODELS
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.ledger import QuestionLedger
from athenaeum_body.reputability_store import ReputabilityStore
from athenaeum_body.belief_graph_store import BeliefGraphStore
from athenaeum_body.model_fitness_store import ModelFitnessStore
from athenaeum_brain import model_backed_reasoning
from athenaeum_brain.model_backed_reasoning import DEFAULT_MODEL
from athenaeum_brain.model_fitness import admit_model
from athenaeum_brain.idle_evolution import IdleContext
from athenaeum_brain.maintenance import Maintainer, MaintenancePolicy

MODEL_ONLY = "what force holds the moon in orbit?"


@pytest.fixture(autouse=True)
def _model(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: "gravity holds the moon in orbit")


def test_the_api_admits_the_default_model_once(tmp_path):
    app = build_app(tmp_path)
    fitness = ModelFitnessStore(CheckpointLog(cas=ContentAddressedStore(tmp_path / "cas"),
                                              index_path=tmp_path / "model-fitness.txt"))
    record = fitness.admission(DEFAULT_MODEL)
    assert list(ADMITTED_MODELS) == [DEFAULT_MODEL] == ["olmo3-7b"]
    assert record["admitted_by"] == "owner" and "decision 4" in record["rationale"]
    entries = len(fitness.log._read_index())
    build_app(tmp_path)                                  # a restart re-admits nothing
    assert len(fitness.log._read_index()) == entries and fitness.admission(DEFAULT_MODEL) == record
    assert app.maintenance_status()["models"] == {DEFAULT_MODEL: "provisional"}


def test_a_model_claim_is_fitness_weighted_on_the_synchronous_path(tmp_path):
    answer = build_app(tmp_path)[0](MODEL_ONLY)["answer"]
    assert answer["fitness_at_use"] == {f"Physics::{DEFAULT_MODEL}": 0.5}   # cold start, earned from here
    assert answer["unadmitted_models"] == []
    (claim,) = [c for c in answer["committed"] if c.get("serving_model") == DEFAULT_MODEL]
    assert claim["fitness_factor"] == 0.5


def test_a_reopened_answer_is_still_fitness_weighted(tmp_path):
    cas = ContentAddressedStore(tmp_path / "cas")
    log = lambda name: CheckpointLog(cas=cas, index_path=tmp_path / f"{name}.txt")
    rep, fitness = ReputabilityStore(log("rep")), ModelFitnessStore(log("fit"))
    admit_model(fitness, DEFAULT_MODEL, rationale="test", admitted_by="owner")
    m = Maintainer(idle=IdleContext(ledger=QuestionLedger(log("ledger")), reputability=rep), log_for=log,
                   belief_graph=BeliefGraphStore(log("graph")), model_fitness=fitness,
                   policy=MaintenancePolicy(idle_every_questions=100, importance_threshold=0.0))
    m.submit_question("q1", MODEL_ONLY)
    m.run()
    for _ in range(10):                                   # the model's own source loses standing
        rep.record_outcome(f"llm:{DEFAULT_MODEL}", "source", "challenged")
    m.submit_question("q2", "is 17 prime?")
    m.run()
    versions = m.ledger.get("q1").versions
    assert len(versions) == 2, "the downgrade should have reopened q1"
    assert "fitness_at_use" in versions[1] and versions[1]["unadmitted_models"] == []
