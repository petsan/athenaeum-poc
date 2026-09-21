from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.domain_fidelity_store import DomainFidelityStore
from athenaeum_brain.domain_fidelity import (
    jurisdiction_overreach_rate, fingerprint_deviation, compute_score, needs_review,
)

def make_store(tmp_path):
    log = CheckpointLog(cas=ContentAddressedStore(tmp_path / "cas"), index_path=tmp_path / "index.txt")
    return DomainFidelityStore(log)

def math_claim(cid, computed=True):
    return {"claim_id": cid, "issuing_agent": "Mathematics", "claim_type": "formal",
            "supporting_provenance": ["computed:trial_division"] if computed else ["textbook:page-42"]}

def test_on_style_claims_score_perfectly(tmp_path):
    claims = [math_claim("c1"), math_claim("c2"), math_claim("c3")]
    dev = fingerprint_deviation("Mathematics", claims)
    assert dev == 0.0

def test_drifted_claims_show_nonzero_deviation(tmp_path):
    claims = [math_claim("c1"), math_claim("c2", computed=False), math_claim("c3", computed=False)]
    dev = fingerprint_deviation("Mathematics", claims)
    assert dev == pytest_approx(2 / 3)

def pytest_approx(x, tol=1e-9):
    class _A:
        def __eq__(self, other): return abs(other - x) < tol
    return _A()

def test_jurisdiction_overreach_rate_from_real_logic_challenge_pattern(tmp_path):
    exploration = [{"claim_id": "c1", "issuing_agent": "Mathematics", "claim_type": "normative",
                     "supporting_provenance": []}]
    exam = [{"relation": "challenges", "target_claim_id": "c1",
             "statement": "claim 'x' asserted outside Mathematics's declared jurisdiction"}]
    rate = jurisdiction_overreach_rate("Mathematics", exploration, exam)
    assert rate == 1.0

def test_no_claims_from_agent_returns_zero_not_error(tmp_path):
    assert jurisdiction_overreach_rate("Physics", [], []) == 0.0
    assert fingerprint_deviation("Physics", []) == 0.0

def test_combined_score_perfect_when_both_signals_clean(tmp_path):
    exploration = [math_claim("c1"), math_claim("c2")]
    result = compute_score("Mathematics", exploration, [])
    assert result["domain_fidelity_score"] == 1.0

def test_needs_review_insufficient_history(tmp_path):
    store = make_store(tmp_path)
    store.record("Mathematics", {"domain_fidelity_score": 0.9})
    assert needs_review(store, "Mathematics")["needs_review"] is False

def test_needs_review_flags_a_real_drop(tmp_path):
    """Simulates an agent's style genuinely degrading over several rounds --
    the exact scenario Section 2.4.3 describes."""
    store = make_store(tmp_path)
    for score in [0.95, 0.93, 0.94]:  # healthy baseline
        store.record("Mathematics", {"domain_fidelity_score": score})
    store.record("Mathematics", {"domain_fidelity_score": 0.60})  # sudden drift
    result = needs_review(store, "Mathematics", drop_threshold=0.15)
    assert result["needs_review"] is True
    assert "dropped" in result["reason"]

def test_needs_review_not_triggered_by_small_fluctuation(tmp_path):
    store = make_store(tmp_path)
    for score in [0.90, 0.91, 0.89]:
        store.record("Mathematics", {"domain_fidelity_score": score})
    store.record("Mathematics", {"domain_fidelity_score": 0.85})  # small, normal fluctuation
    result = needs_review(store, "Mathematics", drop_threshold=0.15)
    assert result["needs_review"] is False
