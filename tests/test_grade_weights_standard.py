"""Synthesis's grade weights (§4.1) are part of the versioned reputability
standard (§6.5): seeded with today's values, amendable with validation,
used as of time of use, and never retroactive."""
import pytest
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.scheduler.runner import SingleUnitRunner
from athenaeum_body.reputability_store import ReputabilityStore, SEED_STANDARD_PARAMS, SEED_GRADE_WEIGHTS
from athenaeum_brain import model_backed_reasoning
from athenaeum_brain.loop import make_deliberation_unit
from athenaeum_brain.rounds import GRADE_WEIGHT
from athenaeum_brain.reevaluation import is_material, materiality_inputs

HALF_PROVISIONAL = {**SEED_GRADE_WEIGHTS, "provisionally_accepted": 0.5}


@pytest.fixture(autouse=True)
def _no_model_fallback(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)


def _store(tmp_path, name="rep"):
    return ReputabilityStore(CheckpointLog(cas=ContentAddressedStore(tmp_path / "cas"),
                                           index_path=tmp_path / f"{name}.txt"))


def test_the_seed_standard_carries_todays_weights(tmp_path):
    assert _store(tmp_path).current_standard()["grade_weights"] == SEED_GRADE_WEIGHTS == GRADE_WEIGHT


def test_standards_saved_before_weights_existed_read_as_seed(tmp_path):
    store = _store(tmp_path)
    store.log.write_checkpoint({"tallies": {}, "grade_versions": {}, "disputes": [],
                                "standards": [{"version": 0, "params": dict(SEED_STANDARD_PARAMS),
                                               "rationale": "old"}]}, label="reputability")
    assert store.current_standard()["grade_weights"] == SEED_GRADE_WEIGHTS


def test_an_amendment_inherits_weights_unless_it_sets_them(tmp_path):
    store = _store(tmp_path)
    store.adopt_standard(SEED_STANDARD_PARAMS, rationale="thresholds only")
    assert store.current_standard()["grade_weights"] == SEED_GRADE_WEIGHTS
    store.adopt_standard(SEED_STANDARD_PARAMS, rationale="weigh provisional sources less",
                         grade_weights=HALF_PROVISIONAL)
    assert store.current_standard()["grade_weights"] == HALF_PROVISIONAL
    assert store.standards()[1]["grade_weights"] == SEED_GRADE_WEIGHTS  # history kept


@pytest.mark.parametrize("weights", [
    {"foundational": 1.0, "contested": 0.4, "rejected": 0.0},                    # a grade missing
    {**SEED_GRADE_WEIGHTS, "foundational": 1.5},                                # out of range
    {**SEED_GRADE_WEIGHTS, "contested": 0.9},                                    # contested above provisional
])
def test_invalid_weights_are_refused_and_nothing_is_half_adopted(tmp_path, weights):
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        store.adopt_standard(SEED_STANDARD_PARAMS, rationale="bad", grade_weights=weights)
    assert len(store.standards()) == 1


def test_a_weights_only_amendment_regrades_nothing(tmp_path):
    store = _store(tmp_path)
    for _ in range(5):
        store.record_outcome("s", "source", "corroborated")
    assert store.adopt_standard(SEED_STANDARD_PARAMS, rationale="w", grade_weights=HALF_PROVISIONAL)["regraded"] == []


def _answer(tmp_path, rep):
    log = CheckpointLog(cas=ContentAddressedStore(tmp_path / "ucas"), index_path=tmp_path / "u.txt")
    runner = SingleUnitRunner(log, shared_state={})
    unit = make_deliberation_unit("is 17 prime?", "q", reputability=rep)
    while unit.status != "completed":
        runner.run_round(unit)
    return log.read_latest()["shared_state"]["answer"]


def test_synthesis_uses_the_weights_of_the_standard_in_force(tmp_path):
    rep = _store(tmp_path)
    rep.adopt_standard(SEED_STANDARD_PARAMS, rationale="w", grade_weights=HALF_PROVISIONAL)
    [claim] = _answer(tmp_path, rep)["committed"]
    assert claim["reputability_factor"] == 0.5  # ungraded -> provisional -> 0.5 under v1
    assert claim["weighted_confidence"] == 0.5


def test_a_weights_only_amendment_is_not_material(tmp_path):
    """§7.2's fourth trigger is about a standard change that alters a
    relied-on source's GRADE; a weights-only amendment alters none."""
    rep = _store(tmp_path)
    answer = _answer(tmp_path, rep)
    rep.adopt_standard(SEED_STANDARD_PARAMS, rationale="w", grade_weights=HALF_PROVISIONAL)
    current, prior = materiality_inputs(answer, rep)
    assert is_material(answer, current, prior_standard_grades=prior)["material"] is False
