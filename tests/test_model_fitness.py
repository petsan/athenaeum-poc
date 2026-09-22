from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.model_fitness_store import ModelFitnessStore
from athenaeum_brain.model_fitness import (
    fitness_weight, current_fitness_weight, snapshot_and_record, apply_fitness_to_confidence,
)


def make_store(tmp_path):
    cas = ContentAddressedStore(tmp_path / "cas")
    log = CheckpointLog(cas=cas, index_path=tmp_path / "index.txt")
    return ModelFitnessStore(log)


def test_cold_start_weight_is_exactly_half():
    """Open Question 10: a brand new pairing with zero evidence lands at
    0.5 -- neither too generous nor too conservative."""
    assert fitness_weight(0, 0) == 0.5


def test_weight_moves_toward_one_with_corroboration_but_not_instantly():
    w = fitness_weight(1, 0)
    assert 0.5 < w < 1.0  # smoothed, not an instant jump to 1.0 on one data point


def test_weight_moves_toward_zero_with_challenges():
    w = fitness_weight(0, 1)
    assert 0.0 < w < 0.5


def test_weight_converges_with_more_evidence():
    w_early = fitness_weight(2, 0)
    w_more = fitness_weight(20, 0)
    assert w_more > w_early  # more corroboration, closer to 1.0
    assert w_more < 1.0      # never actually reaches the extreme


def test_current_fitness_weight_reads_from_store(tmp_path):
    store = make_store(tmp_path)
    assert current_fitness_weight(store, "Engineering", "modelA") == 0.5
    store.record_outcome("Engineering", "modelA", "corroborated")
    store.record_outcome("Engineering", "modelA", "corroborated")
    assert current_fitness_weight(store, "Engineering", "modelA") == fitness_weight(2, 0)


def test_fitness_is_tracked_per_agent_model_pairing_independently(tmp_path):
    store = make_store(tmp_path)
    store.record_outcome("Engineering", "modelA", "corroborated")
    store.record_outcome("Physics", "modelA", "challenged")
    assert current_fitness_weight(store, "Engineering", "modelA") == fitness_weight(1, 0)
    assert current_fitness_weight(store, "Physics", "modelA") == fitness_weight(0, 1)


def test_snapshot_and_record_is_non_retroactive(tmp_path):
    """Section 6.3's non-retroactive-attachment discipline: the snapshot
    returned reflects evidence strictly PRIOR to this outcome, not
    including it -- the same guarantee source grading already gives."""
    store = make_store(tmp_path)
    store.record_outcome("Engineering", "modelA", "corroborated")
    weight_at_use = snapshot_and_record(store, "Engineering", "modelA", survived=True)
    assert weight_at_use == fitness_weight(1, 0)  # BEFORE this call's own outcome is recorded
    assert current_fitness_weight(store, "Engineering", "modelA") == fitness_weight(2, 0)  # AFTER


def test_apply_fitness_scales_confidence_without_exceeding_it():
    assert apply_fitness_to_confidence(1.0, 0.5) == 0.5
    assert apply_fitness_to_confidence(0.8, 1.0) == 0.8
    assert apply_fitness_to_confidence(0.8, 0.0) == 0.0
