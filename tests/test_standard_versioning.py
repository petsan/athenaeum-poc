"""Section 6.5: the reputability standard itself is versioned. A new
version governs new decisions only; nothing decided earlier is rewritten;
the full history of standards is kept. Plus 7.2's fourth materiality
trigger: a standard change that alters the grade of a relied-on source."""
import pytest
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.reputability_store import ReputabilityStore, SEED_STANDARD_PARAMS
from athenaeum_body.scheduler.runner import SingleUnitRunner
from athenaeum_brain import model_backed_reasoning
from athenaeum_brain.loop import make_deliberation_unit
from athenaeum_brain.reevaluation import is_material, materiality_inputs

STRICTER = {**SEED_STANDARD_PARAMS, "foundational_min_corroborations": 8}


def _store(tmp_path):
    cas = ContentAddressedStore(tmp_path / "cas")
    return ReputabilityStore(CheckpointLog(cas=cas, index_path=tmp_path / "rep.txt"))


def _corroborate(store, src, n):
    for _ in range(n):
        store.record_outcome(src, "source", "corroborated")


# --- the standard's own history --------------------------------------------

def test_seed_standard_is_version_zero_with_rationale(tmp_path):
    store = _store(tmp_path)
    [seed] = store.standards()
    assert seed["version"] == 0 and seed["params"] == SEED_STANDARD_PARAMS
    assert "seed" in seed["rationale"]


def test_grades_record_the_standard_and_cause_they_were_decided_under(tmp_path):
    store = _store(tmp_path)
    _corroborate(store, "s", 5)
    history = store.grade_history("s")
    assert history[-1]["grade"] == "foundational"
    assert all(h["decided_under"] == 0 and h["cause"] == "evidence" for h in history)
    assert store.current_grade("s")["standard_version"] == 0


