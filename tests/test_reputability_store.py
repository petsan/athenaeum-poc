from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.reputability_store import ReputabilityStore

def make_store(tmp_path):
    cas = ContentAddressedStore(tmp_path / "cas")
    log = CheckpointLog(cas=cas, index_path=tmp_path / "index.txt")
    return ReputabilityStore(log)

def test_ungraded_source_defaults_to_provisionally_accepted(tmp_path):
    store = make_store(tmp_path)
    assert store.current_grade("src1")["grade"] == "provisionally_accepted"

def test_repeated_corroboration_reaches_foundational(tmp_path):
    store = make_store(tmp_path)
    for _ in range(5):
        store.record_outcome("src1", "source", "corroborated")
    assert store.current_grade("src1")["grade"] == "foundational"

def test_challenges_move_toward_contested_then_rejected(tmp_path):
    store = make_store(tmp_path)
    store.record_outcome("src1", "source", "challenged")
    store.record_outcome("src1", "source", "challenged")
    assert store.current_grade("src1")["grade"] == "contested"
    store.record_outcome("src1", "source", "challenged")
    assert store.current_grade("src1")["grade"] == "rejected"  # 0 corroboration, 3+ challenges

def test_grade_version_increments_only_on_actual_change(tmp_path):
    store = make_store(tmp_path)
    store.record_outcome("src1", "source", "corroborated")
    v1 = store.current_grade("src1")["version"]
    store.record_outcome("src1", "source", "corroborated")  # still provisionally_accepted
    v2 = store.current_grade("src1")["version"]
    assert v1 == v2  # no new version if the grade didn't actually change

def test_dispute_log_is_append_only_and_queryable(tmp_path):
    store = make_store(tmp_path)
    store.log_dispute("src1", ["claim-1", "claim-2"], "conflicting corroboration counts", "downgraded to contested")
    disputes = store.disputes_for("src1")
    assert len(disputes) == 1
    assert disputes[0]["ruling"] == "downgraded to contested"
