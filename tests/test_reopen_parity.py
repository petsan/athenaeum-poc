"""Batch 11, Phase AT: a reopened answer is deliberated like a first answer --
the same verification routing (task 44) and the same domain-fidelity
re-grounding (Section 2.4.3). Before, reopens silently skipped both."""
import subprocess
import sys
import pytest
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.sandbox import SandboxResult
from athenaeum_body.ledger import QuestionLedger
from athenaeum_body.reputability_store import ReputabilityStore
from athenaeum_body.belief_graph_store import BeliefGraphStore
from athenaeum_body.domain_fidelity_store import DomainFidelityStore
from athenaeum_brain import model_backed_reasoning
from athenaeum_brain.idle_evolution import IdleContext
from athenaeum_brain.maintenance import Maintainer, MaintenancePolicy

SRC = "computed:trial_division"


def local_runner(code):
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
    return SandboxResult(status="completed", stdout=p.stdout, stderr=p.stderr, returncode=p.returncode)


@pytest.fixture
def host(tmp_path, monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: "gravity holds the moon in orbit")
    cas = ContentAddressedStore(tmp_path / "cas")
    log = lambda name: CheckpointLog(cas=cas, index_path=tmp_path / f"{name}.txt")
    rep, fid = ReputabilityStore(log("rep")), DomainFidelityStore(log("fid"))
    m = Maintainer(idle=IdleContext(ledger=QuestionLedger(log("ledger")), reputability=rep, fidelity=fid),
                   log_for=log, belief_graph=BeliefGraphStore(log("graph")),
                   verification={"enabled": True, "sandbox_run": local_runner},
                   policy=MaintenancePolicy(idle_every_questions=100, importance_threshold=0.0))
    return m, rep, fid


def downgrade(rep, src):
    before = rep.current_grade(src)["grade"]
    while rep.current_grade(src)["grade"] == before:
        rep.record_outcome(src, "source", "challenged")
    for _ in range(5):
        rep.record_outcome(src, "source", "challenged")


def test_a_reopen_is_verified_like_the_first_answer(host):
    m, rep, _ = host
    m.submit_question("q1", "is 17 prime?")
    m.run()
    first = m.ledger.get("q1").versions[0]
    assert first["verification"]["routed"] == 1                     # the sieve check ran the first time
    downgrade(rep, SRC)
    m.submit_question("q2", "is 19 prime?")
    m.run()
    reopened = m.ledger.get("q1").versions
    assert len(reopened) == 2, "the downgrade should have reopened q1"
    assert reopened[1]["verification"]["routed"] == 1                # ...and now on the reopen too


def test_a_reopen_respects_re_grounding(host):
    m, rep, fid = host
    m.submit_question("q1", "what force holds the moon in orbit?")
    m.run()
    assert any(c.get("serving_model") for c in m.ledger.get("q1").versions[0]["committed"])  # model answered
    # Physics is being re-grounded, until a fidelity reading this test never reaches
    fid.set_remediation("Physics", {"stage": "regrounding", "history": [], "until_reading": 10**6})
    downgrade(rep, "llm:olmo3-7b")
    m.submit_question("q2", "is 19 prime?")
    m.run()
    versions = m.ledger.get("q1").versions
    assert len(versions) == 2, "the downgrade should have reopened q1"
    assert versions[1]["regrounding_agents"] == ["Physics"]
    assert not any(c.get("serving_model") for c in versions[1]["committed"])  # no model fallback while re-grounding
