"""Task 44: cross-agent verification routing -- another agent's
formalizable claim is checked by Engineering executing an INDEPENDENT
method, and only when the execution sandbox is enabled."""
import subprocess
import sys
import pytest
from athenaeum_body.config import Config
from athenaeum_body.sandbox import SandboxResult
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.scheduler.runner import SingleUnitRunner
from athenaeum_body.api import build_app
from athenaeum_brain import model_backed_reasoning
from athenaeum_brain.agents import MasterOfPhysics
from athenaeum_brain.claims import Claim
from athenaeum_brain.loop import make_deliberation_unit
from athenaeum_brain.rounds import synthesis_round
from athenaeum_brain.verification_routing import (
    sandbox_enabled, verification_code, route_for_verification,
)


@pytest.fixture(autouse=True)
def _no_model_fallback(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)


def local_runner(code: str) -> SandboxResult:
    """Test harness: really executes the verifier's generated check code,
    but in a plain subprocess rather than the OS sandbox -- the code is
    this module's own generated source, not untrusted input."""
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
    return SandboxResult(status="completed", stdout=p.stdout, stderr=p.stderr, returncode=p.returncode)


def never_called(code):
    raise AssertionError("the sandbox must not be touched while routing is disabled")


def _claim(agent, statement, claim_type="formal"):
    return Claim(question_id="q", round=1, issuing_agent=agent, statement=statement,
                 claim_type=claim_type, confidence=1.0, defeat_condition="x",
                 jurisdiction_check=True, supporting_provenance=["computed:x"])


def _route(*claims):
    return route_for_verification(list(claims), "q", enabled=True, sandbox_run=local_runner)


# --- the gate -----------------------------------------------------------------

def test_shipped_config_keeps_routing_off():
    """CLAUDE.md hard constraint: execution_sandbox.enabled stays false."""
    assert sandbox_enabled() is False


def test_only_a_literal_true_enables_it():
    assert sandbox_enabled(Config(raw={"execution_sandbox": {"enabled": True}})) is True
    for value in ("yes", 1, "true", None):
        assert sandbox_enabled(Config(raw={"execution_sandbox": {"enabled": value}})) is False


def test_disabled_routing_executes_nothing_and_says_why():
    result = route_for_verification([_claim("Mathematics", "17 is prime")], "q",
                                    enabled=False, sandbox_run=never_called)
    assert result["responses"] == [] and result["routed"] == 0
    assert "1 verifiable claim(s)" in result["skipped_reason"]


def test_nothing_verifiable_means_no_skip_note():
    result = route_for_verification([_claim("Philosophy", "an ought claim")], "q", enabled=False)
    assert result["skipped_reason"] is None


# --- primality: sieve vs. trial division ---------------------------------------

@pytest.mark.parametrize("statement", ["17 is prime", "2 is prime", "15 is not prime", "1 is not prime",
                                       "0 is not prime", "7919 is prime"])
def test_correct_primality_claims_are_corroborated(statement):
    [resp] = _route(_claim("Mathematics", statement))["responses"]
    assert resp.relation == "corroborates" and resp.issuing_agent == "Engineering"
    assert resp.claim_type == "executable"


@pytest.mark.parametrize("statement", ["15 is prime", "17 is not prime", "1 is prime"])
def test_wrong_primality_claims_are_challenged(statement):
    [resp] = _route(_claim("Mathematics", statement))["responses"]
    assert resp.relation == "challenges"


# --- free fall: numerical integration vs. closed form ---------------------------

def test_real_physics_claim_is_corroborated_by_simulation():
    [claim] = [c for c in MasterOfPhysics().explore("how long does an object take to fall from 19.6m?", "q")
               if not c.forecast]
    [resp] = _route(claim)["responses"]
    assert resp.relation == "corroborates"


def test_wrong_fall_time_is_challenged_by_simulation():
    wrong = _claim("Physics", "an object falling from 19.6m takes approximately 3.00s to hit the ground "
                              "(v0=0, g=9.8 m/s^2)", claim_type="empirical")
    [resp] = _route(wrong)["responses"]
    assert resp.relation == "challenges"


# --- what is and isn't routed ----------------------------------------------------

def test_unrecognised_and_engineering_claims_are_not_routed():
    assert verification_code(_claim("Philosophy", "virtue is the only good")) is None
    assert _route(_claim("Engineering", "17 is prime"))["routed"] == 0


def test_absurd_sizes_are_left_to_ordinary_cross_examination():
    assert verification_code(_claim("Mathematics", "100000007 is prime")) is None
    assert verification_code(_claim("Physics", "an object falling from 50000m takes approximately "
                                               "101.02s to hit the ground (v0=0, g=9.8 m/s^2)")) is None


# --- through synthesis and the loop ------------------------------------------------

def test_a_challenged_claim_lands_in_dissent():
    wrong = _claim("Mathematics", "15 is prime")
    result = synthesis_round([wrong], _route(wrong)["responses"])
    assert result["committed"] == [] and len(result["dissent"]) == 1


def _answer(tmp_path, question, verification=None):
    log = CheckpointLog(cas=ContentAddressedStore(tmp_path / "cas"), index_path=tmp_path / "i.txt")
    runner = SingleUnitRunner(log, shared_state={})
    unit = make_deliberation_unit(question, "q", verification=verification)
    while unit.status != "completed":
        runner.run_round(unit)
    return log.read_latest()["shared_state"]


def test_loop_routes_when_enabled(tmp_path):
    state = _answer(tmp_path, "is 17 prime?", verification={"enabled": True, "sandbox_run": local_runner})
    assert state["answer"]["verification"] == {"routed": 1, "skipped_reason": None}
    assert any(c["issuing_agent"] == "Engineering" and c["relation"] == "corroborates"
               for c in state["exam_claims"])
    assert state["answer"]["committed"][0]["statement"] == "17 is prime"


def test_loop_reports_the_skip_by_default(tmp_path):
    state = _answer(tmp_path, "is 17 prime?")
    assert state["answer"]["verification"]["routed"] == 0
    assert "execution_sandbox.enabled is false" in state["answer"]["verification"]["skipped_reason"]


def test_api_follows_config_and_does_not_route(tmp_path):
    answer = build_app(tmp_path)[0]("is 17 prime?")["answer"]
    assert answer["verification"]["routed"] == 0


# --- the real OS sandbox (needs CAP_SYS_ADMIN, like test_engineering_execution.py) ---

def test_real_sandbox_run_corroborates_a_true_claim():
    result = route_for_verification([_claim("Mathematics", "97 is prime")], "q", enabled=True)
    [resp] = result["responses"]
    assert resp.relation == "corroborates"
    assert resp.supporting_provenance[0].startswith("executed:sandbox_run:")
