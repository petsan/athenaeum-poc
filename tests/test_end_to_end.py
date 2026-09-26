"""End-to-end: one realistic lifecycle through every Brain mechanism at
once, on real stores and the real scheduler -- deliberation with every
option on, a kill/resume, importance, idle evolution into consolidation,
a grade-driven reopen that must expand a compacted claim, a forecast
resolution, both audits, the integrity gates and the adversarial suite.

Per-phase tests prove each piece; this proves they compose. The model
fallback is stubbed (deterministic text) so the scenario never depends on
the model-lab guests' health; everything else is real."""
import subprocess
import sys
import pytest
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.scheduler.runner import SingleUnitRunner
from athenaeum_body.sandbox import SandboxResult
from athenaeum_body.ledger import QuestionLedger
from athenaeum_body.schemas import QuestionLedgerEntry
from athenaeum_body.reputability_store import ReputabilityStore
from athenaeum_body.consolidation_store import ConsolidationStore
from athenaeum_body.domain_fidelity_store import DomainFidelityStore
from athenaeum_body.human_checkpoint_store import HumanCheckpointStore
from athenaeum_body.model_fitness_store import ModelFitnessStore
from athenaeum_body.audit_store import AuditStore
from athenaeum_brain import model_backed_reasoning
from athenaeum_brain.loop import make_deliberation_unit
from athenaeum_brain.model_fitness import admit_model
from athenaeum_brain.reopening import rate_and_store_importance, reopen_if_material
from athenaeum_brain.idle_evolution import IdleContext, make_idle_evolution_unit
from athenaeum_brain.consolidation import should_promote_to_c, compact
from athenaeum_brain.audits import reevaluation_audit, consolidation_audit
from athenaeum_brain.evaluation import check_integrity_gates, run_adversarial_suite

QUESTIONS = {
    "prime": "is 17 prime?",
    "round": "should we round 2.5 up or down?",
    "forecast": "will an object dropped from 20m land within 3 seconds?",
    "history": "did world war i cause world war ii?",
    "orbit": "what force holds the moon in orbit?",   # only the model fallback can answer
}
PRIME_KEY = "Mathematics::17 is prime"


def local_runner(code):
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
    return SandboxResult(status="completed", stdout=p.stdout, stderr=p.stderr, returncode=p.returncode)


class System:
    def __init__(self, tmp):
        self.tmp, self.cas, self.n = tmp, ContentAddressedStore(tmp / "cas"), 0
        self.ledger = QuestionLedger(self.log("ledger"))
        self.rep = ReputabilityStore(self.log("rep"))
        self.cons = ConsolidationStore(self.log("cons"), ContentAddressedStore(tmp / "archive"))
        self.fid = DomainFidelityStore(self.log("fid"))
        self.cp = HumanCheckpointStore(self.log("cp"))
        self.fit = ModelFitnessStore(self.log("fit"))
        self.audits = AuditStore(self.log("audits"))
        self.idle = IdleContext(ledger=self.ledger, reputability=self.rep, consolidation=self.cons,
                                fidelity=self.fid, checkpoints=self.cp)

    def log(self, name):
        return CheckpointLog(cas=self.cas, index_path=self.tmp / f"{name}.txt")

    def fresh(self):
        self.n += 1
        return self.log(f"u{self.n}")

    def unit(self, question, qid):
        return make_deliberation_unit(question, qid, reputability=self.rep, model_fitness=self.fit,
                                      fidelity=self.fid,
                                      verification={"enabled": True, "sandbox_run": local_runner})

    def ask(self, qid, question, kill_after=None):
        self.ledger.submit(QuestionLedgerEntry(id=qid))
        name = f"ask-{qid}"
        log, unit = self.log(name), self.unit(question, qid)
        runner = SingleUnitRunner(log, shared_state={})
        while unit.status != "completed":
            if kill_after is not None and unit.round_index == kill_after:
                log = self.log(name)  # a fresh process reading the same checkpoint files
                runner = SingleUnitRunner(log, shared_state=log.read_latest()["shared_state"])
                unit = self.unit(question, qid)
                unit.round_index = runner.resume_round_index(qid)
                kill_after = None
            runner.run_round(unit)
        answer = log.read_latest()["shared_state"]["answer"]
        self.ledger.append_version(qid, answer)
        return answer

    def idle_cycle(self, i):
        log = self.log(f"idle-{i}")
        runner = SingleUnitRunner(log, shared_state={})
        unit = make_idle_evolution_unit(self.idle, f"idle-{i}", sample_size=50, seed=i)
        while unit.status != "completed":
            runner.run_round(unit)
        return log.read_latest()["shared_state"]["idle_result"]


