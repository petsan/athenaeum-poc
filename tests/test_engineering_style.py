"""Owner decision 3 (batch 10, Phase AL): Engineering's rounding claims are
'formal' (nothing executes them), and Engineering's style is a real sandbox
run OR a claim naming the implementation standard it follows -- so it stays
distinguishable from Mathematics while the sandbox is off."""
import pytest
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.scheduler.runner import SingleUnitRunner
from athenaeum_body.sandbox import SandboxResult
from athenaeum_brain import model_backed_reasoning
from athenaeum_brain.agents import MasterOfEngineering, MasterOfMathematics
from athenaeum_brain.domain_fidelity import FINGERPRINT_CHECKS, fingerprint_deviation
from athenaeum_brain.loop import make_deliberation_unit


@pytest.fixture(autouse=True)
def _no_model_fallback(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)


def test_rounding_claims_are_formal_and_name_their_standard():
    (claim,) = MasterOfEngineering().explore("how should we round 2.5?", "q1")
    assert claim.claim_type == "formal"          # no longer 'executable': nothing ran in a sandbox
    assert claim.supporting_provenance == ["standard:IEEE-754/decimal.ROUND_HALF_EVEN"]  # one line of evidence
    assert claim.statement == "2.5 rounds to 2 (IEEE-754 round-half-to-even convention)"


def test_engineering_and_mathematics_stay_distinguishable():
    eng = MasterOfEngineering().explore("how should we round 2.5?", "q1")[0].to_dict()
    math = MasterOfMathematics().explore("how should we round 2.5?", "q1")[0].to_dict()
    assert FINGERPRINT_CHECKS["Engineering"](eng) and not FINGERPRINT_CHECKS["Engineering"](math)
    assert FINGERPRINT_CHECKS["Mathematics"](math) and not FINGERPRINT_CHECKS["Mathematics"](eng)
    assert fingerprint_deviation("Engineering", [eng]) == 0.0   # rounding no longer reads as drift


def test_real_sandbox_runs_are_still_on_style_and_a_bare_claim_is_not():
    ran = MasterOfEngineering().verify_code(
        "t1", "print('PASS')", question_id="q1",
        sandbox_run=lambda code: SandboxResult(status="completed", stdout="PASS\n", stderr="", returncode=0))
    assert ran.claim_type == "executable" and FINGERPRINT_CHECKS["Engineering"](ran.to_dict())
    bare = {"claim_type": "empirical", "supporting_provenance": ["llm:olmo3-7b"]}   # a model fallback
    assert not FINGERPRINT_CHECKS["Engineering"](bare)


def test_the_rounding_plural_answer_is_kept(tmp_path):
    log = CheckpointLog(cas=ContentAddressedStore(tmp_path / "cas"), index_path=tmp_path / "i.txt")
    runner = SingleUnitRunner(log, shared_state={})
    unit = make_deliberation_unit("how should we round 2.5?", "q1")
    while unit.status != "completed":
        runner.run_round(unit)
    answer = log.read_latest()["shared_state"]["answer"]
    (plural,) = answer["plural_answers"]
    agents = {c["agent"] for c in plural["conclusions"]}
    assert {"Mathematics", "Engineering"} <= agents
