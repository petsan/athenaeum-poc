from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.tiered import TieredStore

def test_fallback_and_auto_recovery(tmp_path):
    t2 = ContentAddressedStore(tmp_path / "tier2")
    t3 = ContentAddressedStore(tmp_path / "tier3")
    store = TieredStore(tier2=t2, tier3=t3)

    key = store.put(b"payload")
    assert store.get(key) == b"payload"

    with store.simulate_tier2_outage():
        # written while tier2 down still durable via tier3
        key2 = store.put(b"during outage")
        assert store.get(key2) == b"during outage"

    # tier2 reachable again -- no manual failback needed
    assert store.get(key2) == b"during outage"
    assert store.tier2_reachable is True
