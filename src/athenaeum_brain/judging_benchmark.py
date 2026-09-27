"""
The judging benchmark for challenger models (owner decisions 11 and D15).

A model re-examining claims (decision 10) is trusted for what it is doing
there -- judging whether an answer is right -- only once it has shown it can
judge. "Established" standing (enough outcomes for the model's OWN claims)
measures something else, and live OLMo 3 7B judged 13/16 known answers
correctly with every miss a "no" to a TRUE answer (known-bugs #36).

The items (judging_benchmark.json) are unambiguous questions, each asked with
a correct and an incorrect answer, judged exactly as idle evolution judges a
model claim (`model_challenge` on "A (in answer to: Q)").

Qualifying (batch 12, phase AW, with evalcore's rules):
- A case counts as right only if the model judged it right on EVERY repeat:
  asking again is not new evidence.
- The model qualifies when the Wilson lower bound of (cases right / cases)
  is at least QUALIFYING_ACCURACY. A point estimate over-claims: 24/24 has a
  lower bound of 0.862, so the old 24-case benchmark could never prove 0.95.
  With 120 cases, one miss is allowed (evalcore.stats.required_n).
- The result must be for the current items (BENCHMARK_VERSION) and challenge
  prompts (PROMPT_VERSION).
- And the benchmark must have been reviewed by the owner (D15): until then it
  is provisional, and no model's challenges count, whatever it scores.
Until a model qualifies, its "no" is dissent only.
"""
from __future__ import annotations
import hashlib
import json
import time
from pathlib import Path

from evalcore.stats import required_n, wilson_ci

from athenaeum_body.model_fitness_store import ModelFitnessStore
from .claims import Claim
from .model_backed_reasoning import model_challenge, CHALLENGE_PROMPT, ANSWER_CHALLENGE_PROMPT

QUALIFYING_ACCURACY = 0.95   # on the Wilson lower bound, not the point estimate
CONFIDENCE = 0.95
DATA = Path(__file__).with_name("judging_benchmark.json")


def _load() -> dict:
    return json.loads(DATA.read_text(encoding="utf-8"))


_DATA = _load()
# (question, correct answer, incorrect answer): each question is judged twice
ITEMS = [tuple(i) for i in _DATA["items"]]
REVIEW = _DATA["review"]


def _digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode("utf-8")).hexdigest()[:16]


BENCHMARK_VERSION = _digest([list(i) for i in ITEMS])
PROMPT_VERSION = _digest([CHALLENGE_PROMPT, ANSWER_CHALLENGE_PROMPT])


def reviewed() -> bool:
    """Whether the owner has reviewed the current items (read fresh, so an
    approval takes effect without a restart)."""
    return _load()["review"].get("status") == "reviewed"


def cases() -> list[tuple[str, str, bool]]:
    """(question, answer, is_correct): one correct and one incorrect answer per item."""
    return [c for q, right, wrong in ITEMS for c in ((q, right, True), (q, wrong, False))]


def score(case_right: int, n_cases: int) -> dict:
    """The Wilson verdict on `case_right` of `n_cases`."""
    low, high = wilson_ci(case_right, n_cases, CONFIDENCE)
    return {"cases": n_cases, "cases_right": case_right, "case_accuracy": round(case_right / n_cases, 4),
            "wilson_low": round(low, 4), "wilson_high": round(high, 4),
            "passed": low >= QUALIFYING_ACCURACY}


def run_benchmark(model_name: str, repeats: int = 1) -> dict:
    """Judges every case `repeats` times, exactly as idle evolution would.
    A judgment is right when a correct answer is NOT challenged, or an
    incorrect one IS; a case is right only if every repeat was. An
    unreachable model challenges nothing, so it can't pass by accident: it
    would miss every incorrect answer."""
    right, misses, cases_right = 0, [], 0
    all_cases = cases()
    for q, a, is_correct in all_cases:
        claim = Claim(question_id="judging-benchmark", round=1, issuing_agent="benchmark",
                      statement=f"{a} (in answer to: {q})", claim_type="empirical", confidence=0.6,
                      defeat_condition="the benchmark label", jurisdiction_check=True,
                      supporting_provenance=["benchmark"], serving_model=model_name)
        every = True
        for _ in range(repeats):
            challenged = model_challenge(claim, "judging-benchmark", model_name) is not None
            if challenged != is_correct:
                right += 1
            else:
                every = False
                misses.append({"question": q, "answer": a, "is_correct": is_correct,
                               "judged": "challenged" if challenged else "accepted"})
        cases_right += every
    total = len(all_cases) * repeats
    return {"model": model_name, "benchmark_version": BENCHMARK_VERSION, "prompt_version": PROMPT_VERSION,
            "total": total, "correct": right, "accuracy": round(right / total, 4), "repeats": repeats,
            "threshold": QUALIFYING_ACCURACY, **score(cases_right, len(all_cases)),
            "reviewed": reviewed(), "misses": misses, "at": time.time()}


def challenger_qualified(store: ModelFitnessStore | None, model_name: str) -> tuple[bool, str]:
    """Whether this model's challenges count, and why (or why not)."""
    if store is None:
        return False, "no fitness store to read a benchmark result from"
    result = store.judging(model_name)
    if result is None:
        return False, "never run on the judging benchmark"
    if result["benchmark_version"] != BENCHMARK_VERSION:
        return False, "the benchmark has changed since its last run"
    if result["prompt_version"] != PROMPT_VERSION:
        return False, "the challenge prompt has changed since its last run"
    if "wilson_low" not in result:
        return False, "recorded before the Wilson rule; run it again"
    got = (f"{result['cases_right']}/{result['cases']} cases, Wilson lower bound {result['wilson_low']:.3f}")
    if not result["passed"]:
        return False, f"{got}, below the {QUALIFYING_ACCURACY:.2f} needed"
    if not reviewed():
        return False, f"{got}, but the benchmark is provisional (awaiting the owner's review)"
    return True, f"{got} on the current, reviewed benchmark"


def misses_allowed() -> int:
    """The most misses the current benchmark allows while still qualifying."""
    n, misses = len(cases()), 0
    while misses < n and required_n(QUALIFYING_ACCURACY, misses + 1, CONFIDENCE) <= n:
        misses += 1
    return misses if required_n(QUALIFYING_ACCURACY, 0, CONFIDENCE) <= n else -1
