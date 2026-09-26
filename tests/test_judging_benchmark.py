"""Owner decision 11 (batch 11, Phase AR): a challenger model qualifies on a
judging benchmark -- balanced, labelled, versioned -- not on the standing of
its own answers."""
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


@pytest.fixture
def store(tmp_path):
    return ModelFitnessStore(CheckpointLog(cas=ContentAddressedStore(tmp_path / "cas"), index_path=tmp_path / "f.txt"))


def test_the_benchmark_is_balanced_and_versioned():
    cases = jb.cases()
    assert len(cases) == 24 and sum(ok for _, _, ok in cases) == 12
    assert len({q for q, _, _ in cases}) == 12                      # each question judged both ways
    assert len(jb.BENCHMARK_VERSION) == len(jb.PROMPT_VERSION) == 16


def test_a_perfect_judge_qualifies(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", judge_by(lambda q, a, ok: "yes" if ok else "no"))
    result = jb.run_benchmark(DEFAULT_MODEL, repeats=2)
    assert (result["correct"], result["total"], result["accuracy"], result["passed"]) == (48, 48, 1.0, True)
    assert result["misses"] == [] and result["prompt_version"] == jb.PROMPT_VERSION


def test_the_measured_no_bias_does_not_qualify(monkeypatch):
    # rejects three true answers, as OLMo 3 7B did live (known-bugs #36)
    doubted = {"Gravity", "Paris", "4"}
    monkeypatch.setattr(model_backed_reasoning, "ask_model",
                        judge_by(lambda q, a, ok: "no" if (not ok or a in doubted) else "yes"))
    result = jb.run_benchmark(DEFAULT_MODEL)
    assert result["correct"] == 21 and result["accuracy"] == 0.875 and not result["passed"]
    assert {m["answer"] for m in result["misses"]} == doubted
    assert all(m["is_correct"] and m["judged"] == "challenged" for m in result["misses"])


def test_an_unreachable_model_cannot_pass_by_accepting_everything(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)
    result = jb.run_benchmark(DEFAULT_MODEL)
    assert result["accuracy"] == 0.5 and not result["passed"]


def test_qualification_needs_a_current_passing_result(store):
    assert jb.challenger_qualified(None, DEFAULT_MODEL) == (False, "no fitness store to read a benchmark result from")
    assert jb.challenger_qualified(store, DEFAULT_MODEL) == (False, "never run on the judging benchmark")
    current = {"benchmark_version": jb.BENCHMARK_VERSION, "prompt_version": jb.PROMPT_VERSION}
    store.record_judging(DEFAULT_MODEL, {**current, "accuracy": 0.875})
    assert jb.challenger_qualified(store, DEFAULT_MODEL) == (False, "scored 88%, below the 95% needed")
    store.record_judging(DEFAULT_MODEL, {**current, "accuracy": 1.0})
    assert jb.challenger_qualified(store, DEFAULT_MODEL) == (True, "scored 100% on the current benchmark")
    store.record_judging(DEFAULT_MODEL, {**current, "prompt_version": "older", "accuracy": 1.0})
    assert jb.challenger_qualified(store, DEFAULT_MODEL)[1] == "the challenge prompt has changed since its last run"
    store.record_judging(DEFAULT_MODEL, {**current, "benchmark_version": "older", "accuracy": 1.0})
    assert jb.challenger_qualified(store, DEFAULT_MODEL)[1] == "the benchmark has changed since its last run"
    assert len(store.judging_history(DEFAULT_MODEL)) == 4          # every run kept


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
    monkeypatch.setattr(model_backed_reasoning, "ask_model", judge_by(lambda q, a, ok: "yes" if ok else "no"))
    module.main(["--repeats", "1", "--record", str(tmp_path)])
    out = capsys.readouterr().out
    assert "24/24 = 100%" in out and "QUALIFIES" in out and "(True, 'scored 100% on the current benchmark')" in out
