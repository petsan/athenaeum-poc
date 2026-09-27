"""Batch 12, phase AY: every lab model answers the benchmark questions; only
the admitted model is gated. The lexical grader is checked here against all
of the benchmark's labelled answers."""
import pytest

pytest.importorskip("evalcore")

from evalcore import compute_gates                              # noqa: E402
from evalcore.records import Recorder                           # noqa: E402

from athenaeum_brain import judging_benchmark as jb             # noqa: E402
from athenaeum_evals import model_answers as ma                 # noqa: E402


def gates_for(results):
    rec = Recorder()
    rec.extend(results)
    return {g.name: g for g in compute_gates(rec, [ma.SUITE])}


def test_the_grader_agrees_with_every_labelled_answer():
    assert len(jb.ITEMS) >= 60
    wrongly_right = [(q, w) for q, c, w in jb.ITEMS if ma.grade(w, c, w)]
    wrongly_wrong = [(q, c) for q, c, w in jb.ITEMS if not ma.grade(c, c, w)]
    assert wrongly_right == [] and wrongly_wrong == []


@pytest.mark.parametrize("answer, correct, wrong, right", [
    ("A spider has 8 legs.", "Eight", "Six", True),
    ("about 300,000 km/s", "About 300,000", "About 3,000", True),
    ("300 000", "About 300,000", "About 3,000", True),                 # found live: olmo3-7b
    ("3 000", "About 300,000", "About 3,000", False),
    ("It's Paris.", "Paris", "Berlin", True),
    ("Not Berlin; it is Paris", "Paris", "Berlin", False),   # names the wrong label: conservative
    ("0.4", "4", "5", False),                                # a digit inside a decimal is not the answer
    ("", "Paris", "Berlin", False),
    (None, "Paris", "Berlin", False),
    ("Shakespeare", "William Shakespeare", "Charles Dickens", False),   # a floor, as documented
])
def test_the_grader_on_answer_forms(answer, correct, wrong, right):
    assert ma.grade(answer, correct, wrong) is right


def oracle(q, model_name):
    return next(c for qq, c, _ in jb.ITEMS if qq == q)


def test_an_admitted_model_that_answers_right_passes():
    results = ma.evaluate(models=[ma.ADMITTED, "granite-2b"], ask=lambda q, model_name: (
        oracle(q, model_name) if model_name == ma.ADMITTED else "no idea"))
    g = gates_for(results)
    assert g["admitted_right"].status == "PASS" and g["admitted_answered"].status == "PASS"
    assert g["p95_latency_s"].status == "PASS" and g["mean_cost_usd"].status == "NOT_RUN"
    other = [r for r in results if r.category == "granite-2b"]
    assert all(r.metrics["right"] == 0.0 for r in other) and "admitted_right" not in other[0].metrics


def test_an_admitted_model_that_is_down_fails_to_answer():
    def down(q, model_name):
        raise ConnectionError("no route to host")
    results = ma.evaluate(models=[ma.ADMITTED], ask=down)
    assert all(r.metrics["answered"] == 0.0 for r in results)
    assert "ConnectionError: no route to host" in results[0].detail["error"]
    g = gates_for(results)
    assert g["admitted_answered"].status == "FAIL" and g["admitted_right"].status == "FAIL"


def test_only_the_admitted_models_misses_are_problems():
    results = ma.evaluate(models=[ma.ADMITTED, "granite-2b"], items=jb.ITEMS[:2], ask=lambda q, model_name: "no idea")
    assert [r.case_id for r in results if "problem" in r.detail] == [f"{ma.ADMITTED}/00", f"{ma.ADMITTED}/01"]
