"""Does deliberation commit the right answer, however the question is worded?

Each golden question (evals/golden/deliberation.json) runs through the real
four rounds, once as written and once per paraphrase. A wording is correct
when every expected statement is committed (an expectation may list
alternatives, e.g. either order of two events) and nothing forbidden is.
A forbidden statement is a known-wrong answer; committing one is a hard
violation, because a wrong answer is worse than a missing one. The
robustness gate compares accuracy on the original wordings with accuracy on
the paraphrases.

Every committed claim that an expectation or a prohibition identifies is
also labelled right or wrong, with its agent and confidence: that is the
data the calibration suite scores. Every committed claim's provenance is
kept too, for the provenance suite.
"""
from __future__ import annotations

import time
import traceback
from pathlib import Path

from evalcore import CaseResult, CoverageCheck, GateSpec, Suite
from evalcore.golden import check_categories, expand_variants, load_items

from athenaeum_brain.rounds import cross_examination_round, exploration_round, framing_round, synthesis_round

KEY = "deliberation"
GOLDEN_FILE = "deliberation.json"
GOLDEN = Path(__file__).resolve().parents[2] / "evals" / "golden" / GOLDEN_FILE
CATEGORIES = ("primality", "rounding", "free_fall", "chronology", "is_ought", "tradition", "regression")
# Only these claim types have a checkable truth to calibrate against:
# normative and traditional claims are premise-dependent by design (§6.4).
CALIBRATED_TYPES = ("formal", "empirical")


def _validate(item: dict) -> dict:
    for field in ("id", "category", "question", "expect", "forbid"):
        if field not in item:
            raise ValueError(f"golden item {item.get('id', '?')}: missing {field!r}")
    if item["category"] not in CATEGORIES:
        raise ValueError(f"golden item {item['id']}: unknown category {item['category']!r}")
    if not item["expect"] and not item["forbid"]:
        raise ValueError(f"golden item {item['id']}: checks nothing (no expect, no forbid)")
    return item


def _categories_present(results, _metrics):
    missing = sorted(set(CATEGORIES) - {r.category for r in results})
    return (not missing, "Every question category ran" if not missing
            else f"Question categories with no case: {', '.join(missing)}")


def _paraphrases_ran(results, _metrics):
    n = sum(1 for r in results if r.variant != "original")
    return (n > 0, f"Paraphrases ran ({n} wordings)")


SUITE = Suite(
    key=KEY, title="Deliberation accuracy (golden questions and paraphrases)",
    per_case_gates=[GateSpec("correct", "Right answer committed", ">=", "deliberation_min_accuracy")],
    hard_gate_label="Known-wrong answers committed",
    robustness=("correct", "deliberation_max_robustness_gap"),
    primary_metrics=("correct",),
    defaults={"deliberation_min_accuracy": 0.90, "deliberation_max_robustness_gap": 0.05},
    golden_files=(GOLDEN_FILE,),
    coverage=[CoverageCheck(_categories_present), CoverageCheck(_paraphrases_ran)],
)


def items(path: Path | None = None) -> list[dict]:
    loaded = load_items(path or GOLDEN, validate=_validate)
    missing = check_categories(loaded, CATEGORIES)
    if missing:
        raise ValueError(f"{GOLDEN_FILE}: no questions in categories {missing}")
    return loaded


def deliberate(question: str, question_id: str) -> list:
    """The committed claims of one real four-round deliberation."""
    frame = framing_round(question, question_id)
    exp = exploration_round(frame, question_id)
    return synthesis_round(exp, cross_examination_round(exp, question_id))["committed"]


def _alternatives(expectation) -> list[str]:
    return [expectation] if isinstance(expectation, str) else list(expectation)


def grade(item: dict, committed: list) -> dict:
    """Which expectations were met, which forbidden statements appeared, and
    a right/wrong label for every committed claim either one identifies."""
    statements = [c.statement for c in committed]
    missing = [" or ".join(_alternatives(e)) for e in item["expect"]
               if not any(alt in s for alt in _alternatives(e) for s in statements)]
    wrong = sorted({s for s in statements for f in item["forbid"] if f in s})
    labelled = []
    for c in committed:
        if c.claim_type not in CALIBRATED_TYPES:
            continue
        right = any(alt in c.statement for e in item["expect"] for alt in _alternatives(e))
        bad = any(f in c.statement for f in item["forbid"])
        if right or bad:
            labelled.append({"agent": c.issuing_agent, "confidence": float(c.confidence),
                             "verified": bool(right and not bad)})
    return {"missing": missing, "wrong": wrong, "labelled": labelled}


def evaluate(golden: list[dict] | None = None, deliberate_fn=None) -> list[CaseResult]:
    golden = items() if golden is None else golden
    deliberate_fn = deliberate_fn or deliberate
    results = []
    for item, variant, text in expand_variants(golden, "question"):
        result = CaseResult(KEY, item["id"], item["category"], variant, 0)
        result.detail["question"] = text
        started = time.perf_counter()
        try:
            committed = deliberate_fn(text, f"eval-{item['id']}-{variant}")
            g = grade(item, committed)
        except Exception as e:                          # a crash is a wrong answer, and is shown
            g = {"missing": [" or ".join(_alternatives(x)) for x in item["expect"]], "wrong": [], "labelled": []}
            result.detail["error"] = "".join(traceback.format_exception_only(type(e), e)).strip()
            committed = []
        result.latency_s = time.perf_counter() - started
        result.metrics["correct"] = float(not g["missing"] and not g["wrong"] and "error" not in result.detail)
        result.hard_violations += [f"committed a known-wrong answer: {s}" for s in g["wrong"]]
        result.detail.update(committed=[c.statement for c in committed], labelled=g["labelled"],
                             cited=[list(c.supporting_provenance) for c in committed])   # the provenance suite checks these
        if result.metrics["correct"] < 1:
            why = result.detail.get("error") or "; ".join(
                [f"missing: {m}" for m in g["missing"]] + [f"wrong: {w}" for w in g["wrong"]])
            result.detail["problem"] = f"{item['id']} ({variant}): {why}"
        results.append(result)
    return results