def test_amendment_requires_a_rationale_and_valid_params(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        store.adopt_standard(STRICTER, rationale="  ")
    with pytest.raises(ValueError):
        store.adopt_standard({"foundational_min_corroborations": 8}, rationale="missing a key")
    with pytest.raises(ValueError):
        store.adopt_standard({**STRICTER, "rejected_min_challenges": 0}, rationale="zero threshold")
    assert len(store.standards()) == 1  # nothing half-adopted


def test_standard_history_only_grows(tmp_path):
    store = _store(tmp_path)
    store.adopt_standard(STRICTER, rationale="too many early foundational grades overturned")
    store.adopt_standard(SEED_STANDARD_PARAMS, rationale="reverted after review")
    assert [s["version"] for s in store.standards()] == [0, 1, 2]
    assert store.standards()[1]["params"] == STRICTER
    assert store.current_standard()["version"] == 2


# --- non-retroactive regrading ---------------------------------------------

def test_amendment_appends_a_regrade_and_never_rewrites_history(tmp_path):
    store = _store(tmp_path)
    _corroborate(store, "s", 5)
    before = store.grade_history("s")

    result = store.adopt_standard(STRICTER, rationale="foundational bar too low")

    assert result == {"version": 1, "regraded": [
        {"subject_id": "s", "from": "foundational", "to": "provisionally_accepted"}]}
    after = store.grade_history("s")
    assert after[:len(before)] == before  # every earlier decision intact
    assert after[-1] == {"grade": "provisionally_accepted", "version": len(before),
                         "decided_under": 1, "cause": "standard_amendment"}
    assert store.current_grade("s") == {"grade": "provisionally_accepted",
                                        "version": len(before), "standard_version": 1}


def test_source_unaffected_by_amendment_gets_no_new_entry(tmp_path):
    store = _store(tmp_path)
    _corroborate(store, "s", 2)  # provisionally_accepted under both standards
    before = store.grade_history("s")
    assert store.adopt_standard(STRICTER, rationale="r")["regraded"] == []
    assert store.grade_history("s") == before


def test_new_decisions_use_the_standard_in_force(tmp_path):
    store = _store(tmp_path)
    store.adopt_standard(STRICTER, rationale="r")
    _corroborate(store, "fresh", 5)
    assert store.current_grade("fresh")["grade"] == "provisionally_accepted"
    _corroborate(store, "fresh", 3)
    assert store.current_grade("fresh")["grade"] == "foundational"
    assert store.grade_history("fresh")[-1]["decided_under"] == 1


def test_grade_under_reads_any_standard_without_recording(tmp_path):
    store = _store(tmp_path)
    _corroborate(store, "s", 5)
    store.adopt_standard(STRICTER, rationale="r")
    history = store.grade_history("s")
    assert store.grade_under("s", 0) == "foundational"
    assert store.grade_under("s", 1) == "provisionally_accepted"
    assert store.grade_under("never-seen", 1) == "provisionally_accepted"
    assert store.grade_history("s") == history


def test_checkpoints_from_before_versioning_read_as_seed_standard(tmp_path):
    """State persisted by the pre-6.5 store has no 'standards' list and no
    decided_under/cause on its grade entries -- all of it was v0."""
    store = _store(tmp_path)
    store.log.write_checkpoint({
        "tallies": {"old": {"subject_type": "source", "corroborated": 5, "challenged": 0}},
        "grade_versions": {"old": [{"grade": "foundational", "version": 0}]},
        "disputes": [],
    }, label="reputability")
    assert store.current_standard()["version"] == 0
    assert store.grade_history("old") == [{"decided_under": 0, "cause": "evidence",
                                           "grade": "foundational", "version": 0}]
    assert store.adopt_standard(STRICTER, rationale="r")["regraded"][0]["subject_id"] == "old"


# --- 7.2's fourth trigger ---------------------------------------------------

def _answer_citing(store, src):
    return {"source_grades_at_use": {src: store.current_grade(src)}}


def test_standard_driven_change_is_material_below_the_evidence_threshold(tmp_path):
    """A one-band move is below threshold=2, so as an evidence change it
    wouldn't reopen anything -- but a standard amendment that alters a
    relied-on source's grade always does, and is named as the cause."""
    store = _store(tmp_path)
    _corroborate(store, "s", 5)
    answer = _answer_citing(store, "s")
    store.adopt_standard(STRICTER, rationale="r")

    current, prior = materiality_inputs(answer, store)
    assert not is_material(answer, current, threshold=2)["material"]
    result = is_material(answer, current, threshold=2, prior_standard_grades=prior)
    assert result["material"]
    assert "standard amended (v0 -> v1)" in result["reasons"][0]


def test_evidence_driven_change_still_uses_the_threshold(tmp_path):
    """Control: the same one-band move caused by new evidence under an
    unchanged standard stays immaterial at threshold=2."""
    store = _store(tmp_path)
    _corroborate(store, "s", 4)
    answer = _answer_citing(store, "s")
    _corroborate(store, "s", 1)  # evidence tips it to foundational under v0
    current, prior = materiality_inputs(answer, store)
    assert not is_material(answer, current, threshold=2, prior_standard_grades=prior)["material"]


def test_amendment_that_leaves_a_cited_source_alone_is_not_material(tmp_path):
    store = _store(tmp_path)
    _corroborate(store, "s", 2)
    answer = _answer_citing(store, "s")
    store.adopt_standard(STRICTER, rationale="r")
    current, prior = materiality_inputs(answer, store)
    assert not is_material(answer, current, prior_standard_grades=prior)["material"]


def test_loop_snapshots_the_standard_in_force(tmp_path, monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)
    store = _store(tmp_path)
    store.adopt_standard(STRICTER, rationale="r")
    cas = ContentAddressedStore(tmp_path / "loopcas")
    log = CheckpointLog(cas=cas, index_path=tmp_path / "loop.txt")
    runner = SingleUnitRunner(log, shared_state={})
    unit = make_deliberation_unit("is 17 prime?", "q-std", reputability=store)
    while unit.status != "completed":
        runner.run_round(unit)
    answer = log.read_latest()["shared_state"]["answer"]
    assert answer["source_grades_at_use"]["computed:trial_division"]["standard_version"] == 1
