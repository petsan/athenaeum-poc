"""Section 8 / 9.2: every failure mode in brain-design.md's table has at
least one real adversarial check, and the two mechanisms added to make
that possible (stale-frame materiality, Physics's falsifiability check)
behave correctly on their own."""
import pathlib
import re
import pytest
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.calibration_store import CalibrationStore
from athenaeum_body.ledger import QuestionLedger
from athenaeum_body.schemas import QuestionLedgerEntry
from athenaeum_body.reputability_store import ReputabilityStore
from athenaeum_brain import model_backed_reasoning
from athenaeum_brain.agents import MasterOfPhysics
from athenaeum_brain.claims import Claim
from athenaeum_brain.rounds import framing_round
from athenaeum_brain.reevaluation import frame_staleness
from athenaeum_brain.reopening import reopen_if_material
from athenaeum_brain.audits import reevaluation_audit
from athenaeum_brain.evaluation import (
    ADVERSARIAL_CASES, SECTION_8_COVERAGE, run_adversarial_suite, calibration_drift,
)

DESIGN = pathlib.Path(__file__).parent.parent / "docs" / "brain-design.md"


@pytest.fixture(autouse=True)
def _no_model_fallback(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)


def _section_8_rows() -> list[str]:
    text = DESIGN.read_text(encoding="utf-8")
    section = text.split("## 8. Failure Modes Specific to Cognition", 1)[1].split("\n## ", 1)[0]
    return [re.match(r"\| \*\*(.+?)\*\*", line).group(1)
            for line in section.splitlines() if re.match(r"\| \*\*", line)]


def test_every_row_of_the_design_table_has_a_real_check():
    rows = _section_8_rows()
    assert len(rows) == 15
    assert set(rows) == set(SECTION_8_COVERAGE)
    for row, cases in SECTION_8_COVERAGE.items():
        assert cases and all(c in ADVERSARIAL_CASES for c in cases), row
    assert {c for cases in SECTION_8_COVERAGE.values() for c in cases} == set(ADVERSARIAL_CASES)


def test_the_whole_suite_passes():
    suite = run_adversarial_suite()
    assert suite["passed"] == suite["total"] == 16, suite["results"]


# --- falsifiability (Physics) --------------------------------------------------------

def _empirical(defeat, agent="WorldNews"):
    return Claim(question_id="q", round=1, issuing_agent=agent, statement="s", claim_type="empirical",
                 confidence=0.7, defeat_condition=defeat, jurisdiction_check=True)


@pytest.mark.parametrize("defeat", ["", "  ", "none", "N/A", "Nothing.", "cannot be falsified"])
def test_vacuous_defeat_conditions_are_challenged(defeat):
    resp = MasterOfPhysics().cross_examine(_empirical(defeat), "q")
    assert resp.relation == "challenges" and "unfalsifiable" in resp.statement


def test_non_empirical_and_own_claims_are_not_policed():
    physics = MasterOfPhysics()
    normative = _empirical("none")
    normative.claim_type = "normative"
    assert physics.cross_examine(normative, "q") is None
    assert physics.cross_examine(_empirical("none", agent="Physics"), "q") is None


# --- stale framing ----------------------------------------------------------------

def test_staleness_names_what_changed():
    q = "should we round 2.5 up or down?"
    old = {"question": q, "frame": {"routed_agents": ["Mathematics", "Theology"], "output_types": ["research"]}}
    reasons = frame_staleness(old)["reasons"]
    assert any("now also routed to Engineering, Philosophy" in r for r in reasons)
    assert any("no longer routed to Theology" in r for r in reasons)
    assert any("output types now ['research', 'recommendation']" in r for r in reasons)


def test_answers_without_a_recorded_frame_are_not_called_stale():
    assert frame_staleness({"committed": []}) == {"stale": False, "reasons": []}


def _ledger_with_old_frame(tmp_path, importance):
    cas = ContentAddressedStore(tmp_path / "cas")
    ledger = QuestionLedger(CheckpointLog(cas=cas, index_path=tmp_path / "l.txt"))
    rep = ReputabilityStore(CheckpointLog(cas=cas, index_path=tmp_path / "r.txt"))
    q = "how should we round 2.5?"
    ledger.submit(QuestionLedgerEntry(id="q1", importance=importance))
    ledger.append_version("q1", {"question": q, "frame": {**framing_round(q, "x"), "routed_agents": ["Mathematics"]},
                                 "committed": [], "dissent": [], "plural_answers": []})
    return ledger, rep, CheckpointLog(cas=cas, index_path=tmp_path / "u.txt")


def test_a_stale_frame_reopens_an_important_question(tmp_path):
    ledger, rep, unit_log = _ledger_with_old_frame(tmp_path, importance=0.9)
    result = reopen_if_material(ledger, "q1", reputability=rep, unit_log=unit_log)
    assert result["reopened"] is True
    assert any("frame outdated" in c for c in result["answer"]["diff"]["cause"])
    assert frame_staleness(ledger.get("q1").versions[-1])["stale"] is False  # the new version is current


def test_a_stale_frame_shows_up_as_stagnation_until_reopened(tmp_path):
    ledger, rep, _ = _ledger_with_old_frame(tmp_path, importance=0.0)
    [candidate] = reevaluation_audit(ledger, rep, audit_id="a")["stagnation_candidates"]
    assert any("frame outdated" in r for r in candidate["reasons"])


# --- calibration drift --------------------------------------------------------------

def _store(tmp_path):
    return CalibrationStore(CheckpointLog(cas=ContentAddressedStore(tmp_path / "cas"),
                                          index_path=tmp_path / "cal.txt"))


def test_drift_needs_enough_evidence(tmp_path):
    store = _store(tmp_path)
    for _ in range(4):
        store.record("A", 0.95, verified=False)
    assert calibration_drift(store, "A")["drifting"] is False  # n=4 < min_n
    store.record("A", 0.95, verified=False)
    assert calibration_drift(store, "A")["drifting"] is True


def test_underconfidence_is_reported_but_is_not_drift(tmp_path):
    store = _store(tmp_path)
    for _ in range(6):
        store.record("A", 0.35, verified=True)
    report = calibration_drift(store, "A")
    assert report["drifting"] is False and report["underconfident_buckets"][0]["bucket"] == "0.3-0.4"
