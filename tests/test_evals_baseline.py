"""Batch 13: the baseline covers the decidable suites (owner decision), is
compared suite by suite, and noisy gates carry tolerances in their own units."""
import json

import pytest

pytest.importorskip("evalcore")

from evalcore import CaseResult, Config                          # noqa: E402

from athenaeum_evals import api_service, model_answers, runner   # noqa: E402


def test_the_decidable_suites_are_all_but_judging_and_provenance():
    assert runner.DECIDABLE == ["adversarial", "deliberation", "calibration", "human_input", "api_service",
                                "model_answers"]


def test_noisy_gates_have_tolerances_in_their_own_units():
    assert api_service.SUITE.regression_tolerances["answer_p95_s"] == 30.0
    assert model_answers.SUITE.regression_tolerances["admitted_right"] == 0.10


def test_a_full_run_is_compared_with_a_decidable_baseline(tmp_path, monkeypatch):
    """The baseline, saved from some suites, still checks those suites when a
    later run adds the rest (before evalcore 0.1.2 it switched off entirely)."""
    from athenaeum_evals import provenance
    monkeypatch.setattr(runner, "BASELINE", tmp_path / "baseline.json")
    monkeypatch.setattr(provenance, "evaluate", lambda results: [CaseResult("provenance", "p", "cited", "original", 0,
                                                                           metrics={"abstained": 1.0})])
    monkeypatch.setattr(provenance, "SOURCE", "adversarial", raising=True)
    saved = runner.run(tmp_path / "a", ["adversarial"], save_as_baseline=True)
    assert saved.verdict.status == "APPROVED" and (tmp_path / "baseline.json").exists()
    base = json.loads((tmp_path / "baseline.json").read_text(encoding="utf-8"))
    assert "provenance" not in json.dumps(base["dataset_hashes"])
    later = runner.run(tmp_path / "b", ["adversarial", "provenance"])
    assert "Golden datasets changed" not in later.regression_note
    assert "Skipped, golden data changed or new since the baseline: provenance." in later.regression_note


def test_the_cli_accepts_decidable(monkeypatch, tmp_path):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("run_evals", Path(__file__).resolve().parents[1] / "scripts" / "run_evals.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    seen = {}

    class Result:
        verdict = type("V", (), {"status": "APPROVED", "reasons": []})()
        exit_code = 0
    monkeypatch.setattr(module.runner, "run", lambda out, suites, **kw: seen.update(suites=suites, **kw) or Result())
    assert module.main(["--suites", "decidable", "--save-baseline", "--out", str(tmp_path)]) == 0
    assert seen == {"suites": runner.DECIDABLE, "save_as_baseline": True}
