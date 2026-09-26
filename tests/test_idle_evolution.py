"""Section 3.6 idle-evolution rounds: re-challenging committed claims
against current agents and grades, and the periodic reviews that run in
the same pass -- all on the real scheduler, real stores."""
import pytest
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.scheduler.runner import SingleUnitRunner
from athenaeum_body.ledger import QuestionLedger
from athenaeum_body.schemas import QuestionLedgerEntry
from athenaeum_body.reputability_store import ReputabilityStore
from athenaeum_body.consolidation_store import ConsolidationStore
from athenaeum_body.domain_fidelity_store import DomainFidelityStore
from athenaeum_body.human_checkpoint_store import HumanCheckpointStore
from athenaeum_brain import model_backed_reasoning
from athenaeum_brain.claims import Claim
from athenaeum_brain.loop import make_deliberation_unit
from athenaeum_brain.human_input import clear_checkpoint
from athenaeum_brain.idle_evolution import (
    IdleContext, make_idle_evolution_unit, sample_claims, commit, amendment_checkpoint_key,
    apply_amendment_if_approved, feed_reevaluation,
)


@pytest.fixture(autouse=True)
def _no_model_fallback(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)


class World:
    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.cas = ContentAddressedStore(tmp_path / "cas")
        self._n = 0
        self.ctx = IdleContext(
            ledger=QuestionLedger(self.log("ledger")),
            reputability=ReputabilityStore(self.log("rep")),
            consolidation=ConsolidationStore(self.log("cons"), ContentAddressedStore(tmp_path / "archive")),
            fidelity=DomainFidelityStore(self.log("fid")),
            checkpoints=HumanCheckpointStore(self.log("cp")),
        )

    def log(self, name):
        return CheckpointLog(cas=self.cas, index_path=self.tmp / f"{name}.txt")

    def fresh_log(self, name=None):
        self._n += 1
        return self.log(name or f"unit-{self._n}")

    def answer(self, qid, question, importance=0.0):
        self.ctx.ledger.submit(QuestionLedgerEntry(id=qid, importance=importance))
        log = self.fresh_log()
        runner = SingleUnitRunner(log, shared_state={})
        unit = make_deliberation_unit(question, qid, reputability=self.ctx.reputability)
        while unit.status != "completed":
            runner.run_round(unit)
        self.ctx.ledger.append_version(qid, log.read_latest()["shared_state"]["answer"])

    def legacy(self, qid, question, *claims, importance=0.0):
        """A ledger answer committed before today's agents existed -- the
        realistic way a claim that current agents would challenge ends up
        in the Belief Graph."""
        self.ctx.ledger.submit(QuestionLedgerEntry(id=qid, importance=importance))
        committed = [Claim(question_id=qid, round=1, issuing_agent="Physics", statement=s,
                           claim_type="empirical", confidence=0.8, defeat_condition="x",
                           jurisdiction_check=True, supporting_provenance=list(p),
                           status="committed").to_dict() for s, p in claims]
        self.ctx.ledger.append_version(qid, {
            "question": question, "frame": {"routed_agents": ["Physics"], "output_types": ["research"]},
            "committed": committed, "dissent": [], "plural_answers": [], "source_grades_at_use": {},
        })

    def cycle(self, cycle_id="idle-1", **kw):
        log = self.fresh_log(f"idle-{cycle_id}")
        runner = SingleUnitRunner(log, shared_state={})
        unit = make_idle_evolution_unit(self.ctx, cycle_id, **kw)
        while unit.status != "completed":
            runner.run_round(unit)
        return log.read_latest()["shared_state"]

    def grade(self, src, outcome, n):
        for _ in range(n):
            self.ctx.reputability.record_outcome(src, "source", outcome)


# --- sampling ---------------------------------------------------------------

def test_sampling_takes_important_questions_first_and_is_reproducible(tmp_path):
    w = World(tmp_path)
    w.answer("low", "is 17 prime?", importance=0.1)
    w.answer("high", "is 19 prime?", importance=0.9)
    w.answer("mid", "is 23 prime?", importance=0.5)
    sample = sample_claims(w.ctx.ledger, sample_size=2, seed=7)
    assert [s["question_id"] for s in sample] == ["high", "mid"]
    assert sample == sample_claims(w.ctx.ledger, sample_size=2, seed=7)


