"""Section 5.3/9.3: idle evolution feeds per-agent calibration with each
claim's latest fate -- once per claim, never once per re-examination --
and the Maintainer reports drift every cycle."""
import pytest
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.scheduler.runner import SingleUnitRunner
from athenaeum_body.ledger import QuestionLedger
from athenaeum_body.schemas import QuestionLedgerEntry
from athenaeum_body.reputability_store import ReputabilityStore
from athenaeum_body.calibration_store import CalibrationStore
from athenaeum_body.audit_store import AuditStore
from athenaeum_brain import model_backed_reasoning
from athenaeum_brain.claims import Claim
from athenaeum_brain.idle_evolution import IdleContext, make_idle_evolution_unit
from athenaeum_brain.maintenance import Maintainer, MaintenancePolicy


@pytest.fixture(autouse=True)
def _no_model_fallback(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)


class World:
    def __init__(self, tmp):
        self.tmp, self.cas, self.n = tmp, ContentAddressedStore(tmp / "cas"), 0
        self.cal = CalibrationStore(self.log("cal"))
        self.rep = ReputabilityStore(self.log("rep"))
        self.ledger = QuestionLedger(self.log("ledger"))
        self.ctx = IdleContext(ledger=self.ledger, reputability=self.rep, calibration=self.cal)

    def log(self, name):
        return CheckpointLog(cas=self.cas, index_path=self.tmp / f"{name}.txt")

    def legacy(self, qid, claims):
        self.ledger.submit(QuestionLedgerEntry(id=qid))
        committed = [Claim(question_id=qid, round=1, issuing_agent="Physics", statement=s, claim_type="empirical",
                           confidence=0.95, defeat_condition="a measurement", jurisdiction_check=True,
                           supporting_provenance=[src], status="committed").to_dict() for s, src in claims]
        self.ledger.append_version(qid, {"question": "q", "frame": {}, "committed": committed,
                                         "dissent": [], "plural_answers": []})

    def cycle(self):
        self.n += 1
        log = self.log(f"idle-{self.n}")
        runner = SingleUnitRunner(log, shared_state={})
        unit = make_idle_evolution_unit(self.ctx, f"idle-{self.n}", sample_size=50)
        while unit.status != "completed":
            runner.run_round(unit)
        return log.read_latest()["shared_state"]["idle_result"]


# --- the store ------------------------------------------------------------------------

def test_a_claim_counts_once_with_its_latest_fate(tmp_path):
    cal = CalibrationStore(CheckpointLog(cas=ContentAddressedStore(tmp_path / "c"), index_path=tmp_path / "i"))
    cal.set_outcome("k", "Physics", 0.95, verified=True)
    cal.set_outcome("k", "Physics", 0.95, verified=True)
    assert cal.record_for_agent("Physics") == {"0.9-1.0": {"verified": 1, "overturned": 0}}
    cal.set_outcome("k", "Physics", 0.95, verified=False)  # its fate changed
    assert cal.record_for_agent("Physics") == {"0.9-1.0": {"verified": 0, "overturned": 1}}


def test_explicit_records_and_claim_outcomes_are_merged(tmp_path):
    cal = CalibrationStore(CheckpointLog(cas=ContentAddressedStore(tmp_path / "c"), index_path=tmp_path / "i"))
    cal.record("Physics", 0.95, verified=True)
    cal.set_outcome("k", "Physics", 0.97, verified=False)
    assert cal.record_for_agent("Physics") == {"0.9-1.0": {"verified": 1, "overturned": 1}}
    assert cal.agents() == ["Physics"]


# --- fed by idle evolution ------------------------------------------------------------

def test_repeated_survival_is_one_data_point_not_many(tmp_path):
    w = World(tmp_path)
    w.legacy("q1", [("an object falling from 19.6m takes approximately 2.00s to hit the ground "
                     "(v0=0, g=9.8 m/s^2)", "computed:kinematics_free_fall")])
    for _ in range(3):
        w.cycle()
    assert w.cal.record_for_agent("Physics") == {"0.9-1.0": {"verified": 1, "overturned": 0}}


def test_a_claim_that_loses_its_support_becomes_overturned(tmp_path):
    w = World(tmp_path)
    w.legacy("q1", [("a claim resting on one blog", "blog:1")])
    w.cycle()
    for _ in range(3):
        w.rep.record_outcome("blog:1", "source", "challenged")  # rejected
    w.cycle()
    assert w.cal.record_for_agent("Physics") == {"0.9-1.0": {"verified": 0, "overturned": 1}}


def test_the_maintainer_reports_a_drifting_agent(tmp_path):
    """Five 0.95-confidence claims that all fail re-examination: the agent
    says 'almost certainly' and is right none of the time."""
    w = World(tmp_path)
    w.legacy("q1", [(f"the data shows we should do thing {i}", f"study:{i}") for i in range(5)])
    audits = AuditStore(w.log("audits"))
    m = Maintainer(idle=w.ctx, log_for=w.log, audits=audits, policy=MaintenancePolicy(audit_every_cycles=1))
    [event] = m.run()
    assert event["calibration_drifting"] == ["Physics"]
    [report] = audits.history("calibration")
    assert report["drifting"] == ["Physics"]
    assert report["agents"]["Physics"]["overconfident_buckets"][0]["observed"] == 0.0
