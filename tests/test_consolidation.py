from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.consolidation_store import ConsolidationStore
from athenaeum_brain.consolidation import record_survival, should_promote_to_c, compact, expand

def make_store(tmp_path):
    log = CheckpointLog(cas=ContentAddressedStore(tmp_path / "log_cas"), index_path=tmp_path / "index.txt")
    archive = ContentAddressedStore(tmp_path / "archive")
    return ConsolidationStore(log, archive)

def claim(statement="17 is prime", confidence=1.0, sources=("computed:trial_division",)):
    return {"statement": statement, "confidence": confidence, "supporting_provenance": list(sources)}

def test_survival_accumulates_cycles_and_sources(tmp_path):
    store = make_store(tmp_path)
    record_survival(store, "k1", claim(sources=("srcA",)))
    entry = record_survival(store, "k1", claim(sources=("srcB",)))
    assert entry["cycles"] == 2
    assert set(entry["sources"]) == {"srcA", "srcB"}

def test_not_eligible_below_thresholds(tmp_path):
    store = make_store(tmp_path)
    entry = record_survival(store, "k1", claim())
    verdict = should_promote_to_c(entry, min_cycles=5, min_sources=2)
    assert verdict["eligible"] is False
    assert any("cycles" in r for r in verdict["reasons"])

def test_declining_confidence_blocks_promotion_even_if_counts_met(tmp_path):
    """The specific rule Section 10.2 calls out: a claim can meet the
    cycle/source thresholds and STILL be excluded if its confidence has
    been eroding, even though it hasn't been overturned yet."""
    store = make_store(tmp_path)
    for conf, src in [(1.0, "a"), (0.9, "b"), (0.8, "c"), (0.7, "d"), (0.6, "e")]:
        entry = record_survival(store, "k1", claim(confidence=conf, sources=(src,)))
    verdict = should_promote_to_c(entry, min_cycles=5, min_sources=2)
    assert verdict["eligible"] is False
    assert "declining" in verdict["reasons"][0]

def test_eligible_when_all_three_criteria_met(tmp_path):
    store = make_store(tmp_path)
    for conf, src in [(0.8, "a"), (0.85, "b"), (0.9, "c"), (0.9, "d"), (1.0, "e")]:
        entry = record_survival(store, "k1", claim(confidence=conf, sources=(src,)))
    verdict = should_promote_to_c(entry, min_cycles=5, min_sources=2)
    assert verdict["eligible"] is True
    assert verdict["reasons"] == []

def test_compact_archives_full_trace_and_returns_tier_c_node(tmp_path):
    store = make_store(tmp_path)
    for conf, src in [(0.8, "a"), (0.9, "b")]:
        record_survival(store, "k1", claim(confidence=conf, sources=(src,)))
    node = compact(store, "k1")
    assert node["tier"] == "C"
    assert node["archive_ref"] is not None
    # the active entry is now the compact form, not the full trace
    assert store.get("k1")["tier"] == "C"

def test_expand_recovers_the_full_trace_after_compaction(tmp_path):
    store = make_store(tmp_path)
    record_survival(store, "k1", claim(confidence=0.8, sources=("a",)))
    record_survival(store, "k1", claim(confidence=0.9, sources=("b",)))
    compact(store, "k1")
    full = expand(store, "k1")
    assert full["confidence_history"] == [0.8, 0.9]  # nothing lost by compaction
    assert set(full["sources"]) == {"a", "b"}

def test_nothing_is_ever_deleted(tmp_path):
    """Section 10.4: compacting changes what's resident, never what's
    recoverable -- the archived object is still readable via the CAS
    directly, independent of the tracker state."""
    store = make_store(tmp_path)
    record_survival(store, "k1", claim())
    node = compact(store, "k1")
    directly_from_archive = store.archive.get_json(node["archive_ref"])
    assert directly_from_archive["statement"] == "17 is prime"
