"""Both new modules, proven against REAL claim logs from the actual
deliberation engine, not just hand-built synthetic dicts."""
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.scheduler.runner import SingleUnitRunner
from athenaeum_body.consolidation_store import ConsolidationStore
from athenaeum_body.domain_fidelity_store import DomainFidelityStore
from athenaeum_brain.loop import make_deliberation_unit
from athenaeum_brain.consolidation import record_survival, should_promote_to_c, compact, expand
from athenaeum_brain.domain_fidelity import compute_score

def run_once(tmp_path, name, question):
    cas = ContentAddressedStore(tmp_path / f"cas-{name}")
    log = CheckpointLog(cas=cas, index_path=tmp_path / f"index-{name}.txt")
    runner = SingleUnitRunner(log, shared_state={})
    unit = make_deliberation_unit(question, name)
    while unit.status != "completed":
        runner.run_round(unit)
    return log.read_latest()["shared_state"]

def test_consolidation_promotes_a_real_repeatedly_confirmed_claim(tmp_path):
    cons_log = CheckpointLog(cas=ContentAddressedStore(tmp_path / "cons-cas"), index_path=tmp_path / "cons-index.txt")
    store = ConsolidationStore(cons_log, ContentAddressedStore(tmp_path / "archive"))

    for i in range(5):
        state = run_once(tmp_path, f"run{i}", "is 17 prime?")
        committed = state["answer"]["committed"][0]  # real claim from the real engine
        entry = record_survival(store, "17-is-prime", committed)

    verdict = should_promote_to_c(entry, min_cycles=5, min_sources=1)
    assert verdict["eligible"] is True
    node = compact(store, "17-is-prime")
    assert node["tier"] == "C"
    full = expand(store, "17-is-prime")
    assert full["cycles"] == 5

def test_domain_fidelity_scores_a_real_deliberation_as_healthy(tmp_path):
    state = run_once(tmp_path, "df", "is 17 prime?")
    result = compute_score("Mathematics", state["exploration_claims"], state["exam_claims"])
    assert result["domain_fidelity_score"] == 1.0  # real Mathematics claims, on-style, no overreach
