"""Batch 12, phase AZ: the fault matrix. Each tool must catch the fault it
exists for and stay quiet on the healthy system; a deliberately broken tool
must visibly lose its catch rate."""
import pytest

pytest.importorskip("evalcore")

from athenaeum_brain import model_backed_reasoning              # noqa: E402
from athenaeum_evals import faults, provenance                  # noqa: E402


@pytest.fixture(scope="module")
def recorded(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)
    try:
        yield faults.record(tmp_path_factory.mktemp("rec"))
    finally:
        mp.undo()


@pytest.fixture(scope="module")
def measured(recorded):
    return faults.matrix(recorded, trials=8)


def test_every_tool_catches_its_fault_and_never_cries_wolf(measured):
    summary = {s["tool"]: s for s in measured["summary"]}
    assert set(summary) == {t["name"] for t in measured["tools"]} and len(summary) == 11
    assert {name: s["false_alarm"]["rate"] for name, s in summary.items() if s["false_alarm"]["rate"]} == {}
    assert {name: s["catch"]["rate"] for name, s in summary.items() if s["catch"]["rate"] < 0.5} == {}


def test_every_fault_is_some_tools_target(measured):
    targeted = {f for t in measured["tools"] for f in t["targets"]}
    assert targeted == {f["name"] for f in measured["faults"]} - {"healthy"}


def test_the_page_says_what_the_rates_describe(measured):
    assert "not any real system" in measured["note"]
    assert "fresh random draw" in measured["conditions"]["how a trial works"]


def test_a_broken_canary_check_loses_its_catch_rate(recorded, monkeypatch):
    monkeypatch.setattr(provenance, "leak", lambda fixture, text: None)       # the check is switched off
    summary = {s["tool"]: s for s in faults.matrix(recorded, trials=8)["summary"]}
    assert summary["canary_leak"]["catch"]["rate"] == 0.0


def test_the_heuristic_is_measured_per_document(recorded):
    """One of the five instruction-bearing fixtures has none of its patterns,
    so its catch rate sits below 1; the clean fixtures raise no alarm."""
    from evalcore.efficacy import run_matrix
    tool = next(t for t in faults._tools(recorded) if t.name == "injection_heuristic")
    fault = next(f for f in faults.FAULTS if f.name == "injected_docs")
    [heuristic] = run_matrix([tool], [fault], {"faults": set()}, trials=200)["summary"]
    assert 0.5 < heuristic["catch"]["rate"] < 1.0 and heuristic["false_alarm"]["rate"] == 0.0


def test_the_matrix_is_reproducible(recorded):
    a, b = faults.matrix(recorded, trials=3, seed=7), faults.matrix(recorded, trials=3, seed=7)
    assert a["cells"] == b["cells"]


def test_the_dashboard_builds_from_a_saved_matrix(measured, tmp_path):
    import json
    import subprocess
    import sys
    from pathlib import Path
    eff = tmp_path / "efficacy.json"
    eff.write_text(json.dumps(measured), encoding="utf-8")
    script = Path(__file__).resolve().parents[1] / "scripts" / "build_dashboard.py"
    out = subprocess.run([sys.executable, str(script), "--efficacy", str(eff), "--out", str(tmp_path / "d"),
                          "--runs", str(tmp_path / "none")], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    page = (tmp_path / "d" / "index.html").read_text(encoding="utf-8")
    assert "Athenaeum evaluation dashboard" in page and "Injection canaries (hard gate)" in page
    assert "<script" not in page


def test_rates_are_also_reported_when_the_fault_showed_up(measured):
    """evalcore 0.1.2: a sparse fault sometimes touches nothing. Over the runs
    where it did, the hard-gate tools catch every case."""
    summary = {s["tool"]: s for s in measured["summary"]}
    assert all("when_manifested" in s for s in summary.values())
    for tool in ("canary_leak", "governance", "input_obeyed", "fabricated_provenance", "wrong_answers"):
        s = summary[tool]
        assert s["when_manifested"]["rate"] == 1.0, tool
        assert s["catch"]["rate"] <= s["when_manifested"]["rate"]


def test_a_fault_that_touches_nothing_is_not_counted_as_manifested(recorded):
    """Dropping the answers of a question that had none changes nothing."""
    from evalcore.efficacy import run_matrix
    tool = next(t for t in faults._tools(recorded) if t.name == "accuracy")
    fault = next(f for f in faults.FAULTS if f.name == "missing_answers")
    [cell] = [c for c in run_matrix([tool], [fault], {"faults": set()}, trials=5)["cells"] if c["fault"] == fault.name]
    assert 0 < cell["manifested"] <= cell["trials"]
