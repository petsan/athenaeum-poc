"""
Real specify->implement->execute->verify loop (Phase 15, tasks 42-43) --
these run the ACTUAL sandbox (no mocking), same convention as
test_sandbox.py: needs CAP_SYS_ADMIN, will not pass in an unprivileged
runner without extra setup.
"""
from athenaeum_brain.agents import MasterOfEngineering
from athenaeum_brain.claims import Claim


def test_verify_code_real_known_correct_solution():
    e = MasterOfEngineering()
    claim = e.verify_code("sum-of-two", "print(2 + 2 == 4 and 'PASS' or 'FAIL')\nprint('PASS')",
                           question_id="q1")
    assert claim.claim_type == "executable"
    assert claim.confidence == 1.0
    assert "verified" in claim.statement


def test_verify_code_real_known_buggy_solution():
    e = MasterOfEngineering()
    code = "import sys\nassert 2 + 2 == 5, 'deliberately wrong'\nprint('PASS')"
    claim = e.verify_code("broken-sum", code, question_id="q1")
    assert claim.confidence == 0.0
    assert "FAILED" in claim.statement
    assert "AssertionError" in claim.defeat_condition or "deliberately wrong" in claim.defeat_condition


def test_verify_code_real_nonzero_exit_without_pass_fails():
    e = MasterOfEngineering()
    code = "import sys\nprint('did something')\nsys.exit(1)"
    claim = e.verify_code("no-pass-marker", code, question_id="q1")
    assert claim.confidence == 0.0


def test_verify_code_sets_serving_model_field():
    e = MasterOfEngineering()
    claim = e.verify_code("trivial", "print('PASS')", question_id="q1")
    assert claim.serving_model == "deterministic:sandbox_execution"


def test_verify_claim_corroborates_when_execution_confirms():
    e = MasterOfEngineering()
    original = Claim(question_id="q1", round=1, issuing_agent="Mathematics",
                      statement="3 * 7 == 21", claim_type="formal", confidence=1.0,
                      defeat_condition="x", jurisdiction_check=True)
    resp = e.verify_claim(original, "print('PASS' if 3 * 7 == 21 else 'FAIL')\nassert 3*7==21\nprint('PASS')",
                           question_id="q1")
    assert resp.relation == "corroborates"
    assert resp.target_claim_id == original.claim_id


def test_verify_claim_challenges_when_execution_contradicts():
    e = MasterOfEngineering()
    original = Claim(question_id="q1", round=1, issuing_agent="Mathematics",
                      statement="3 * 7 == 20", claim_type="formal", confidence=1.0,
                      defeat_condition="x", jurisdiction_check=True)
    resp = e.verify_claim(original, "assert 3 * 7 == 20\nprint('PASS')", question_id="q1")
    assert resp.relation == "challenges"


def test_verify_code_with_injected_stub_for_fast_unit_testing():
    """Not every caller needs the real OS sandbox spun up per case --
    sandbox_run is injectable for that, exercised here against a fake
    result to check the pass/fail decision logic itself in isolation."""
    from athenaeum_body.sandbox import SandboxResult
    e = MasterOfEngineering()

    def fake_pass(code, **kwargs):
        return SandboxResult(status="completed", stdout="PASS\n", stderr="", returncode=0)

    def fake_timeout(code, **kwargs):
        return SandboxResult(status="timeout", stdout="", stderr="", returncode=-9)

    ok = e.verify_code("t1", "irrelevant", question_id="q1", sandbox_run=fake_pass)
    assert ok.confidence == 1.0

    timed_out = e.verify_code("t2", "irrelevant", question_id="q1", sandbox_run=fake_timeout)
    assert timed_out.confidence == 0.0
    assert "timeout" in timed_out.defeat_condition
