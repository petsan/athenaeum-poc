"""Sections 9.4 and 9.5: sampled, reproducible audits of re-evaluation
judgment and consolidation fidelity."""
import pytest
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.scheduler.runner import SingleUnitRunner
from athenaeum_body.ledger import QuestionLedger
from athenaeum_body.schemas import QuestionLedgerEntry
from athenaeum_body.reputability_store import ReputabilityStore
from athenaeum_body.consolidation_store import ConsolidationStore
from athenaeum_body.audit_store import AuditStore
from athenaeum_brain import model_backed_reasoning
from athenaeum_brain.loop import make_deliberation_unit
from athenaeum_brain.reopening import reopen_question
from athenaeum_brain.consolidation import record_survival, compact
from athenaeum_brain.audits import classify_reopen, reevaluation_audit, consolidation_audit


@pytest.fixture(autouse=True)
def _no_model_fallback(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)


class World:
    def __init__(self, tmp_path):
        self.tmp, self.cas, self.n = tmp_path, ContentAddressedStore(tmp_path / "cas"), 0
        self.ledger = QuestionLedger(self.log("ledger"))
        self.rep = ReputabilityStore(self.log("rep"))
        self.audits = AuditStore(self.log("audits"))
        self.archive = ContentAddressedStore(tmp_path / "archive")
        self.cons = ConsolidationStore(self.log("cons"), self.archive)

    def log(self, name):
        return CheckpointLog(cas=self.cas, index_path=self.tmp / f"{name}.txt")

    def fresh(self):
        self.n += 1
        return self.log(f"u{self.n}")

    def answer(self, qid, question):
        self.ledger.submit(QuestionLedgerEntry(id=qid))
        log = self.fresh()
        runner = SingleUnitRunner(log, shared_state={})
        unit = make_deliberation_unit(question, qid, reputability=self.rep)
        while unit.status != "completed":
            runner.run_round(unit)
        self.ledger.append_version(qid, log.read_latest()["shared_state"]["answer"])

    def reopen(self, qid):
        return reopen_question(self.ledger, qid, reasons=["audit test"], unit_log=self.fresh(), reputability=self.rep)

    def contest(self, src):
        for _ in range(3):
            self.rep.record_outcome(src, "source", "challenged")


# --- 9.4 classification --------------------------------------------------------------

@pytest.mark.parametrize("diff,expected", [
    ({"added": [], "removed": [], "weight_changes": [],
      "leading_conclusion": {"change": "unchanged", "confidence": "same"}}, "no_change"),
    ({"added": [], "removed": [], "weight_changes": [{"claim": "x"}],
      "leading_conclusion": {"change": "unchanged", "confidence": "decreased"}}, "weights_only"),
    ({"added": ["x"], "removed": [], "weight_changes": [],
      "leading_conclusion": {"change": "none_before_or_after"}}, "weights_only"),
    ({"added": [], "removed": [], "weight_changes": [],
      "leading_conclusion": {"change": "changed", "from": "a", "to": "b"}}, "leading_changed"),
    ({"added": [], "removed": [], "weight_changes": [], "cause": ["forecast resolved: outcome=True"],
      "leading_conclusion": {"change": "unchanged", "confidence": "same"}}, "forecast_resolution"),
])
def test_reopen_classification(diff, expected):
    assert classify_reopen(diff) == expected


# --- 9.4 on real reopens -------------------------------------------------------------

def test_a_reopen_that_changed_nothing_is_a_thrash_suspect(tmp_path):
    w = World(tmp_path)
    w.answer("q1", "is 17 prime?")
    w.reopen("q1")  # nothing about its evidence changed
    report = reevaluation_audit(w.ledger, w.rep, audit_id="a1")
    assert [s["classification"] for s in report["sampled"]] == ["no_change"]
    assert report["thrash_suspect_rate"] == 1.0


def test_a_grade_driven_reopen_is_weights_only(tmp_path):
    w = World(tmp_path)
    w.answer("q1", "is 17 prime?")
    w.contest("computed:trial_division")
    w.reopen("q1")
    report = reevaluation_audit(w.ledger, w.rep, audit_id="a1")
    assert report["sampled"][0]["classification"] == "weights_only"
    assert report["thrash_suspect_rate"] == 0.0 and report["for_human_review"] == []


