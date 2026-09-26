"""Section 10.3/10.5 inside idle evolution: claims are compacted by the idle
process the moment they qualify, and de-compacted before a challenge is
reasoned about -- plus the Tier C survival crash it exposed (known-bugs #29)."""
import pytest
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.scheduler.runner import SingleUnitRunner
from athenaeum_body.ledger import QuestionLedger
from athenaeum_body.schemas import QuestionLedgerEntry
from athenaeum_body.reputability_store import ReputabilityStore
from athenaeum_body.consolidation_store import ConsolidationStore
from athenaeum_brain import model_backed_reasoning
from athenaeum_brain.claims import Claim
from athenaeum_brain.consolidation import record_survival, compact, decompact
from athenaeum_brain.idle_evolution import IdleContext, make_idle_evolution_unit
from athenaeum_brain.audits import consolidation_audit

KEY = "Physics::an object falling from 19.6m takes approximately 2.00s to hit the ground (v0=0, g=9.8 m/s^2)"


@pytest.fixture(autouse=True)
def _no_model_fallback(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)


class World:
    def __init__(self, tmp):
        self.tmp, self.cas, self.n = tmp, ContentAddressedStore(tmp / "cas"), 0
        self.archive = ContentAddressedStore(tmp / "archive")
        self.cons = ConsolidationStore(self.log("cons"), self.archive)
        self.rep = ReputabilityStore(self.log("rep"))
        self.ledger = QuestionLedger(self.log("ledger"))
        self.ctx = IdleContext(ledger=self.ledger, reputability=self.rep, consolidation=self.cons,
                               consolidation_min_cycles=3, consolidation_min_sources=1)

    def log(self, name):
        return CheckpointLog(cas=self.cas, index_path=self.tmp / f"{name}.txt")

    def add_answer(self, statement, source, claim_type="empirical"):
        self.ledger.submit(QuestionLedgerEntry(id="q1"))
        claim = Claim(question_id="q1", round=1, issuing_agent="Physics", statement=statement,
                      claim_type=claim_type, confidence=0.95, defeat_condition="a timed drop disagreeing",
                      jurisdiction_check=True, supporting_provenance=[source], status="committed")
        self.ledger.append_version("q1", {"question": "q", "frame": {}, "committed": [claim.to_dict()],
                                          "dissent": [], "plural_answers": []})

    def cycle(self):
        self.n += 1
        log = self.log(f"idle-{self.n}")
        runner = SingleUnitRunner(log, shared_state={})
        unit = make_idle_evolution_unit(self.ctx, f"idle-{self.n}")
        while unit.status != "completed":
            runner.run_round(unit)
        return log.read_latest()["shared_state"]["idle_result"]


def _plain_store(tmp):
    return ConsolidationStore(CheckpointLog(cas=ContentAddressedStore(tmp / "c"), index_path=tmp / "i.txt"),
                              ContentAddressedStore(tmp / "a"))


# --- known-bugs #29 -----------------------------------------------------------------

def test_surviving_after_compaction_no_longer_crashes_and_keeps_the_node_honest(tmp_path):
    store = _plain_store(tmp_path)
    claim = {"statement": "s", "confidence": 0.9, "supporting_provenance": ["x", "y"]}
    for i in range(5):
        record_survival(store, "k", claim, cycle_id=f"c{i}")
    compact(store, "k")
    node = record_survival(store, "k", {**claim, "confidence": 0.95}, cycle_id="after")
    assert node["tier"] == "C" and node["cycles"] == 5 and node["cycles_since_compaction"] == 1
    assert node["confidence"] == 0.9 and node["current_confidence"] == 0.95  # compacted value kept
    assert record_survival(store, "k", claim, cycle_id="after")["cycles_since_compaction"] == 1  # idempotent
    assert consolidation_audit(store, audit_id="a", min_sources=2)["failed"] == []  # still matches its archive


def test_compacting_twice_is_a_no_op(tmp_path):
    store = _plain_store(tmp_path)
    for i in range(5):
        record_survival(store, "k", {"statement": "s", "confidence": 0.9, "supporting_provenance": ["x"]})
    first = compact(store, "k")
    assert compact(store, "k") == first


# --- 10.3 automatic compaction ---------------------------------------------------------

def test_idle_evolution_compacts_a_claim_once_it_qualifies(tmp_path):
    w = World(tmp_path)
    w.add_answer("an object falling from 19.6m takes approximately 2.00s to hit the ground (v0=0, g=9.8 m/s^2)",
                 "computed:kinematics_free_fall")
    results = [w.cycle() for _ in range(4)]
    assert [r["compacted"] for r in results] == [[], [], [KEY], []]  # at exactly min_cycles, once
    node = w.cons.get(KEY)
    assert node["tier"] == "C" and node["cycles"] == 3 and node["cycles_since_compaction"] == 1
    assert consolidation_audit(w.cons, audit_id="a", min_cycles=3, min_sources=1)["failed"] == []


# --- 10.5 de-compaction ----------------------------------------------------------------

def test_a_compacted_claim_that_loses_its_support_is_decompacted_first(tmp_path):
    w = World(tmp_path)
    w.add_answer("an object falling from 19.6m takes approximately 2.00s to hit the ground (v0=0, g=9.8 m/s^2)",
                 "blog:shaky")
    for _ in range(3):
        w.cycle()
    ref = w.cons.get(KEY)["archive_ref"]
    for _ in range(3):
        w.rep.record_outcome("blog:shaky", "source", "challenged")  # 0 corroborations -> rejected
    result = w.cycle()
    assert result["decompacted"] == [KEY]
    entry = w.cons.get(KEY)
    assert entry["tier"] == "B" and entry["decompacted_from"] == ref
    assert "now unsupported" in entry["decompaction_reason"]
    assert entry["confidence_history"]                      # the full trace is active again
    assert w.cons.read_full_trace(ref)["cycles"] == 3        # and the archive is untouched (10.4)


def test_a_compacted_claim_under_challenge_is_decompacted_before_its_dispute(tmp_path):
    w = World(tmp_path)
    w.add_answer("the data shows we should ban it", "study:1")
    key = "Physics::the data shows we should ban it"
    # force it into Tier C as if it had qualified earlier, then let a cycle challenge it
    for i in range(3):
        record_survival(w.cons, key, {"statement": "the data shows we should ban it", "confidence": 0.95,
                                      "supporting_provenance": ["study:1"]}, cycle_id=f"old-{i}")
    compact(w.cons, key)
    result = w.cycle()
    assert result["decompacted"] == [key] and key in result["dispute_rulings"]
    assert w.cons.get(key)["tier"] == "B"


def test_decompacting_a_non_compacted_entry_is_a_no_op(tmp_path):
    store = _plain_store(tmp_path)
    record_survival(store, "k", {"statement": "s", "confidence": 0.9, "supporting_provenance": ["x"]})
    before = store.get("k")
    assert decompact(store, "k", reason="x") == before
