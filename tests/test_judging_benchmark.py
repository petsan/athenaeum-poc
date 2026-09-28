"""Owner decisions 11 and D15 (batch 12, phase AW): a challenger model qualifies
on a judging benchmark -- balanced, labelled, versioned, reviewed -- judged on
the Wilson lower bound (evalcore), not on a point estimate and not on the
standing of its own answers."""
import json

import pytest
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.model_fitness_store import ModelFitnessStore
from athenaeum_brain import model_backed_reasoning
from athenaeum_brain import judging_benchmark as jb
from athenaeum_brain.model_backed_reasoning import DEFAULT_MODEL


def judge_by(rule):
    """A stub model: `rule(question, answer, is_correct)` -> its verdict text."""
    labels = {(q, a): ok for q, a, ok in jb.cases()}

    def ask_model(prompt, *a, **k):
        for (q, a), ok in labels.items():
            if f'The answer to "{q}" is "{a}".' in prompt:
                return rule(q, a, ok)
        raise AssertionError(f"unexpected prompt {prompt!r}")
    return ask_model


def perfect(q, a, ok):
    return "yes" if ok else "no"


@pytest.fixture
def store(tmp_path):
    return ModelFitnessStore(CheckpointLog(cas=ContentAddressedStore(tmp_path / "cas"), index_path=tmp_path / "f.txt"))


def test_the_benchmark_is_balanced_versioned_and_its_review_recorded():
    cases = jb.cases()
    assert len(cases) == 120 and sum(ok for _, _, ok in cases) == 60
    assert len({q for q, _, _ in cases}) == 60                      # each question judged both ways
    assert len(jb.BENCHMARK_VERSION) == len(jb.PROMPT_VERSION) == 16
    assert not any("continents" in q for q, _, _ in cases)          # convention-dependent: removed
    assert jb.REVIEW["status"] in ("provisional", "reviewed")
    assert jb.reviewed() == (jb.REVIEW["status"] == "reviewed")
    assert jb.REVIEW["reviewed_by"] if jb.reviewed() else jb.REVIEW["reviewed_by"] is None   # who approved it, when it is
    assert jb.misses_allowed() == 1                                 # 120 cases prove 0.95 with one miss


def test_a_perfect_judge_passes_on_the_wilson_bound(monkeypatch):
    monkeypatch.setattr(jb, "reviewed", lambda: False)             # the review state is set by each test, not the file
    monkeypatch.setattr(model_backed_reasoning, "ask_model", judge_by(perfect))
    result = jb.run_benchmark(DEFAULT_MODEL, repeats=2)
    assert (result["correct"], result["total"], result["cases_right"], result["cases"]) == (240, 240, 120, 120)
    assert result["passed"] and result["wilson_low"] >= jb.QUALIFYING_ACCURACY and result["misses"] == []
    assert result["reviewed"] is False


@pytest.mark.parametrize("wrong, passes", [(1, True), (2, False)])
def test_one_miss_is_allowed_two_are_not(monkeypatch, wrong, passes):
    doubted = [(q, a) for q, a, ok in jb.cases() if ok][:wrong]    # (question, answer): "100" answers two questions
    monkeypatch.setattr(model_backed_reasoning, "ask_model",
                        judge_by(lambda q, a, ok: "no" if (not ok or (q, a) in doubted) else "yes"))
    result = jb.run_benchmark(DEFAULT_MODEL)
    assert result["cases_right"] == 120 - wrong and result["passed"] is passes


def test_a_case_counts_only_if_every_repeat_was_right(monkeypatch):
    seen = {}

    def flaky(q, a, ok):                        # right the first time, wrong the second, on one case
        seen[(q, a)] = seen.get((q, a), 0) + 1
        if (q, a) == ("what is 2 + 2?", "4") and seen[(q, a)] == 2:
            return "no"
        return perfect(q, a, ok)
    monkeypatch.setattr(model_backed_reasoning, "ask_model", judge_by(flaky))
    result = jb.run_benchmark(DEFAULT_MODEL, repeats=2)
    assert result["correct"] == 239 and result["cases_right"] == 119


