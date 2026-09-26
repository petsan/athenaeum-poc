"""Owner decision 8 (batch 10, Phase AQ): one checkpoint log per question.
A write costs one question, not the whole ledger; the old single-log layout
is migrated on first open, idempotently, and its history is kept."""
import pytest
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.ledger import QuestionLedger, LAYOUT
from athenaeum_body.schemas import QuestionLedgerEntry


@pytest.fixture
def mk(tmp_path):
    cas = ContentAddressedStore(tmp_path / "cas")
    return lambda name="index": CheckpointLog(cas=cas, index_path=tmp_path / f"{name}.txt")


def answered(ledger, qid, n=1):
    ledger.submit(QuestionLedgerEntry(id=qid, importance=0.5))
    for i in range(n):
        ledger.append_version(qid, {"question": f"{qid}?", "committed": [{"statement": f"s{i}"}]})


def payload_bytes(log):
    return log.cas._path_for(log.all_entries()[-1].payload_ref).stat().st_size


def test_each_question_has_its_own_log_and_the_index_lists_them_in_order(mk):
    ledger = QuestionLedger(mk())
    for qid in ("q-2", "q-1", "q-3"):
        answered(ledger, qid)
    assert ledger.log.read_latest() == {"layout": LAYOUT, "ids": ["q-2", "q-1", "q-3"]}
    assert list(ledger._state()["questions"]) == ["q-2", "q-1", "q-3"]
    assert ledger.count() == 3
    before = {q: len(ledger._log_for(q)._read_index()) for q in ("q-1", "q-2", "q-3")}
    index_before = len(ledger.log._read_index())
    ledger.set_status("q-2", "archived")
    after = {q: len(ledger._log_for(q)._read_index()) for q in ("q-1", "q-2", "q-3")}
    assert after == {**before, "q-2": before["q-2"] + 1}           # only q-2's log grew
    assert len(ledger.log._read_index()) == index_before            # and not the index


def test_a_write_costs_one_question_however_many_there_are(mk):
    ledger = QuestionLedger(mk())
    answered(ledger, "q-1", n=3)
    ledger.update_importance("q-1", 0.4)
    small = payload_bytes(ledger._log_for("q-1"))
    for i in range(2, 40):
        answered(ledger, f"q-{i}", n=3)
    ledger.update_importance("q-1", 0.6)
    assert payload_bytes(ledger._log_for("q-1")) == small           # unchanged by 38 other questions


def legacy_ledger(log, questions):
    """What a layout-1 ledger looked like: every checkpoint held every question."""
    state = {"questions": {}}
    for n, (qid, versions, status) in enumerate(questions):
        state["questions"][qid] = QuestionLedgerEntry(id=qid, status="queued", created_at=1000.0 + n).to_dict()
        log.write_checkpoint(state, label="question_ledger")
        state["questions"][qid]["versions"] = versions
        state["questions"][qid]["status"] = status
        log.write_checkpoint(state, label="question_ledger")


LEGACY = [("prime", [{"question": "is 17 prime?", "committed": [{"statement": "17 is prime"}]}], "completed"),
          ("round", [{"question": "round 2.5?"}, {"question": "round 2.5?", "diff": {}}], "completed"),
          ("pending", [], "suspended")]


def test_a_layout_1_ledger_is_migrated_with_nothing_lost(mk):
    old = mk()
    legacy_ledger(old, LEGACY)
    legacy_state, legacy_entries = old.read_latest(), len(old._read_index())
    ledger = QuestionLedger(mk())
    assert ledger._state() == legacy_state                           # every question, in order, intact
    assert ledger.get("round").versions[1] == {"question": "round 2.5?", "diff": {}}
    assert ledger.get("pending").status == "suspended"
    index = ledger.log.read_latest()
    assert index["layout"] == LAYOUT and index["ids"] == ["prime", "round", "pending"]
    history = ledger.log.all_entries()
    assert len(history) == legacy_entries + 1                        # the old snapshots are all still there
    assert index["migrated_from"] == history[-2].snapshot_id
    assert ledger.log.verify_chain()
    ledger.append_version("prime", {"question": "is 17 prime?", "note": "after migration"})
    assert len(QuestionLedger(mk()).get("prime").versions) == 2     # and it carries on as layout 2


def test_migration_is_idempotent_and_resumes_if_interrupted(mk, tmp_path):
    old = mk()
    legacy_ledger(old, LEGACY)
    legacy = old.read_latest()
    # a migration that died after writing its first question, before the index
    probe = QuestionLedger.__new__(QuestionLedger)
    probe._dir = tmp_path / "index.questions"
    CheckpointLog(cas=old.cas, index_path=probe._path_for("prime")).write_checkpoint(legacy["questions"]["prime"])
    ledger = QuestionLedger(mk())                                    # resumes
    assert ledger._state() == legacy
    assert len(ledger._log_for("prime")._read_index()) == 1          # the finished question isn't written twice
    index_entries = len(ledger.log._read_index())
    QuestionLedger(mk())                                             # and opening again changes nothing
    assert len(ledger.log._read_index()) == index_entries


def test_two_ledger_objects_over_the_same_files_stay_consistent(mk):
    a, b = QuestionLedger(mk()), QuestionLedger(mk())
    answered(a, "q-1")
    assert b.get("q-1").versions == a.get("q-1").versions            # b wasn't told; its cache is keyed on the log
    b.set_status("q-1", "archived")
    assert a.get("q-1").status == "archived"


def test_a_batch_reads_its_own_writes_and_writes_once(mk):
    ledger = QuestionLedger(mk())
    ledger.submit(QuestionLedgerEntry(id="q-1"))
    with ledger.batch("q-1"):
        ledger.append_version("q-1", {"question": "?"})
        assert ledger.get("q-1").status == "completed"               # visible inside the batch
        ledger.update_importance("q-1", 0.7)
    assert len(ledger._log_for("q-1")._read_index()) == 2            # submit + one batched write
    assert ledger.get("q-1").importance == 0.7


def test_awkward_ids_get_distinct_files_and_unknown_ids_create_nothing(mk, tmp_path):
    ledger = QuestionLedger(mk())
    for qid in ("a/b:c", "a_b_c", "a:b/c"):
        ledger.submit(QuestionLedgerEntry(id=qid))
    assert len({ledger._path_for(q) for q in ("a/b:c", "a_b_c", "a:b/c")}) == 3
    assert [ledger.get(q).id for q in ("a/b:c", "a_b_c", "a:b/c")] == ["a/b:c", "a_b_c", "a:b/c"]
    files_before = sorted(p.name for p in ledger._dir.iterdir())
    assert ledger.get("never-submitted") is None
    assert sorted(p.name for p in ledger._dir.iterdir()) == files_before


def test_the_api_opens_a_layout_1_data_dir(tmp_path, monkeypatch):
    from athenaeum_body.api import build_app
    from athenaeum_brain import model_backed_reasoning
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)
    cas = ContentAddressedStore(tmp_path / "cas")
    legacy_ledger(CheckpointLog(cas=cas, index_path=tmp_path / "index.txt"), LEGACY)
    app = build_app(tmp_path)
    assert [q["id"] for q in app[1]("summary")] == ["prime", "round", "pending"]
    assert app.submit_async("is 19 prime?")["id"] == "q-4"           # numbering continues past them
