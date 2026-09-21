import pytest
from athenaeum_body.ingestion import FixtureSource, fetch_and_check, ingest, seed_load, IngestionRejected
from athenaeum_body.storage.content_addressed import ContentAddressedStore

def test_paid_source_rejected(tmp_path):
    s = FixtureSource(url="http://x", content=b"c", license="cc-by", is_paid_or_metered=True)
    check = fetch_and_check(s)
    assert check["accepted"] is False
    assert "paid" in check["reason"]

def test_robots_disallowed_rejected(tmp_path):
    s = FixtureSource(url="http://x", content=b"c", license="cc-by", robots_disallowed=True)
    assert fetch_and_check(s)["accepted"] is False

def test_unlicensed_rejected(tmp_path):
    s = FixtureSource(url="http://x", content=b"c", license="all-rights-reserved")
    assert fetch_and_check(s)["accepted"] is False

def test_legitimate_source_ingested(tmp_path):
    cas = ContentAddressedStore(tmp_path / "cas")
    s = FixtureSource(url="http://x", content=b"classical text", license="public-domain")
    entry = ingest(s, cas)
    assert entry.metadata["license"] == "public-domain"
    assert cas.get(entry.content_hash) == b"classical text"  # durable + tamper-evident

def test_ingest_raises_rather_than_silently_skipping(tmp_path):
    cas = ContentAddressedStore(tmp_path / "cas")
    s = FixtureSource(url="http://x", content=b"c", license="all-rights-reserved")
    with pytest.raises(IngestionRejected):
        ingest(s, cas)

def test_seed_load_skips_rejected_without_failing_the_batch(tmp_path):
    cas = ContentAddressedStore(tmp_path / "cas")
    sources = [
        FixtureSource(url="http://good", content=b"ok", license="public-domain"),
        FixtureSource(url="http://bad", content=b"no", license="all-rights-reserved"),
    ]
    entries = seed_load(sources, cas)
    assert len(entries) == 1
    assert entries[0].id == "http://good"