@pytest.fixture
def system(tmp_path, monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: "gravity holds the moon in orbit")
    return System(tmp_path)


def test_full_lifecycle(system):
    s = system
    admit_model(s.fit, "olmo3-7b", rationale="evaluated on the workbench", admitted_by="owner")

    # --- 1. deliberation, every option on, one killed mid-way -----------------------
    answers = {qid: s.ask(qid, q, kill_after=2 if qid == "prime" else None) for qid, q in QUESTIONS.items()}

    prime = answers["prime"]
    assert [c["statement"] for c in prime["committed"]] == ["17 is prime"]
    assert prime["verification"]["routed"] == 1  # sieve-checked by Engineering
    assert answers["round"]["plural_answers"] and \
        answers["round"]["output_answer"]["sections"]["recommendation"]["chosen_option"].startswith("none chosen")
    forecast = answers["forecast"]["output_answer"]["sections"]["forecast"]
    assert forecast["available"] and forecast["probability"] == 0.9
    assert [c["statement"] for c in answers["history"]["committed"]] == [
        "'world war i' (1914-07-28) precedes 'world war ii' (1939-09-01), "
        "so a causal/contributing link is chronologically POSSIBLE"]
    orbit = answers["orbit"]
    assert orbit["fitness_at_use"] == {"Physics::olmo3-7b": 0.5} and orbit["unadmitted_models"] == []

    # --- 2. importance ---------------------------------------------------------------
    importance = {qid: rate_and_store_importance(s.ledger, qid)["importance"] for qid in QUESTIONS}
    assert importance["round"] > importance["prime"]  # three domains + two output types vs one domain

    # --- 3. idle evolution into consolidation ---------------------------------------
    results = [s.idle_cycle(i) for i in range(5)]
    assert all(r["status_counts"]["challenged"] == 0 for r in results)
    assert all(r["amendment_proposal"] is None for r in results)
    entry = s.cons.get(PRIME_KEY)
    assert entry["cycles"] == 5
    # idle evolution compacts on its own (10.3) what meets the default bar of two
    # independent sources: the World News claim cites two dated events
    history_key = f"WorldNews::{answers['history']['committed'][0]['statement']}"
    assert [k for r in results for k in r["compacted"]] == [history_key]
    # the one-source primality claim needs a lower bar, applied here by hand
    assert should_promote_to_c(entry, min_cycles=5, min_sources=1)["eligible"]
    compact(s.cons, PRIME_KEY)

    # --- 4. a source is contested: a grade-driven reopen with a diff ----------------
    for _ in range(3):
        s.rep.record_outcome("computed:trial_division", "source", "challenged")
    reopened = reopen_if_material(s.ledger, "prime", reputability=s.rep, unit_log=s.fresh(),
                                  importance_threshold=0.1, consolidation=s.cons)
    assert reopened["reopened"] is True
    new = reopened["answer"]
    assert [t["claim"] for t in new["reopen_context"]["expanded_traces"]] == [PRIME_KEY]  # 10.5
    [change] = new["diff"]["weight_changes"]
    assert change["direction"] == "decreased"
    assert s.ledger.get("prime").versions[0] == prime  # history intact

    # --- 5. the forecast resolves: reopened regardless of importance -----------------
    resolved = reopen_if_material(s.ledger, "forecast", reputability=s.rep, unit_log=s.fresh(),
                                  importance_threshold=1.0, forecast_outcome=True)
    assert resolved["reopened"] is True
    assert resolved["answer"]["reopen_context"]["forecast_resolution"]["outcome"] is True

    # --- 6. audits, integrity gates, adversarial suite -------------------------------
    re_audit = reevaluation_audit(s.ledger, s.rep, audit_id="e2e-1", store=s.audits)
    by_q = {r["question_id"]: r["classification"] for r in re_audit["sampled"]}
    assert by_q == {"prime": "weights_only", "forecast": "forecast_resolution"}
    assert re_audit["thrash_suspect_rate"] == 0.0
    assert re_audit["stagnation_candidates"] == []

    cons_audit = consolidation_audit(s.cons, audit_id="e2e-2", min_sources=1, store=s.audits)
    assert cons_audit["population"] == 2 and cons_audit["failed"] == []

    for qid in QUESTIONS:
        latest = s.ledger.get(qid).versions[-1]
        assert check_integrity_gates(latest)["passed"], (qid, check_integrity_gates(latest))

    suite = run_adversarial_suite()
    assert suite["passed"] == suite["total"] == 16


