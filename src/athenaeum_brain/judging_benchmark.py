"""
The judging benchmark for challenger models (owner decision 11, 2026-09-26).

A model re-examining claims (decision 10) is trusted for what it is doing
there -- judging whether an answer is right -- only once it has shown it can
judge. "Established" standing (enough outcomes for the model's OWN claims)
measures something else, and live OLMo 3 7B judged 13/16 known answers
correctly with every miss a "no" to a TRUE answer (known-bugs #36).

The benchmark is a balanced set of unambiguous questions, each asked with a
correct and an incorrect answer, judged exactly as idle evolution judges a
model claim (`model_challenge` on "A (in answer to: Q)"). A challenger's
"no" counts only if its latest recorded score:
  - was for the current benchmark items (BENCHMARK_VERSION),
  - was with the current challenge prompts (PROMPT_VERSION), and
  - meets QUALIFYING_ACCURACY.
Change the items, the prompts or the model, and the model must qualify
again. Until then its "no" is dissent only.
"""
from __future__ import annotations
import hashlib
import json
import time
from athenaeum_body.model_fitness_store import ModelFitnessStore
from .claims import Claim
from .model_backed_reasoning import model_challenge, CHALLENGE_PROMPT, ANSWER_CHALLENGE_PROMPT

QUALIFYING_ACCURACY = 0.95   # a placeholder, like every threshold here: at most 1 miss in 24

# (question, correct answer, incorrect answer): each question is judged twice
ITEMS = [
    ("what force holds the moon in orbit?", "Gravity", "Magnetism"),
    ("what is the capital of France?", "Paris", "Berlin"),
    ("what is the largest planet in our solar system?", "Jupiter", "Mars"),
    ("how many legs does a spider have?", "Eight", "Six"),
    ("what is 2 + 2?", "4", "5"),
    ("what gas do plants absorb from the air for photosynthesis?", "Carbon dioxide", "Oxygen"),
    ("what is the boiling point of water at sea level in degrees Celsius?", "100", "50"),
    ("who wrote Romeo and Juliet?", "William Shakespeare", "Charles Dickens"),
    ("what is the chemical symbol for gold?", "Au", "Ag"),
    ("how many continents are there?", "Seven", "Five"),
    ("what planet is closest to the Sun?", "Mercury", "Venus"),
    ("what is the freezing point of water in degrees Celsius?", "0", "10"),
]


def _digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode("utf-8")).hexdigest()[:16]


BENCHMARK_VERSION = _digest(ITEMS)
PROMPT_VERSION = _digest([CHALLENGE_PROMPT, ANSWER_CHALLENGE_PROMPT])


def cases() -> list[tuple[str, str, bool]]:
    """(question, answer, is_correct) -- 12 correct answers, 12 incorrect."""
    return [c for q, right, wrong in ITEMS for c in ((q, right, True), (q, wrong, False))]


def run_benchmark(model_name: str, repeats: int = 1) -> dict:
    """Judges every case `repeats` times, exactly as idle evolution would.
    A judgment is right when a correct answer is NOT challenged, or an
    incorrect one IS. An unreachable model challenges nothing, so it can't
    pass by accident: it would miss every incorrect answer."""
    right, misses = 0, []
    for q, a, is_correct in cases():
        claim = Claim(question_id="judging-benchmark", round=1, issuing_agent="benchmark",
                      statement=f"{a} (in answer to: {q})", claim_type="empirical", confidence=0.6,
                      defeat_condition="the benchmark label", jurisdiction_check=True,
                      supporting_provenance=["benchmark"], serving_model=model_name)
        for _ in range(repeats):
            challenged = model_challenge(claim, "judging-benchmark", model_name) is not None
            if challenged != is_correct:
                right += 1
            else:
                misses.append({"question": q, "answer": a, "is_correct": is_correct,
                               "judged": "challenged" if challenged else "accepted"})
    total = len(cases()) * repeats
    accuracy = right / total
    return {"model": model_name, "benchmark_version": BENCHMARK_VERSION, "prompt_version": PROMPT_VERSION,
            "total": total, "correct": right, "accuracy": round(accuracy, 4),
            "threshold": QUALIFYING_ACCURACY, "passed": accuracy >= QUALIFYING_ACCURACY,
            "misses": misses, "at": time.time()}


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
    if result["accuracy"] < QUALIFYING_ACCURACY:
        return False, f"scored {result['accuracy']:.0%}, below the {QUALIFYING_ACCURACY:.0%} needed"
    return True, f"scored {result['accuracy']:.0%} on the current benchmark"
