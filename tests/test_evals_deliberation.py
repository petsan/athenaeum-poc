"""Batch 12, phase AX: deliberation accuracy over golden questions and their
paraphrases, and per-agent calibration of the claims it labels.

These run the deterministic agents only (model fallbacks off): what the lab
models add is measured by the nightly run, not asserted here."""
import json
import math

import pytest

pytest.importorskip("evalcore")

from evalcore import Config, compute_gates                     # noqa: E402
from evalcore.records import CaseResult, Recorder              # noqa: E402

from athenaeum_brain import model_backed_reasoning             # noqa: E402
from athenaeum_brain.claims import Claim                       # noqa: E402
from athenaeum_evals import calibration, deliberation, runner  # noqa: E402


@pytest.fixture(autouse=True)
def _deterministic(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)


@pytest.fixture(scope="module")
def real_results():
    mp = pytest.MonkeyPatch()
    mp.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)
    try:
        yield deliberation.evaluate()
    finally:
        mp.undo()


def claim(statement, agent="Mathematics", confidence=1.0, claim_type="formal"):
    return Claim(question_id="q", round=1, issuing_agent=agent, statement=statement, claim_type=claim_type,
                 confidence=confidence, defeat_condition="x", jurisdiction_check=True)


def gates_for(results, suites=None, metrics=None):
    rec = Recorder()
    rec.extend(results)
    for name, m in (metrics or {}).items():
        rec.set_metric(calibration.KEY, name, m)
    return {g.name: g for g in compute_gates(rec, suites or [deliberation.SUITE])}


# --- the golden set -------------------------------------------------------

def test_the_golden_set_covers_every_category_with_paraphrases():
    items = deliberation.items()
    assert len(items) >= 30
    assert {i["category"] for i in items} == set(deliberation.CATEGORIES)
    assert all(len(i.get("paraphrases", [])) >= 2 for i in items)