# --- statuses ---------------------------------------------------------------

def test_unchanged_claims_survive_and_count_toward_consolidation(tmp_path):
    w = World(tmp_path)
    w.answer("q1", "is 17 prime?")
    result = w.cycle()["idle_result"]
    assert result["status_counts"]["survived"] == 1
    assert w.ctx.consolidation.get("Mathematics::17 is prime")["cycles"] == 1
    assert result["reevaluation_candidates"] == {}


def test_contested_source_weakens_and_records_the_lower_weight(tmp_path):
    w = World(tmp_path)
    w.answer("q1", "is 17 prime?")
    w.grade("computed:trial_division", "challenged", 3)  # 1 corroborated vs 3 challenged -> contested
    result = w.cycle()["idle_result"]
    assert result["status_counts"]["weakened"] == 1
    entry = w.ctx.consolidation.get("Mathematics::17 is prime")
    assert entry["confidence_history"] == [0.4]  # 1.0 x contested weight, not the raw 1.0


def test_source_with_no_support_left_is_unsupported(tmp_path):
    w = World(tmp_path)
    w.legacy("q1", "does it fall?", ("an old physics claim", ["blog:x"]))
    w.grade("blog:x", "challenged", 3)  # 0 corroborations, 3 challenges -> rejected
    result = w.cycle()["idle_result"]
    assert result["status_counts"]["unsupported"] == 1
    assert "is now unsupported" in result["reevaluation_candidates"]["q1"][0]
    assert w.ctx.consolidation.get("Physics::an old physics claim") is None  # not a survival


def test_newly_challenged_claim_goes_to_a_logged_dispute(tmp_path):
    w = World(tmp_path)
    w.legacy("q1", "should we ban it?", ("the data shows we should ban it", ["study:1"]))
    result = w.cycle()["idle_result"]
    assert result["status_counts"]["challenged"] == 1
    key = "Physics::the data shows we should ban it"
    assert key in result["dispute_rulings"]
    [logged] = w.ctx.reputability.disputes_for(key)
    assert logged["dispute_id"] == f"idle-1:{key}"
    assert "is now challenged" in result["reevaluation_candidates"]["q1"][0]


def test_idle_cycle_records_no_reputability_outcomes(tmp_path):
    """Surviving re-examination is not new evidence about a source; counting
    it would let a claim promote its own sources every cycle."""
    w = World(tmp_path)
    w.answer("q1", "is 17 prime?")
    before = w.ctx.reputability._state()["tallies"]
    for i in range(3):
        w.cycle(f"idle-{i}")
    assert w.ctx.reputability._state()["tallies"] == before


# --- idempotency / kill-resume -------------------------------------------------

def test_commit_is_idempotent_under_its_cycle_id(tmp_path):
    w = World(tmp_path)
    w.legacy("q1", "should we ban it?", ("the data shows we should ban it", ["study:1"]))
    w.answer("q2", "is 17 prime?")
    state = w.cycle("idle-1")
    commit(w.ctx, "idle-1", state["findings"], state["plan"])  # a resumed round 3 re-running
    assert w.ctx.consolidation.get("Mathematics::17 is prime")["cycles"] == 1
    assert len(w.ctx.reputability.disputes_for("Physics::the data shows we should ban it")) == 1
    assert len(w.ctx.fidelity.history_for("Mathematics")) == 1


