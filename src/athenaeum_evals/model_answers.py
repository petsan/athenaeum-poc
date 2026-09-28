"""How well does each lab model answer? One category per model.

Every lab model is asked every judging-benchmark question, the way the
agents' fallbacks ask (`ask_model`, with its retries and answer cut).
An answer is graded lexically against the item's labels: right when it
contains the correct answer and not the labelled wrong one. The grader is
checked against all 120 labelled answers in the tests. Accepted alternative
forms ("Einstein" for "Albert Einstein", "sodium chloride" for NaCl) are in
evals/golden/answer_aliases.json, outside the benchmark's versioned items. A
free-form answer it still can't read (a paraphrase, a hedge) counts as not
right, so accuracy here is a floor.

Only the admitted model (the one every fallback asks) is gated: its
accuracy, how often it gives no answer at all, and its p95 latency. The
other models share the same card, per category, so a newly served model is
compared on equal terms before anyone proposes admitting it.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from evalcore import CaseResult, GateSpec, Suite
from evalcore.golden import load_items

from athenaeum_body.model_lab_registry import MODEL_LAB_ENDPOINTS
from athenaeum_brain import judging_benchmark as jb
from athenaeum_brain import model_backed_reasoning as mbr

KEY = "model_answers"
ADMITTED = mbr.DEFAULT_MODEL
ALIASES_FILE = "answer_aliases.json"
ALIASES = Path(__file__).resolve().parents[2] / "evals" / "golden" / ALIASES_FILE

SUITE = Suite(
    key=KEY, title="Lab model answers (benchmark questions, graded lexically)",
    per_case_gates=[
        GateSpec("admitted_right", f"Admitted model ({ADMITTED}) answers right", ">=", "model_min_accuracy"),
        GateSpec("admitted_answered", f"Admitted model ({ADMITTED}) gives an answer", ">=", "model_min_answered"),
    ],
    slo=("model_max_p95_s", 1.0),
    optional_gates=frozenset({"mean_cost_usd"}),               # local models: no cost to report
    primary_metrics=("right", "answered"),
    defaults={"model_min_accuracy": 0.80, "model_min_answered": 0.95, "model_max_p95_s": 30.0},
    # A sampling model on 60 questions: accuracy has a standard deviation of
    # about 0.04 between runs, so 0.10 (2.5 of them) is a real drop; latency in
    # seconds (evalcore 0.1.2).
    regression_tolerances={"admitted_right": 0.10, "admitted_answered": 0.05, "p95_latency_s": 5.0},
    golden_files=(ALIASES_FILE,),
)
SYSTEM_INFO = {"name": "lab models", "model_id": ADMITTED, "models": ", ".join(MODEL_LAB_ENDPOINTS),
               "prompt_version": mbr.ANSWER_FRAME}

_WORDS = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
          "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12"}
_FILLER = {"the", "a", "an", "about", "approximately", "roughly"}


def normalize(text: str) -> str:
    """Lower case, no thousands commas or punctuation (a decimal point stays),
    number words as digits, no articles or hedges: "About 300,000" and
    "300000" read alike, as do "Eight" and "8"."""
    t = re.sub(r"[^\w\s.+-]", " ", text.lower().replace(",", ""))
    t = re.sub(r"(?<=\d) (?=\d{3}\b)", "", t)          # "300 000": a space as the thousands separator
    words = [_WORDS.get(w.rstrip("."), w) for w in t.split()]
    return " ".join(w for w in words if w.rstrip(".") not in _FILLER)


def _contains(answer: str, label: str) -> bool:
    return re.search(r"(?<![\w.])" + re.escape(normalize(label)) + r"(?![\w])", normalize(answer)) is not None


def grade(answer: str | None, correct: str, wrong: str, accept=()) -> bool:
    """Right when the answer names the correct label (or an accepted form of
    it) and not the wrong one."""
    return (bool(answer) and any(_contains(answer, label) for label in (correct, *accept))
            and not _contains(answer, wrong))


def aliases(path: Path = ALIASES) -> dict[str, tuple]:
    """{question: accepted forms}. An alias that names the wrong label, or a
    question the benchmark doesn't ask, is an error."""
    wrong_of = {q: w for q, _, w in jb.ITEMS}
    out = {}
    for a in load_items(path):
        if a["question"] not in wrong_of:
            raise ValueError(f"{path.name}: {a['id']} is for a question the benchmark doesn't ask")
        if any(_contains(alias, wrong_of[a["question"]]) for alias in a["accept"]):
            raise ValueError(f"{path.name}: {a['id']} accepts the labelled wrong answer")
        out[a["question"]] = tuple(a["accept"])
    return out


def evaluate(models=None, items=None, ask=None) -> list[CaseResult]:
    models = list(MODEL_LAB_ENDPOINTS) if models is None else models
    items = jb.ITEMS if items is None else items
    ask = ask or mbr.ask_model
    accepted = aliases()
    results = []
    for model in models:
        for i, (question, correct, wrong) in enumerate(items):
            r = CaseResult(KEY, f"{model}/{i:02d}", model, "original", 0)
            started = time.perf_counter()
            try:
                answer = ask(question, model_name=model)
            except Exception as e:                     # an unreachable model gives no answer
                answer, r.detail["error"] = None, f"{type(e).__name__}: {e}"
            r.latency_s = time.perf_counter() - started
            right = grade(answer, correct, wrong, accepted.get(question, ()))
            r.metrics.update(right=float(right), answered=float(bool(answer)))
            if model == ADMITTED:
                r.metrics.update(admitted_right=float(right), admitted_answered=float(bool(answer)))
            else:                                      # the latency SLO is the admitted model's
                r.detail["latency_s"], r.latency_s = r.latency_s, None
            r.detail.update(question=question, answer=answer, expected=correct)
            if not right and model == ADMITTED:
                r.detail["problem"] = f"{model}: {question!r} -> {answer!r} (expected {correct!r})"
            results.append(r)
    return results
