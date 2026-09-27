"""Batch 12, phase AV: the adversarial suite on evalcore. Every §8 failure
mode is a hard gate; a planted failing or crashing defence rejects the run."""
import pytest

evalcore = pytest.importorskip("evalcore")   # the evals need evalcore (LXC 104: /opt/athenaeum-venv)

from evalcore import compute_gates, verdict                   # noqa: E402
from evalcore.records import Recorder                         # noqa: E402

from athenaeum_brain.evaluation import ADVERSARIAL_CASES, SECTION_8_COVERAGE  # noqa: E402
from athenaeum_evals import adversarial, runner                 # noqa: E402


def decide(results):
    rec = Recorder()
    rec.extend(results)
    gates = compute_gates(rec, [adversarial.SUITE])
    return gates, verdict(gates, [], suites_run=rec.suites_seen(), required_suites=[adversarial.KEY])


def test_the_real_defences_all_hold():
    results = adversarial.evaluate()
    assert len(results) == len(ADVERSARIAL_CASES) == 16
    assert all(r.metrics["defended"] == 1.0 and not r.hard_violations for r in results)
    assert {r.category for r in results} == set(SECTION_8_COVERAGE)      # every §8 row, by name
    gates, v = decide(results)
    assert gates[0].name == "hard_violations" and gates[0].status == "PASS" and v.status == "APPROVED"


def test_one_undefended_failure_mode_rejects_the_release():
    checks = dict(ADVERSARIAL_CASES, circular_corroboration=lambda: False)
    gates, v = decide(adversarial.evaluate(checks))
    assert gates[0].status == "FAIL" and v.status == "REJECTED"
    assert "Circular corroboration: the defence did not hold" in gates[0].detail


def test_a_crashing_defence_counts_as_undefended():
    def boom():
        raise RuntimeError("store unavailable")
    results = adversarial.evaluate(dict(ADVERSARIAL_CASES, stale_framing=boom))
    crashed = next(r for r in results if r.case_id == "stale_framing")
    assert crashed.hard_violations == ["Stale framing: RuntimeError: store unavailable"]
    assert decide(results)[1].status == "REJECTED"


def test_the_card_says_when_a_section_8_row_went_unchecked():
    few = {k: v for k, v in ADVERSARIAL_CASES.items() if k != "lossy_compaction"}
    ran, label = adversarial._every_row_ran(adversarial.evaluate(few), {})
    assert not ran and "Lossy or unaccountable compaction" in label


def test_the_runner_writes_the_artifacts(tmp_path):
    result = runner.run(tmp_path, ["adversarial"])
    assert result.verdict.status == "APPROVED"
    card = result.paths["card"].read_text(encoding="utf-8")
    assert "- [x] Every §8 failure mode checked (15 of 15 rows)" in card
    with pytest.raises(ValueError, match="unknown suites"):
        runner.run(tmp_path, ["nope"])