def test_cycle_survives_a_kill_between_rounds(tmp_path):
    w = World(tmp_path)
    w.answer("q1", "is 17 prime?")
    log = w.fresh_log("idle-kill")
    runner = SingleUnitRunner(log, shared_state={})
    unit = make_idle_evolution_unit(w.ctx, "idle-k")
    runner.run_round(unit)
    runner.run_round(unit)  # sampled + re-examined, then "killed"

    log2 = CheckpointLog(cas=w.cas, index_path=tmp_path / "idle-kill.txt")
    runner2 = SingleUnitRunner(log2, shared_state=log2.read_latest()["shared_state"])
    fresh = make_idle_evolution_unit(w.ctx, "idle-k")
    fresh.round_index = runner2.resume_round_index("idle-k")
    assert fresh.round_index == 2
    while fresh.status != "completed":
        runner2.run_round(fresh)
    assert log2.read_latest()["shared_state"]["idle_result"]["status_counts"]["survived"] == 1


# --- Domain Fidelity ----------------------------------------------------------

def test_fidelity_is_scored_per_agent_and_tagged_with_the_cycle(tmp_path):
    w = World(tmp_path)
    w.answer("q1", "is 17 prime?")
    w.cycle("idle-1")
    [record] = w.ctx.fidelity.history_for("Mathematics")
    assert record["cycle_id"] == "idle-1" and record["domain_fidelity_score"] == 1.0


# --- 6.5 standard review ------------------------------------------------------

def _two_challenged_claims_on_foundational_sources(w):
    for src in ("journal:a", "journal:b"):
        w.grade(src, "corroborated", 5)
    w.legacy("q1", "should we ban it?",
             ("the data shows we should ban it", ["journal:a"]),
             ("the trial shows we must stop it", ["journal:b"]))


def test_amendment_is_proposed_to_the_human_checkpoint_not_adopted(tmp_path):
    w = World(tmp_path)
    _two_challenged_claims_on_foundational_sources(w)
    proposal = w.cycle("idle-1")["idle_result"]["amendment_proposal"]
    assert proposal["params"]["foundational_min_corroborations"] == 6
    cp = w.ctx.checkpoints.get(amendment_checkpoint_key("idle-1"))
    assert cp["status"] == "pending_human_checkpoint" and cp["submitter_id"] == "idle-evolution"
    assert w.ctx.reputability.current_standard()["version"] == 0  # nothing adopted yet
    assert apply_amendment_if_approved(w.ctx, "idle-1", proposal)["adopted"] is False


def test_approved_amendment_is_adopted_once(tmp_path):
    w = World(tmp_path)
    _two_challenged_claims_on_foundational_sources(w)
    proposal = w.cycle("idle-1")["idle_result"]["amendment_proposal"]
    clear_checkpoint(w.ctx.checkpoints, amendment_checkpoint_key("idle-1"),
                     reviewer_id="rev-1", reviewer_role="reviewer", decision="approve")

    result = apply_amendment_if_approved(w.ctx, "idle-1", proposal)
    assert result["adopted"] and result["version"] == 1
    # both sources had exactly 5 corroborations: foundational under v0, not under v1
    assert {r["subject_id"] for r in result["regraded"]} == {"journal:a", "journal:b"}
    assert apply_amendment_if_approved(w.ctx, "idle-1", proposal) == {"adopted": False,
                                                                      "reason": "already adopted"}


def test_one_challenged_claim_is_not_enough_evidence_to_amend(tmp_path):
    w = World(tmp_path)
    w.grade("journal:a", "corroborated", 5)
    w.legacy("q1", "should we ban it?", ("the data shows we should ban it", ["journal:a"]))
    assert w.cycle()["idle_result"]["amendment_proposal"] is None


# --- feeding re-evaluation ------------------------------------------------------

def test_findings_reopen_an_important_question(tmp_path):
    w = World(tmp_path)
    w.legacy("q1", "should we ban it?", ("the data shows we should ban it", ["study:1"]), importance=0.9)
    w.legacy("q2", "should we allow it?", ("the data shows we should allow it", ["study:2"]), importance=0.0)
    result = w.cycle()["idle_result"]
    outcomes = feed_reevaluation(w.ctx, result, unit_log_for=lambda qid: w.fresh_log())
    assert outcomes["q1"]["reopened"] is True
    assert any("is now challenged" in c for c in outcomes["q1"]["answer"]["diff"]["cause"])
    assert outcomes["q2"]["reopened"] is False  # same finding, below the importance gate
