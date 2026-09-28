"""Batch 12, phase AW: the judging benchmark as evalcore's judge-validation
suite. It passes only on a current, reviewed result whose Wilson lower bound
clears the bar; otherwise it withholds the metric (INSUFFICIENT, never PASS),
and every judge-scored gate elsewhere stays unproven."""
import pytest

pytest.importorskip("evalcore")

from evalcore import GateSpec, Suite, compute_gates           # noqa: E402
from evalcore.records import Recorder                          # noqa: E402

from athenaeum_brain import judging_benchmark as jb             # noqa: E402
from athenaeum_brain.model_backed_reasoning import DEFAULT_MODEL  # noqa: E402
from athenaeum_evals import judging, runner                     # noqa: E402

CURRENT = {"benchmark_version": jb.BENCHMARK_VERSION, "prompt_version": jb.PROMPT_VERSION}


def gate_for(metric):
    rec = Recorder()
    rec.set_metric(judging.KEY, "challenger_agreement", metric)
    return compute_gates(rec, [judging.SUITE])[0]


@pytest.mark.parametrize("result, reviewed, status, note", [
    (None, True, "INSUFFICIENT_DATA", "never run"),
    ({**CURRENT, "benchmark_version": "old", **jb.score(120, 120)}, True, "INSUFFICIENT_DATA", "older items"),
    ({**CURRENT, "accuracy": 1.0}, True, "INSUFFICIENT_DATA", "before the Wilson rule"),
    ({**CURRENT, **jb.score(120, 120)}, False, "INSUFFICIENT_DATA", "benchmark provisional"),
    ({**CURRENT, **jb.score(120, 120)}, True, "PASS", "120/120 cases"),
    ({**CURRENT, **jb.score(119, 120)}, True, "PASS", "119/120"),
    ({**CURRENT, **jb.score(118, 120)}, True, "FAIL", "118/120"),       # two misses: the bound falls below 0.95
    ({**CURRENT, **jb.score(96, 120)}, True, "FAIL", "96/120"),
])
def test_the_suite_passes_only_what_the_runtime_would_accept(result, reviewed, status, note):
    g = gate_for(judging.agreement(result, reviewed))
    assert g.status == status and note in g.detail


def test_judge_scored_gates_elsewhere_depend_on_it():
    rag = Suite(key="provenance", title="Provenance", judge_metrics=frozenset({"citation_support"}),
                suite_gates=[GateSpec("citation_support", "Citation support", ">=", 0.5, min_n=1)])
    rec = Recorder()
    from evalcore import SuiteMetric
    rec.set_metric("provenance", "citation_support", SuiteMetric(0.9, 0.85, 0.95, n=50))
    rec.set_metric(judging.KEY, "challenger_agreement", judging.agreement({**CURRENT, **jb.score(120, 120)}, False))
    support = next(g for g in compute_gates(rec, [rag, judging.SUITE]) if g.name == "citation_support")
    assert support.status == "INSUFFICIENT_DATA" and "judge not validated" in support.detail


def test_the_runner_reads_the_store(tmp_path, monkeypatch):
    store = judging.store_at(tmp_path)
    store.record_judging(DEFAULT_MODEL,
                         {**CURRENT, **jb.score(120, 120), "misses": []})
    monkeypatch.setattr(judging, "DATA_DIR", tmp_path)
    monkeypatch.setattr(jb, "reviewed", lambda: False)             # a provisional benchmark, whatever the file says
    result = runner.run(tmp_path / "out", ["judging"])
    gate = next(g for g in result.gates if g.name == "challenger_agreement")
    assert gate.status == "INSUFFICIENT_DATA" and "provisional" in gate.detail     # the benchmark isn't reviewed yet
    assert result.verdict.status == "NOT APPROVED"
