"""
Real model-backed fallback tests -- these hit the actual OLMo 2 model-lab
guest (192.168.0.166, olmo3-7b), no mocking for the main path, same convention as
test_model_serving_real.py. Deterministic edge cases (unreachable
backend) use an unrouted IP, same technique test_model_serving_real.py
already uses.
"""
from athenaeum_brain.model_backed_reasoning import ask_model, model_backed_claim, DEFAULT_MODEL
from athenaeum_brain.agents import (
    MasterOfMathematics, MasterOfLogic, MasterOfEngineering, MasterOfPhysics,
    MasterOfPhilosophy, MasterOfTheology, MasterOfWorldNews,
)


def test_ask_model_returns_none_for_unreachable_backend():
    assert ask_model("hello", model_name="nonexistent-model") is None


def test_model_backed_claim_returns_none_when_backend_unreachable():
    assert model_backed_claim(agent_name="X", question="hi", question_id="q1",
                               model_name="nonexistent-model") is None


def _stub_gpu_unavailable(monkeypatch):
    """These three tests isolate ask_model's CPU-path retry logic by
    monkeypatching LlamaCppBackend -- but ask_model now tries an elastic
    GPU worker FIRST (Section 4.3), and if one happens to be online (as it
    genuinely is when the Windows 3070 Ti box is running), it answers for
    real and short-circuits the very CPU-path logic these tests exist to
    exercise. Stubbing the GPU path to always report unavailable makes
    these tests correct regardless of whether a real worker happens to be
    up at the moment they run -- exactly the elasticity this module is
    built around, now visible in test isolation too."""
    import athenaeum_brain.model_backed_reasoning as mbr
    from athenaeum_body.model_serving import BackendUnavailable

    class AlwaysUnavailable:
        def infer(self, spec, question):
            raise BackendUnavailable("stubbed: no GPU worker for this test")

    monkeypatch.setattr(mbr, "build_elastic_gpu_backend", lambda: AlwaysUnavailable())


def test_ask_model_retries_on_empty_or_whitespace_completion(monkeypatch):
    """Real finding: OLMo 2's own sampling occasionally returns a
    near-empty completion (observed directly: a single space). Verified
    here deterministically by forcing the first two attempts empty."""
    import athenaeum_brain.model_backed_reasoning as mbr
    _stub_gpu_unavailable(monkeypatch)
    responses = iter([" ", "", "a real answer"])

    class FakeBackend:
        def __init__(self, *a, **kw):
            pass

        def infer(self, spec, question):
            return next(responses)

    monkeypatch.setattr(mbr, "LlamaCppBackend", FakeBackend)
    result = ask_model("irrelevant", max_attempts=3)
    assert result == "a real answer"


def test_ask_model_retries_on_timeout_not_just_empty_completion(monkeypatch):
    """Real bug caught running the full suite under load: a transient
    timeout (BackendUnavailable) used to return None immediately,
    burning zero of the remaining retry attempts -- only an empty-string
    response was ever retried. Verified here deterministically: the first
    attempt raises BackendUnavailable, the second succeeds."""
    import athenaeum_brain.model_backed_reasoning as mbr
    from athenaeum_body.model_serving import BackendUnavailable
    _stub_gpu_unavailable(monkeypatch)

    attempts = iter([BackendUnavailable("simulated timeout"), "a real answer"])

    class FakeBackend:
        def __init__(self, *a, **kw):
            pass

        def infer(self, spec, question):
            outcome = next(attempts)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    monkeypatch.setattr(mbr, "LlamaCppBackend", FakeBackend)
    result = ask_model("irrelevant", max_attempts=3)
    assert result == "a real answer"


def test_ask_model_returns_none_after_exhausting_attempts_on_repeated_timeout(monkeypatch):
    import athenaeum_brain.model_backed_reasoning as mbr
    from athenaeum_body.model_serving import BackendUnavailable
    _stub_gpu_unavailable(monkeypatch)

    class AlwaysTimesOut:
        def __init__(self, *a, **kw):
            pass

        def infer(self, spec, question):
            raise BackendUnavailable("simulated timeout")

    monkeypatch.setattr(mbr, "LlamaCppBackend", AlwaysTimesOut)
    assert ask_model("irrelevant", max_attempts=3) is None


