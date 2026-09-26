"""Section 6.4: Logic-chaired dispute resolution, including the
independence check that catches circular corroboration (Section 8)."""
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.reputability_store import ReputabilityStore
from athenaeum_body.ingestion import FixtureSource, ingest
from athenaeum_brain.claims import Claim
from athenaeum_brain.dispute_resolution import check_independence, citation_map, resolve_dispute
from athenaeum_brain.consolidation import should_promote_to_c
from athenaeum_brain.evaluation import run_adversarial_suite


def _store(tmp_path):
    cas = ContentAddressedStore(tmp_path / "cas")
    return ReputabilityStore(CheckpointLog(cas=cas, index_path=tmp_path / "rep.txt"))


def _claim(agent, statement, sources, claim_type="empirical", confidence=0.8):
    return Claim(question_id="d", round=1, issuing_agent=agent, statement=statement,
                 claim_type=claim_type, confidence=confidence, defeat_condition="x",
                 jurisdiction_check=True, supporting_provenance=sources)


# --- 6.4.2 independence --------------------------------------------------

def test_sources_with_no_citations_are_all_independent():
    r = check_independence(["a", "b", "c"], {})
    assert r["independent_count"] == 3 and r["circular"] == []


def test_direct_citation_collapses_to_one_line():
    assert check_independence(["a", "b"], {"b": ["a"]})["independent_count"] == 1


def test_shared_upstream_not_in_the_list_still_collapses():
    """Two reports both derived from the same wire story are one line of
    evidence even when the wire story itself isn't cited on the claim."""
    r = check_independence(["a", "b"], {"a": ["wire"], "b": ["wire"]})
    assert r["independent_count"] == 1


def test_transitive_citation_collapses():
    r = check_independence(["a", "b"], {"a": ["x"], "x": ["b"]})
    assert r["independent_count"] == 1


def test_unrelated_source_stays_separate():
    r = check_independence(["a", "b", "c"], {"b": ["a"]})
    assert r["independent_count"] == 2
    assert sorted(map(sorted, r["groups"])) == [["a", "b"], ["c"]]


def test_citation_cycle_is_named_circular_and_terminates():
    cites = {"a": ["b"], "b": ["c"], "c": ["a"]}
    r = check_independence(["a", "b", "c", "d"], cites)
    assert r["independent_count"] == 2
    assert sorted(r["circular"]) == ["a", "b", "c"]


def test_duplicate_sources_count_once():
    assert check_independence(["a", "a"], {})["independent_count"] == 1


# --- citation data from ingestion -----------------------------------------

def test_ingested_cites_round_trip_into_citation_map(tmp_path):
    cas = ContentAddressedStore(tmp_path / "cas")
    a = ingest(FixtureSource(url="https://ex.org/a", content=b"A", license="public-domain"), cas)
    b = ingest(FixtureSource(url="https://ex.org/b", content=b"B", license="public-domain",
                             cites=["https://ex.org/a"]), cas)
    assert "cites" not in a.metadata  # unchanged shape when there's nothing to record
    assert citation_map([a, b]) == {"https://ex.org/a": [], "https://ex.org/b": ["https://ex.org/a"]}


# --- 6.4 full procedure ---------------------------------------------------

def test_circular_side_loses_to_independent_side_and_ruling_is_logged(tmp_path):
    store = _store(tmp_path)
    cites = {"blog:1": ["blog:2"], "blog:2": ["blog:1"]}
    sides = {
        "affirms": [_claim("Physics", "X is true", ["blog:1", "blog:2"])],
        "denies": [_claim("Physics", "X is false", ["journal:a", "archive:b"])],
    }
    record = resolve_dispute("topic:X", sides, reputability=store, cites=cites)

    assert record["sides"]["affirms"]["strength"] == 1
    assert record["sides"]["denies"]["strength"] == 2
    assert record["ruling"] == "favours denies"
    assert "circular citation" in record["rationale"]
    assert record["chaired_by"] == "Logic" and record["reversible_on_new_evidence"]

    logged = store.disputes_for("topic:X")
    assert len(logged) == 1 and logged[0]["ruling"] == "favours denies"
    assert set(logged[0]["claim_ids"]) == {c.claim_id for cs in sides.values() for c in cs}


def test_equal_strength_is_unresolved_not_a_manufactured_winner(tmp_path):
    sides = {"a": [_claim("Physics", "p", ["s1"])], "b": [_claim("Physics", "not p", ["s2"])]}
    record = resolve_dispute("topic:tie", sides, reputability=_store(tmp_path))
    assert record["ruling"].startswith("unresolved")


def test_rejected_sources_add_no_strength(tmp_path):
    store = _store(tmp_path)
    for _ in range(3):
        store.record_outcome("s-bad", "source", "challenged")
    sides = {"a": [_claim("Physics", "p", ["s-bad", "s-worse"])],
             "b": [_claim("Physics", "not p", ["s-ok"])]}
    for _ in range(3):
        store.record_outcome("s-worse", "source", "challenged")
    record = resolve_dispute("topic:rej", sides, reputability=store)
    assert record["sides"]["a"]["strength"] == 0
    assert record["ruling"] == "favours b"


def test_category_error_is_found_by_philosophy_not_logic_and_excluded(tmp_path):
    """An 'empirical' claim that smuggles in an ought is excluded from the
    weighing -- and the finding comes from Philosophy's own cross-exam."""
    sides = {
        "ban": [_claim("Physics", "the data shows we should ban it", ["s1", "s2"])],
        "allow": [_claim("Physics", "no measured harm at these doses", ["s3"])],
    }
    record = resolve_dispute("topic:cat", sides, reputability=_store(tmp_path))
    errors = record["sides"]["ban"]["category_errors"]
    assert [e["reviewer"] for e in errors] == ["Philosophy"]
    assert record["sides"]["ban"]["strength"] == 0
    assert record["ruling"] == "favours allow"


def test_overconfident_traditional_claim_is_flagged_by_theology(tmp_path):
    sides = {"t": [_claim("WorldNews", "the tradition holds X", ["corpus:x"],
                          claim_type="traditional", confidence=1.0)]}
    record = resolve_dispute("topic:trad", sides, reputability=_store(tmp_path))
    assert [e["reviewer"] for e in record["sides"]["t"]["category_errors"]] == ["Theology"]


def test_ruling_never_edits_a_grade(tmp_path):
    """No unilateral blacklist authority: a losing side's sources keep the
    grade they had; only accumulated outcomes (6.2) move grades."""
    store = _store(tmp_path)
    before = store.current_grade("blog:1")
    resolve_dispute("topic:g", {"a": [_claim("Physics", "p", ["blog:1"])],
                                "b": [_claim("Physics", "q", ["j:1", "j:2"])]}, reputability=store)
    assert store.current_grade("blog:1") == before


# --- consolidation now counts independent sources ------------------------

def test_consolidation_does_not_promote_on_circular_corroboration():
    entry = {"cycles": 5, "sources": ["a", "b"], "confidence_history": [0.9] * 5}
    assert should_promote_to_c(entry)["eligible"]  # no citation data: still two
    verdict = should_promote_to_c(entry, cites={"b": ["a"]})
    assert not verdict["eligible"]
    assert "only 1/2 independent sources" in verdict["reasons"][0]


def test_adversarial_suite_covers_circular_corroboration():
    suite = run_adversarial_suite()
    assert suite["results"]["circular_corroboration"] is True
    assert suite["total"] == 7
