import pytest
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog, ChainIntegrityError

def make_log(tmp_path):
    cas = ContentAddressedStore(tmp_path / "cas")
    return CheckpointLog(cas=cas, index_path=tmp_path / "index.txt")

def test_append_only_and_read_latest(tmp_path):
    log = make_log(tmp_path)
    log.write_checkpoint({"n": 1})
    log.write_checkpoint({"n": 2})
    assert log.read_latest() == {"n": 2}
    assert len(log.all_entries()) == 2

def test_chain_verifies(tmp_path):
    log = make_log(tmp_path)
    for i in range(5):
        log.write_checkpoint({"n": i})
    assert log.verify_chain() is True

def test_tamper_breaks_chain(tmp_path):
    log = make_log(tmp_path)
    for i in range(3):
        log.write_checkpoint({"n": i})
    entries = log.all_entries()
    log.cas.corrupt_for_testing(entries[1].payload_ref, b"not json {{{")
    with pytest.raises(Exception):
        log.verify_chain()

def test_last_good_snapshot_falls_back_past_corruption(tmp_path):
    log = make_log(tmp_path)
    ids = [log.write_checkpoint({"n": i}) for i in range(3)]
    # corrupt only the LATEST entry's own record (not its payload) --
    # last_good_snapshot_id should walk backward to the prior good one
    log.cas.corrupt_for_testing(ids[-1], b"garbage")
    good = log.last_good_snapshot_id()
    assert good == ids[-2]