def test_ask_model_gets_real_completion_from_olmo():
    # bare question -- ask_model wraps it in Q:/A: framing itself
    response = ask_model("What is the capital of France?")
    assert response and len(response.strip()) > 0


def test_model_backed_claim_has_capped_confidence_and_serving_model():
    # a genuine question, not an imperative -- "Say hello." turned out to
    # be a real edge case for OLMo 3's Q:/A: framing (degenerate/empty
    # output), unlike any actual agent fallback prompt, which is always a
    # real question extracted from a deliberation, never an imperative
    claim = model_backed_claim(agent_name="TestAgent", question="What is the capital of Japan?", question_id="q1")
    assert claim is not None
    assert claim.confidence < 1.0
    assert claim.serving_model == DEFAULT_MODEL
    assert claim.supporting_provenance == [f"llm:{DEFAULT_MODEL}"]


# --- per-agent fallback: in-jurisdiction, deterministic path empty ---

def test_mathematics_falls_back_to_real_model_when_no_digits_present():
    m = MasterOfMathematics()
    claims = m.explore("is this a prime example of poor planning?", "q1")
    assert len(claims) == 1
    assert claims[0].claim_type == "formal"
    assert claims[0].serving_model == DEFAULT_MODEL


def test_logic_never_falls_back_even_when_in_jurisdiction():
    """Section 2.2: Logic never asserts first-order claims -- no fallback
    path exists for it at all, by construction, not just by chance."""
    logic = MasterOfLogic()
    assert logic.in_jurisdiction("if all men are mortal, then therefore what?")
    assert logic.explore("if all men are mortal, then therefore what?", "q1") == []


def test_engineering_falls_back_when_no_rounding_question():
    e = MasterOfEngineering()
    claims = e.explore("how should we test this implementation?", "q1")
    assert len(claims) == 1
    assert claims[0].claim_type == "empirical"  # never 'executable' -- that's verify_code()'s alone
    assert claims[0].serving_model == DEFAULT_MODEL


def test_physics_falls_back_when_no_fall_height_given():
    p = MasterOfPhysics()
    claims = p.explore("what force acts on a stationary object?", "q1")
    assert len(claims) == 1
    assert claims[0].serving_model == DEFAULT_MODEL


def test_philosophy_falls_back_to_normative_claim_type():
    ph = MasterOfPhilosophy()
    claims = ph.explore("is this a good value to hold?", "q1")
    assert len(claims) == 1
    assert claims[0].claim_type == "normative"  # never 'empirical' -- Philosophy's own discipline


def test_theology_fallback_stays_under_the_confidence_cap():
    """Real model sampling occasionally produces a near-empty completion
    (observed directly: OLMo 2 returned a single space on one real call
    for this exact prompt) -- ask_model() now retries internally
    (model_backed_reasoning.py's own max_attempts), which is the real fix;
    this test just exercises the normal path."""
    t = MasterOfTheology()
    claims = t.explore("what is the doctrine of the trinity?", "q1")
    assert len(claims) == 1
    assert claims[0].claim_type == "traditional"
    assert claims[0].confidence <= t._TRADITIONAL_CONFIDENCE_CAP


def test_world_news_falls_back_when_fewer_than_two_events_named():
    wn = MasterOfWorldNews()
    claims = wn.explore("tell me about the history of ancient Rome", "q1")
    assert len(claims) == 1
    assert claims[0].serving_model == DEFAULT_MODEL


def test_deterministic_path_still_wins_when_it_finds_something():
    """The fallback must never override a real computation that DID find
    something -- deterministic claims take priority, unconditionally."""
    m = MasterOfMathematics()
    claims = m.explore("is 17 prime?", "q1")
    assert len(claims) == 1
    assert claims[0].serving_model is None  # the deterministic claim, not a fallback
    assert "computed:" in claims[0].supporting_provenance[0]