@pytest.mark.parametrize("bad, message", [
    ({"id": "x", "category": "astrology", "question": "?", "expect": ["a"], "forbid": []}, "unknown category"),
    ({"id": "x", "category": "primality", "question": "?", "expect": [], "forbid": []}, "checks nothing"),
    ({"id": "x", "category": "primality", "question": "?", "expect": ["a"]}, "missing 'forbid'"),
])
def test_malformed_golden_items_are_refused(tmp_path, bad, message):
    path = tmp_path / "g.json"
    path.write_text(json.dumps([bad]), encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        deliberation.items(path)


def test_every_wording_gets_the_right_answer(real_results):
    assert len(real_results) == 3 * len(deliberation.items())
    wrong = [r.detail["problem"] for r in real_results if r.metrics["correct"] < 1]
    assert wrong == []
    assert not any(r.hard_violations for r in real_results)
    g = gates_for(real_results)
    assert g["correct"].status == "PASS" and g["hard_violations"].status == "PASS"
    assert g["robustness_gap"].status == "PASS"


# --- grading --------------------------------------------------------------

ITEM = {"id": "chrono", "category": "chronology", "question": "q?", "paraphrases": ["p?"],
        "expect": [["A before B", "B after A"]], "forbid": ["A after B"]}


@pytest.mark.parametrize("committed, correct, violations", [
    (["A before B"], 1.0, 0),
    (["B after A"], 1.0, 0),                       # either order of mention
    ([], 0.0, 0),                                  # missing: wrong, but not a violation
    (["A before B", "A after B"], 0.0, 1),         # a known-wrong answer committed alongside
])
def test_grading(committed, correct, violations):
    [r, _] = deliberation.evaluate([ITEM], lambda q, qid: [claim(s) for s in committed])
    assert r.metrics["correct"] == correct and len(r.hard_violations) == violations
    assert ("problem" in r.detail) == (correct < 1)


def test_a_known_wrong_answer_rejects_the_release():
    results = deliberation.evaluate([ITEM], lambda q, qid: [claim("A after B")])
    assert gates_for(results)["hard_violations"].status == "FAIL"
    assert "committed a known-wrong answer: A after B" in results[0].hard_violations


def test_a_crashing_deliberation_is_a_wrong_answer():
    def boom(q, qid):
        raise RuntimeError("synthesis failed")
    [r, _] = deliberation.evaluate([ITEM], boom)
    assert r.metrics["correct"] == 0.0 and "RuntimeError: synthesis failed" in r.detail["problem"]


def test_a_paraphrase_that_breaks_shows_as_a_robustness_gap():
    items = [dict(ITEM, id=f"c{i}", paraphrases=["p?"]) for i in range(40)]
    fn = lambda q, qid: [claim("A before B")] if q == "q?" else []       # noqa: E731
    g = gates_for(deliberation.evaluate(items, fn))
    assert g["robustness_gap"].status == "FAIL"


def test_only_checkable_claims_are_labelled_for_calibration():
    committed = [claim("A before B", "WorldNews", 1.0, "empirical"), claim("A after B", "Physics", 0.9, "empirical"),
                 claim("A before B", "Philosophy", 0.9, "normative"), claim("unrelated", "Mathematics", 1.0)]
    labelled = deliberation.grade(ITEM, committed)["labelled"]
    assert labelled == [{"agent": "WorldNews", "confidence": 1.0, "verified": True},
                        {"agent": "Physics", "confidence": 0.9, "verified": False}]


# --- calibration ----------------------------------------------------------

def labelled_results(rows):
    """rows: (case, agent, confidence, verified)"""
    out = []
    for case, agent, conf, ok in rows:
        r = CaseResult(deliberation.KEY, case, "x", "original", 0)
        r.detail["labelled"] = [{"agent": agent, "confidence": conf, "verified": ok}]
        out.append(r)
    return out


def test_the_real_claims_are_calibrated_and_the_card_says_what_that_means(real_results):
    m = calibration.metrics(real_results, baseline_confidences=None)
    assert m["ece"].n >= 60 and m["ece"].value < 0.05
    assert "none wrong, so this measures only under-confidence" in m["ece"].detail["note"]
    g = gates_for([], [calibration.SUITE], {k: v for k, v in m.items()})
    assert g["ece"].status == "PASS" and g["brier"].status == "PASS"
    assert g["worst_agent_ece"].status == "PASS"


def test_an_overconfident_agent_fails_the_worst_agent_gate():
    rows = [(f"m{i}", "Mathematics", 1.0, True) for i in range(40)]
    rows += [(f"p{i}", "Physics", 0.95, i % 2 == 0) for i in range(40)]      # says 95%, right half the time
    m = calibration.metrics(labelled_results(rows), baseline_confidences=None)
    assert m["worst_agent_ece"].detail["note"].startswith("worst: Physics")
    g = gates_for([], [calibration.SUITE], m)
    assert g["worst_agent_ece"].status == "FAIL" and g["ece"].status == "FAIL"


def test_agents_with_too_few_claims_are_named_not_gated():
    rows = [(f"m{i}", "Mathematics", 1.0, True) for i in range(40)] + [("t", "Theology", 0.75, True)]
    note = calibration.metrics(labelled_results(rows), baseline_confidences=None)["worst_agent_ece"].detail["note"]
    assert "not gated (fewer than 15 claims): Theology (n=1)" in note


def test_no_labelled_claims_is_insufficient_never_a_pass():
    m = calibration.metrics([], baseline_confidences=None)
    assert all(math.isnan(m[k].value) for k in ("ece", "brier", "worst_agent_ece"))
    g = gates_for([], [calibration.SUITE], m)
    assert {g[k].status for k in ("ece", "brier", "worst_agent_ece")} == {"INSUFFICIENT_DATA"}


def test_confidence_drift_is_optional_until_a_baseline_exists():
    rows = [(f"m{i}", "Mathematics", 1.0 if i % 2 else 0.9, True) for i in range(40)]
    first = calibration.metrics(labelled_results(rows), baseline_confidences=None)
    assert "confidence_psi" not in first
    assert gates_for([], [calibration.SUITE], first)["confidence_psi"].status == "NOT_RUN"
    same = calibration.metrics(labelled_results(rows), baseline_confidences=[r[2] for r in rows])
    assert same["confidence_psi"].value < 0.01
    shifted = calibration.metrics(labelled_results(rows), baseline_confidences=[0.6] * 20 + [0.7] * 20)
    assert gates_for([], [calibration.SUITE], shifted)["confidence_psi"].status == "FAIL"


def test_the_interval_resamples_questions_not_claims():
    # one question with 30 wrong claims: resampling claims would call this certain
    rows = [("big", "Physics", 0.9, False)] * 30 + [(f"q{i}", "Physics", 0.9, True) for i in range(30)]
    m = calibration.metrics(labelled_results(rows), baseline_confidences=None)["ece"]
    assert m.ci_high - m.ci_low > 0.3


# --- the runner -----------------------------------------------------------

def test_the_runner_scores_calibration_from_the_same_deliberations(tmp_path, monkeypatch):
    calls = []
    real = deliberation.evaluate
    monkeypatch.setattr(deliberation, "evaluate", lambda: calls.append(1) or real())
    result = runner.run(tmp_path / "out", ["deliberation", "calibration"], config=Config())
    assert calls == [1]                                               # run once, scored twice
    by_name = {g.name: g.status for g in result.gates}
    assert by_name["correct"] == "PASS" and by_name["ece"] == "PASS"
    assert result.verdict.status == "APPROVED"


def test_calibration_alone_runs_its_source(tmp_path, monkeypatch):
    real = deliberation.evaluate
    monkeypatch.setattr(deliberation, "evaluate", lambda: real()[:30])
    result = runner.run(tmp_path / "out", ["calibration"])
    assert {g.suite for g in result.gates} == {"calibration"}
