"""known-bugs #35: a small model doesn't stop at the end of its answer. The
batch 9 live smoke committed a Physics claim whose statement ran on into an
invented instruction and a whole new Q:/A: turn. The completion is now cut
to the answer. Deterministic: the backend is stubbed with the completion
actually observed live."""
import athenaeum_brain.model_backed_reasoning as mbr
from athenaeum_body.model_serving import BackendUnavailable
from athenaeum_brain.model_backed_reasoning import answer_only, ask_model, model_backed_claim

OBSERVED = (" Gravity \nExplain how the answer helps with the question.\n\n"
            "Q: how can i become more assertive at work?\nA: Practice saying \"no\" in low-stakes situations")


def _backend(monkeypatch, completions):
    class NoGpu:
        def infer(self, spec, prompt):
            raise BackendUnavailable("stubbed")

    class Fake:
        def __init__(self, *a, **k):
            pass

        def infer(self, spec, prompt):
            return next(completions)
    monkeypatch.setattr(mbr, "build_elastic_gpu_backend", lambda: NoGpu())
    monkeypatch.setattr(mbr, "LlamaCppBackend", Fake)


def test_answer_only_keeps_the_answer_and_nothing_after_it():
    assert answer_only(OBSERVED) == "Gravity"
    assert answer_only("Paris is the capital of France.") == "Paris is the capital of France."
    assert answer_only("\n\n  Tokyo.  \nQ: next?") == "Tokyo."
    assert answer_only("   ") == "" and answer_only("\nQ: a question of its own\nA: x") == ""


def test_ask_model_returns_the_answer_not_the_run_on(monkeypatch):
    _backend(monkeypatch, iter([OBSERVED]))
    assert ask_model("what force holds the moon in orbit?") == "Gravity"


def test_a_completion_with_no_answer_is_retried(monkeypatch):
    _backend(monkeypatch, iter(["\nQ: something else entirely?\nA: no", "Gravity holds the moon in orbit.\nQ: more"]))
    assert ask_model("what force holds the moon in orbit?", max_attempts=3) == "Gravity holds the moon in orbit."


def test_the_claim_statement_is_one_line(monkeypatch):
    _backend(monkeypatch, iter([OBSERVED]))
    claim = model_backed_claim(agent_name="Physics", question="why do objects fall when dropped?", question_id="q1")
    assert claim.statement == "Gravity" and "\n" not in claim.statement
