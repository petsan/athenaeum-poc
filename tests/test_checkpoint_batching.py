"""Batch 6, Phase AB: storage growth. CheckpointLog.batch gives one logical
operation one checkpoint (and makes it atomic); the Belief Graph,
consolidation, fidelity, calibration and the ledger use it; the Maintainer's
checkpoints no longer carry harvested units' scratch or runner records."""
import importlib.util
from pathlib import Path
import pytest
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.belief_graph_store import BeliefGraphStore
from athenaeum_body.ledger import QuestionLedger
from athenaeum_body.reputability_store import ReputabilityStore
from athenaeum_body.consolidation_store import ConsolidationStore
from athenaeum_body.domain_fidelity_store import DomainFidelityStore
from athenaeum_body.calibration_store import CalibrationStore
from athenaeum_body.ingestion import FixtureSource, ingest
from athenaeum_brain import model_backed_reasoning
from athenaeum_brain.belief_graph import record_answer
from athenaeum_brain.idle_evolution import IdleContext
from athenaeum_brain.maintenance import Maintainer, MaintenancePolicy


@pytest.fixture(autouse=True)
def _no_model_fallback(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)


@pytest.fixture
def mk(tmp_path):
    cas = ContentAddressedStore(tmp_path / "cas")
    return lambda name: CheckpointLog(cas=cas, index_path=tmp_path / f"{name}.txt")


def entries(log):
    return len(log._read_index())


# --- CheckpointLog.batch ------------------------------------------------------------

def test_a_batch_writes_one_entry_and_reads_its_own_writes(mk):
    log = mk("l")
    log.write_checkpoint({"n": 0})
    with log.batch():
        for i in range(1, 4):
            state = log.read_latest()
            assert state["n"] == i - 1          # sees the pending state
            state["n"] = i
            log.write_checkpoint(state)
        assert entries(log) == 1                # nothing written yet
        assert mk("l").read_latest() == {"n": 0}  # another reader sees only what's written
    assert entries(log) == 2 and log.read_latest() == {"n": 3}
    assert log.verify_chain()


def test_a_failed_batch_writes_nothing(mk):
    log = mk("l")
    log.write_checkpoint({"n": 0})
    with pytest.raises(RuntimeError):
        with log.batch():
            log.write_checkpoint({"n": 1})
            raise RuntimeError("half-way")
    assert entries(log) == 1 and log.read_latest() == {"n": 0}
    log.write_checkpoint({"n": 2})              # and the log works normally afterwards
    assert log.read_latest() == {"n": 2}


def test_batches_nest_and_reads_are_copies(mk):
    log = mk("l")
    with log.batch():
        log.write_checkpoint({"items": []})
        with log.batch():
            s = log.read_latest(); s["items"].append(1); log.write_checkpoint(s)
        assert entries(log) == 0                # the inner block doesn't write
        log.read_latest()["items"].append("not written")  # mutating a read changes nothing stored
    assert entries(log) == 1 and log.read_latest() == {"items": [1]}


def test_an_empty_batch_writes_nothing(mk):
    log = mk("l")
    with log.batch():
        log.read_latest()
    assert entries(log) == 0


# --- one operation, one checkpoint ------------------------------------------------------

def test_recording_an_answer_or_a_source_is_one_graph_checkpoint(mk, tmp_path):
    graph = BeliefGraphStore(mk("g"))
    claims = [{"statement": f"s{i}", "issuing_agent": "Mathematics", "claim_type": "formal",
               "supporting_provenance": [f"src{i}", "shared"]} for i in range(3)]
    record_answer(graph, "q1", {"question": "q", "committed": claims, "dissent": []}, version=0)
    assert entries(graph.log) == 1 and len(graph.nodes()) == 1 + 1 + 3 + 4
    ingest(FixtureSource(url="a", content=b"x", license="cc-by", cites=["b", "c"]),
           ContentAddressedStore(tmp_path / "c2"), graph)
    assert entries(graph.log) == 2


@pytest.fixture
def maintainer(mk, tmp_path):
    idle = IdleContext(ledger=QuestionLedger(mk("ledger")), reputability=ReputabilityStore(mk("rep")),
                       consolidation=ConsolidationStore(mk("cons"), ContentAddressedStore(tmp_path / "arch")),
                       fidelity=DomainFidelityStore(mk("fid")), calibration=CalibrationStore(mk("cal")))
    return Maintainer(idle=idle, log_for=mk, belief_graph=BeliefGraphStore(mk("graph")),
                      policy=MaintenancePolicy(idle_every_questions=100))


def test_an_idle_cycle_writes_each_store_at_most_once(maintainer):
    m = maintainer
    for i, q in enumerate(["is 17 prime?", "how should we round 2.5?", "is 21 prime?"]):
        m.submit_question(f"q{i}", q)
    before = {name: entries(log) for name, log in
              [("cons", m.idle.consolidation.log), ("fid", m.idle.fidelity.log), ("cal", m.idle.calibration.log)]}
    events = m.run()   # three answers, then one idle cycle over all their claims
    assert [e["kind"] for e in events].count("idle") == 1
    after = {"cons": entries(m.idle.consolidation.log), "fid": entries(m.idle.fidelity.log),
             "cal": entries(m.idle.calibration.log)}
    assert all(after[k] - before[k] == 1 for k in after), (before, after)
    assert len(m.idle.consolidation.entries()) >= 3   # ...yet every surviving claim was recorded


def test_an_answered_question_costs_three_ledger_checkpoints(maintainer):
    m = maintainer
    start = entries(m.ledger.log)
    m.submit_question("q1", "is 17 prime?")
    m.tick()
    while m.scheduler._heap:
        m.tick()
    # Since owner decision 8 (batch 10, Phase AQ) each question has its own log:
    # submitted (queued), started (active), answered-and-rated (one batch) --
    # and the index gains one entry, when the question is first submitted.
    assert entries(m.ledger._log_for("q1")) == 3
    assert entries(m.ledger.log) - start == 1
    assert m.ledger.get("q1").status == "completed" and m.ledger.get("q1").importance != 0.5


def test_the_maintainer_state_at_rest_carries_no_scratch(maintainer):
    m = maintainer
    for i in range(3):
        m.submit_question(f"q{i}", f"is {17 + 2 * i} prime?")
    m.run()
    saved = m.scheduler.runner.log.read_latest()
    assert list(saved["shared_state"]) == ["maintenance"]   # no mirrors, no harvested namespaces
    assert saved["units"] == {}                              # no runner records of finished units
    assert m._m["units"] == {}


# --- the measurement tool itself ----------------------------------------------------------

def test_the_storage_measurement_script_runs(monkeypatch, tmp_path):
    path = Path(__file__).resolve().parents[1] / "scripts" / "measure_storage.py"
    spec = importlib.util.spec_from_file_location("measure_storage", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.tempfile, "mkdtemp", lambda prefix="": str(tmp_path / "run"))
    (tmp_path / "run").mkdir()
    result = module.main(total=4, step=2)
    assert [r["questions"] for r in result["rows"]] == [2, 4]
    logs = result["rows"][-1]["logs"]
    assert logs["maintainer"]["latest_state_bytes"] < 1000 and logs["index"]["entries"] > 0