def test_the_measured_no_bias_does_not_qualify(monkeypatch):
    # rejects three true answers, as OLMo 3 7B did live (known-bugs #36)
    doubted = {"Gravity", "Paris", "4"}
    monkeypatch.setattr(model_backed_reasoning, "ask_model",
                        judge_by(lambda q, a, ok: "no" if (not ok or a in doubted) else "yes"))
    result = jb.run_benchmark(DEFAULT_MODEL)
    assert result["cases_right"] == 117 and not result["passed"]
    assert {m["answer"] for m in result["misses"]} == doubted
    assert all(m["is_correct"] and m["judged"] == "challenged" for m in result["misses"])


def test_an_unreachable_model_cannot_pass_by_accepting_everything(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)
    result = jb.run_benchmark(DEFAULT_MODEL)
    assert result["accuracy"] == 0.5 and not result["passed"]


def test_qualification_needs_a_current_passing_reviewed_result(store, monkeypatch):
    assert jb.challenger_qualified(None, DEFAULT_MODEL) == (False, "no fitness store to read a benchmark result from")
    assert jb.challenger_qualified(store, DEFAULT_MODEL) == (False, "never run on the judging benchmark")
    current = {"benchmark_version": jb.BENCHMARK_VERSION, "prompt_version": jb.PROMPT_VERSION}
    store.record_judging(DEFAULT_MODEL, {**current, "accuracy": 1.0})             # a pre-Wilson record
    assert jb.challenger_qualified(store, DEFAULT_MODEL)[1] == "recorded before the Wilson rule; run it again"
    store.record_judging(DEFAULT_MODEL, {**current, **jb.score(112, 120)})
    ok, why = jb.challenger_qualified(store, DEFAULT_MODEL)
    assert not ok and why.startswith("112/120 cases, Wilson lower bound 0.8") and "below the 0.95 needed" in why
    monkeypatch.setattr(jb, "reviewed", lambda: False)
    store.record_judging(DEFAULT_MODEL, {**current, **jb.score(120, 120)})
    ok, why = jb.challenger_qualified(store, DEFAULT_MODEL)
    assert not ok and why.endswith("but the benchmark is provisional (awaiting the owner's review)")
    monkeypatch.setattr(jb, "reviewed", lambda: True)
    assert jb.challenger_qualified(store, DEFAULT_MODEL) == (
        True, "120/120 cases, Wilson lower bound 0.969 on the current, reviewed benchmark")
    store.record_judging(DEFAULT_MODEL, {**current, **jb.score(120, 120), "prompt_version": "older"})
    assert jb.challenger_qualified(store, DEFAULT_MODEL)[1] == "the challenge prompt has changed since its last run"
    store.record_judging(DEFAULT_MODEL, {**current, **jb.score(120, 120), "benchmark_version": "older"})
    assert jb.challenger_qualified(store, DEFAULT_MODEL)[1] == "the benchmark has changed since its last run"
    assert len(store.judging_history(DEFAULT_MODEL)) == 5          # every run kept


def test_review_status_is_read_fresh(tmp_path, monkeypatch):
    data = json.loads(jb.DATA.read_text(encoding="utf-8"))
    copy = tmp_path / "judging_benchmark.json"
    monkeypatch.setattr(jb, "DATA", copy)
    for status in ("provisional", "reviewed", "provisional"):          # no restart needed either way
        data["review"]["status"] = status
        copy.write_text(json.dumps(data), encoding="utf-8")
        assert jb.reviewed() == (status == "reviewed")


def test_the_api_reports_each_challengers_status(tmp_path, monkeypatch):
    from athenaeum_body.api import build_app
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)
    app = build_app(tmp_path)
    assert app.maintenance_status()["challengers"] == {
        DEFAULT_MODEL: {"counts": False, "why": "never run on the judging benchmark"}}


def test_the_script_records_a_result(tmp_path, monkeypatch, capsys):
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "scripts" / "run_judging_benchmark.py"
    spec = importlib.util.spec_from_file_location("run_judging_benchmark", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(jb, "reviewed", lambda: False)
    monkeypatch.setattr(model_backed_reasoning, "ask_model", judge_by(perfect))
    module.main(["--repeats", "1", "--record", str(tmp_path)])
    out = capsys.readouterr().out
    assert "120/120 cases" in out and "Wilson lower bound 0.969" in out and "passes the bar" in out
    assert "provisional (awaiting the owner's review)" in out
