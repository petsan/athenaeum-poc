from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.ledger import QuestionLedger
from athenaeum_body.schemas import QuestionLedgerEntry

def make_ledger(tmp_path):
    cas = ContentAddressedStore(tmp_path / "cas")
    log = CheckpointLog(cas=cas, index_path=tmp_path / "index.txt")
    return QuestionLedger(log)

def test_submit_get_versions_never_overwritten(tmp_path):
    ledger = make_ledger(tmp_path)
    ledger.submit(QuestionLedgerEntry(id="q1", importance=0.8))
    ledger.append_version("q1", {"answer": "v1"})
    ledger.append_version("q1", {"answer": "v2 -- reopened and re-derived"})

    q = ledger.get("q1")
    assert q.status == "completed"
    assert len(q.versions) == 2
    assert q.versions[0]["answer"] == "v1"  # first version preserved, not overwritten

def test_list_by_status(tmp_path):
    ledger = make_ledger(tmp_path)
    ledger.submit(QuestionLedgerEntry(id="q1", status="queued"))
    ledger.submit(QuestionLedgerEntry(id="q2", status="queued"))
    assert len(ledger.list_by_status("queued")) == 2
