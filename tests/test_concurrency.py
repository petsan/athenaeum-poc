import pytest
from athenaeum_body.concurrency import VersionedStore, ConflictError

def test_expected_version_conflict_then_retry_succeeds():
    store = VersionedStore()
    store.put("k", "v1", expected_version=0)
    with pytest.raises(ConflictError):
        store.put("k", "v2", expected_version=0)  # stale version
    val, ver = store.get("k")
    store.put("k", "v2", expected_version=ver)  # retry with fresh version
    assert store.get("k") == ("v2", 2)

def test_idempotency_key_dedup():
    store = VersionedStore()
    r1 = store.put("k", "v1", expected_version=0, idempotency_key="req-1")
    r2 = store.put("k", "v1", expected_version=0, idempotency_key="req-1")  # retried
    assert r1 == r2
    _, ver = store.get("k")
    assert ver == 1  # only applied once, not twice
