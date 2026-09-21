"""Task 16: ingestion runs as an ordinary, resource-scheduled work unit --
same engine as everything else, no special-casing."""
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.scheduler.work_unit import WorkUnit, RoundResult
from athenaeum_body.scheduler.runner import SingleUnitRunner
from athenaeum_body.ingestion import FixtureSource, ingest, IngestionRejected

def make_ingestion_handler(source: FixtureSource, cas: ContentAddressedStore):
    def handler(state, round_index):
        try:
            entry = ingest(source, cas)
            return RoundResult(proposed_writes={"result": {"ok": True, "entry": entry.to_dict()}}, done=True)
        except IngestionRejected as e:
            return RoundResult(proposed_writes={"result": {"ok": False, "reason": str(e)}}, done=True)
    return handler

def test_ingestion_work_unit_runs_on_ordinary_scheduler(tmp_path):
    cas = ContentAddressedStore(tmp_path / "source_cas")
    log = CheckpointLog(cas=ContentAddressedStore(tmp_path / "log_cas"), index_path=tmp_path / "index.txt")
    runner = SingleUnitRunner(log, shared_state={})
    source = FixtureSource(url="http://x", content=b"classical text", license="public-domain")
    unit = WorkUnit(id="ingest-1", round_handler=make_ingestion_handler(source, cas))
    runner.run_round(unit)
    assert unit.status == "completed"
    assert log.read_latest()["shared_state"]["result"]["ok"] is True
