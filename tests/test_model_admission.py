"""Section 6.7: the model admission gate, and (agent, model) fitness as a
synthesis-time weight with non-retroactive attachment."""
import pytest
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.scheduler.runner import SingleUnitRunner
from athenaeum_body.model_fitness_store import ModelFitnessStore
from athenaeum_brain import model_backed_reasoning
from athenaeum_brain.claims import Claim
from athenaeum_brain.loop import make_deliberation_unit
from athenaeum_brain.rounds import synthesis_round
from athenaeum_brain.model_fitness import (
    admit_model, model_standing, fitness_factor, rank_models_for, ESTABLISHED_AFTER,
)

MODEL_QUESTION = "what force holds the moon in orbit?"  # Physics is routed, finds nothing deterministic


@pytest.fixture
def store(tmp_path):
    return ModelFitnessStore(CheckpointLog(cas=ContentAddressedStore(tmp_path / "cas"),
                                           index_path=tmp_path / "fit.txt"))


@pytest.fixture
def stub_model(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: "gravity holds the moon in orbit")


def _admit(store, model="olmo3-7b"):
    return admit_model(store, model, rationale="evaluated on the workbench", admitted_by="owner")


def _claim(agent, serving_model, confidence=0.6):
    return Claim(question_id="q", round=1, issuing_agent=agent, statement=f"{agent}/{serving_model}",
                 claim_type="empirical", confidence=confidence, defeat_condition="x",
                 jurisdiction_check=True, supporting_provenance=["s"], serving_model=serving_model)


# --- admission --------------------------------------------------------------------

def test_admission_requires_a_rationale(store):
    with pytest.raises(ValueError):
        admit_model(store, "m", rationale=" ", admitted_by="owner")
    assert store.admission("m") is None


def test_admission_is_recorded_once_and_never_rewritten(store):
    first = _admit(store)
    again = admit_model(store, "olmo3-7b", rationale="a different story", admitted_by="someone-else")
    assert again == first == store.admission("olmo3-7b")


def test_standing_is_earned_through_outcomes_not_admission(store):
    assert model_standing(store, "olmo3-7b") == "not_admitted"
    _admit(store)
    assert model_standing(store, "olmo3-7b") == "provisional"
    for i in range(ESTABLISHED_AFTER):
        store.record_outcome("Physics" if i % 2 else "Mathematics", "olmo3-7b", "corroborated")
    assert model_standing(store, "olmo3-7b") == "established"


# --- the factor -------------------------------------------------------------------

def test_deterministic_claims_are_not_subject_to_fitness(store):
    assert fitness_factor(store, "Mathematics", None) == 1.0
    assert fitness_factor(store, "Engineering", "deterministic:sandbox_execution") == 1.0


def test_unadmitted_model_gets_zero_and_admitted_starts_at_cold_start(store):
    assert fitness_factor(store, "Physics", "olmo3-7b") == 0.0
    _admit(store)
    assert fitness_factor(store, "Physics", "olmo3-7b") == 0.5
    store.record_outcome("Physics", "olmo3-7b", "corroborated")
    assert fitness_factor(store, "Physics", "olmo3-7b") == pytest.approx(2 / 3)
    assert fitness_factor(store, "Theology", "olmo3-7b") == 0.5  # fitness is per (agent, model)


def test_ranking_orders_admitted_models_by_fitness(store):
    for m in ("a", "b"):
        _admit(store, m)
    store.record_outcome("Physics", "b", "corroborated")
    store.record_outcome("Physics", "a", "challenged")
    ranked = rank_models_for(store, "Physics", ["a", "never-admitted", "b"])
    assert [r["model"] for r in ranked] == ["b", "a"]


# --- synthesis --------------------------------------------------------------------

def test_fitness_multiplies_into_the_evidence_weight_and_leaves_confidence_alone(store):
    _admit(store)
    model_claim, det_claim = _claim("Physics", "olmo3-7b"), _claim("Mathematics", None, confidence=0.9)
    result = synthesis_round([model_claim, det_claim], [],
                             grade_lookup=lambda s: "foundational",
                             fitness_lookup=lambda a, m: fitness_factor(store, a, m))
    by_agent = {c.issuing_agent: c for c in result["committed"]}
    assert by_agent["Physics"].confidence == 0.6
    assert by_agent["Physics"].weighted_confidence == pytest.approx(0.6 * 1.0 * 0.5)
    assert by_agent["Mathematics"].weighted_confidence == pytest.approx(0.9)


def test_unadmitted_model_claim_is_still_committed_only_weighted_to_zero(store):
    result = synthesis_round([_claim("Physics", "olmo3-7b")], [],
                             fitness_lookup=lambda a, m: fitness_factor(store, a, m))
    [c] = result["committed"]
    assert c.fitness_factor == 0.0 and c.weighted_confidence == 0.0


# --- through the loop -------------------------------------------------------------

def _run(tmp_path, name, store):
    log = CheckpointLog(cas=ContentAddressedStore(tmp_path / f"cas-{name}"), index_path=tmp_path / f"{name}.txt")
    runner = SingleUnitRunner(log, shared_state={})
    unit = make_deliberation_unit(MODEL_QUESTION, name, model_fitness=store)
    while unit.status != "completed":
        runner.run_round(unit)
    return log.read_latest()["shared_state"]["answer"]


def test_loop_flags_an_unadmitted_model_and_records_nothing_for_it(tmp_path, store, stub_model):
    answer = _run(tmp_path, "q1", store)
    assert answer["unadmitted_models"] == ["olmo3-7b"]
    assert answer["fitness_at_use"] == {"Physics::olmo3-7b": 0.0}
    assert store.tally("Physics", "olmo3-7b") == {"corroborated": 0, "challenged": 0}


def test_loop_attaches_fitness_at_use_non_retroactively(tmp_path, store, stub_model):
    _admit(store)
    first = _run(tmp_path, "q1", store)
    second = _run(tmp_path, "q2", store)
    assert first["fitness_at_use"] == {"Physics::olmo3-7b": 0.5}  # before its own outcome
    assert second["fitness_at_use"]["Physics::olmo3-7b"] == pytest.approx(2 / 3)
    assert store.tally("Physics", "olmo3-7b") == {"corroborated": 2, "challenged": 0}
    assert first["unadmitted_models"] == []