# ---------------------------------------------------------------------------
# Batch 2 (J-N): the same system driven the way the async API drives it --
# through the Maintainer, with questions interleaved on one scheduler, the
# Belief Graph, fingerprints and the fixed number parsing all in play.
# ---------------------------------------------------------------------------

def test_full_lifecycle_through_the_maintainer(system):
    from athenaeum_body.belief_graph_store import BeliefGraphStore
    from athenaeum_brain.maintenance import Maintainer, MaintenancePolicy
    from athenaeum_brain.belief_graph import dependents

    s = system
    admit_model(s.fit, "olmo3-7b", rationale="evaluated on the workbench", admitted_by="owner")
    graph = BeliefGraphStore(s.log("graph"))
    m = Maintainer(idle=s.idle, log_for=s.log, model_fitness=s.fit, belief_graph=graph, audits=s.audits,
                   verification={"enabled": True, "sandbox_run": local_runner},
                   policy=MaintenancePolicy(idle_every_questions=10, audit_every_cycles=1))
    batch = {
        "p17": "is 17 prime?",
        "believe": "should we believe 17 is prime?",
        "round": "how should we round 2.5?",
        "even": "is 4 even?",                   # Phase K: no irrelevant primality claim
        "fall": "did the berlin wall fall in 1989?",  # #21: no 1989 m drop
    }
    for qid, q in batch.items():
        m.submit_question(qid, q)
    events = m.run()

    # every question answered -- its OWN question (known-bugs #26) -- then one idle cycle
    assert [e["kind"] for e in events] == ["question"] * 5 + ["idle"]
    latest = {qid: s.ledger.get(qid).versions[-1] for qid in batch}
    assert all(latest[qid]["question"] == q for qid, q in batch.items())
    assert [c["statement"] for c in latest["p17"]["committed"]] == ["17 is prime"]
    assert not any("prime" in c["statement"] for c in latest["even"]["committed"])
    assert not any("1989m" in c["statement"] for c in latest["fall"]["committed"])
    assert "Physics" not in latest["fall"]["frame"]["routed_agents"]  # #28: no physical context

    # Belief Graph: the shared claim links the two primality questions (Phase L)
    assert dependents(graph, "p17") == ["believe"]

    # a later claim about the same subject reopens the rounding question (7.2 trigger 2)
    s.ledger.update_importance("round", 0.9)
    m.submit_question("round-b", "should we round 2.50 up or down?")
    m.run()
    result = reopen_if_material(s.ledger, "round", reputability=s.rep, unit_log=s.fresh(), belief_graph=graph)
    assert result["reopened"] and any("newly relevant" in c for c in result["answer"]["diff"]["cause"])

    # every agent the idle cycle scored has a fingerprint (Phase J)
    from athenaeum_brain.domain_fidelity import FINGERPRINT_CHECKS
    from athenaeum_brain.agents import all_agents
    scored = [a.name for a in all_agents() if s.fid.history_for(a.name)]
    assert {"Mathematics", "Philosophy"} <= set(scored)
    assert all(agent in FINGERPRINT_CHECKS for agent in scored)

    # audits ran on their cadence; nothing left over in the scheduler's state
    assert s.audits.history("reevaluation")
    assert not [k for k in m.scheduler.runner.shared_state if k.startswith(("deliberation:", "idle:"))]

    for qid in list(batch) + ["round-b"]:
        assert check_integrity_gates(s.ledger.get(qid).versions[-1])["passed"], qid
    assert run_adversarial_suite()["passed"] == 16