def test_material_but_never_reopened_is_a_stagnation_candidate(tmp_path):
    w = World(tmp_path)
    w.answer("q1", "is 17 prime?")
    w.contest("computed:trial_division")
    report = reevaluation_audit(w.ledger, w.rep, audit_id="a1")
    assert [c["question_id"] for c in report["stagnation_candidates"]] == ["q1"]
    w.reopen("q1")  # the new version snapshots the current grade
    assert reevaluation_audit(w.ledger, w.rep, audit_id="a2")["stagnation_candidates"] == []


def test_sampling_is_bounded_and_reproducible(tmp_path):
    w = World(tmp_path)
    for i in range(5):
        w.answer(f"q{i}", f"is {17 + 2 * i} prime?")
        w.reopen(f"q{i}")
    a = reevaluation_audit(w.ledger, w.rep, audit_id="a", sample_size=3, seed=4)
    b = reevaluation_audit(w.ledger, w.rep, audit_id="b", sample_size=3, seed=4)
    assert a["population"] == 5 and len(a["sampled"]) == 3
    assert a["sampled"] == b["sampled"]


def test_audit_reports_are_kept_once_per_id(tmp_path):
    w = World(tmp_path)
    w.answer("q1", "is 17 prime?")
    reevaluation_audit(w.ledger, w.rep, audit_id="a1", store=w.audits)
    reevaluation_audit(w.ledger, w.rep, audit_id="a1", store=w.audits)
    reevaluation_audit(w.ledger, w.rep, audit_id="a2", store=w.audits)
    assert [r["audit_id"] for r in w.audits.history("reevaluation")] == ["a1", "a2"]


# --- 9.5 ---------------------------------------------------------------------------

def _promote(w, key, confidences, sources_cycle=("src:a", "src:b")):
    for i, conf in enumerate(confidences):
        record_survival(w.cons, key, {"statement": f"statement of {key}", "confidence": conf,
                                      "supporting_provenance": [sources_cycle[i % len(sources_cycle)]]})
    return compact(w.cons, key)


def test_faithful_compaction_passes(tmp_path):
    w = World(tmp_path)
    _promote(w, "k", [0.9] * 5)
    report = consolidation_audit(w.cons, audit_id="c1")
    assert report["population"] == 1 and report["failed"] == []


def test_edited_compact_node_is_caught(tmp_path):
    w = World(tmp_path)
    node = _promote(w, "k", [0.9] * 5)
    w.cons.upsert("k", {**node, "statement": "a quietly stronger statement", "confidence": 0.99})
    [finding] = consolidation_audit(w.cons, audit_id="c1")["failed"]
    kinds = {p.split(":")[0] for p in finding["problems"]}
    assert kinds == {"statement_mismatch", "confidence_mismatch"}


def test_corrupted_archive_is_reported_not_trusted(tmp_path):
    w = World(tmp_path)
    node = _promote(w, "k", [0.9] * 5)
    w.archive.corrupt_for_testing(node["archive_ref"], b"tampered")
    [finding] = consolidation_audit(w.cons, audit_id="c1")["failed"]
    assert finding["problems"][0].startswith("archive_corrupt")


@pytest.mark.parametrize("confidences,sources,why", [
    ([0.9] * 3, ("src:a", "src:b"), "survival cycles"),        # compacted too early
    ([0.9, 0.9, 0.8, 0.8, 0.7], ("src:a", "src:b"), "declining"),  # eroding confidence
    ([0.9] * 5, ("src:a",), "independent sources"),             # one source
])
def test_promotion_that_skipped_its_criteria_is_caught(tmp_path, confidences, sources, why):
    w = World(tmp_path)
    _promote(w, "k", confidences, sources_cycle=sources)  # compact() itself doesn't gate
    [finding] = consolidation_audit(w.cons, audit_id="c1")["failed"]
    assert finding["problems"][0].startswith("promoted_without_meeting_criteria")
    assert why in finding["problems"][0]


def test_circular_sources_fail_the_audit_when_citations_are_known(tmp_path):
    w = World(tmp_path)
    _promote(w, "k", [0.9] * 5)
    assert consolidation_audit(w.cons, audit_id="c1")["failed"] == []
    report = consolidation_audit(w.cons, audit_id="c2", cites={"src:a": ["src:b"], "src:b": ["src:a"]})
    assert "circular" in report["failed"][0]["problems"][0]


def test_only_tier_c_nodes_are_audited(tmp_path):
    w = World(tmp_path)
    record_survival(w.cons, "tier-b", {"statement": "s", "confidence": 0.9, "supporting_provenance": ["x"]})
    assert consolidation_audit(w.cons, audit_id="c1")["population"] == 0
