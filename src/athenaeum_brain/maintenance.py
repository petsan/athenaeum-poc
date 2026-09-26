"""
The maintenance cadence: the piece that makes the system evolve on its own
instead of waiting for someone to call each periodic function by hand.

A `Maintainer` owns one `MultiUnitScheduler` and feeds it two kinds of
work unit:
- questions (priority 0), each a full deliberation with every store wired
  in (reputability, model fitness, domain fidelity, Belief Graph); and
- idle-evolution cycles (priority -1), so real questions are always served
  first (brain-design.md 3.6: "between and alongside active questions").

Cadence (all configurable, all placeholders):
- an idle cycle is queued after every `idle_every_questions` answered
  questions, and once whenever the queue runs dry -- but only once per dry
  spell, so an idle system doesn't spin re-examining unchanged claims;
- after each idle cycle: implicated questions are handed to re-evaluation
  (7.2/7.3, importance-gated), any amendment a Reviewer has approved is
  adopted (6.5), and every `audit_every_cycles` cycles both audits run
  (9.4, 9.5) into the AuditStore.

After a unit's result is harvested, its namespace is removed from the
scheduler's shared state, so checkpoints stay bounded instead of carrying
every past unit forever (the ledger, stores and graph hold the results).

Known limitation, inherited from MultiUnitScheduler: its queue is in
memory. A killed Maintainer's completed work is all durable (ledger,
stores, checkpoints), but units that were queued or mid-way must be
resubmitted after a restart; a deliberation resubmitted with the same id
resumes from its last completed round via the runner's checkpoint.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable
from athenaeum_body.ledger import QuestionLedger
from athenaeum_body.schemas import QuestionLedgerEntry
from athenaeum_body.scheduler.multi_unit import MultiUnitScheduler
from athenaeum_body.scheduler.runner import SingleUnitRunner
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.model_fitness_store import ModelFitnessStore
from athenaeum_body.belief_graph_store import BeliefGraphStore
from athenaeum_body.audit_store import AuditStore
from .loop import make_deliberation_unit
from .idle_evolution import (
    IdleContext, make_idle_evolution_unit, apply_amendment_if_approved, feed_reevaluation,
)
from .reopening import rate_and_store_importance
from .audits import reevaluation_audit, consolidation_audit


@dataclass
class MaintenancePolicy:
    idle_every_questions: int = 3
    audit_every_cycles: int = 5
    idle_sample_size: int = 20
    importance_threshold: float = 0.3


@dataclass
class Maintainer:
    idle: IdleContext                       # ledger, reputability, consolidation, fidelity, checkpoints
    log_for: Callable[[str], CheckpointLog]  # fresh checkpoint log by name (scheduler, reopens)
    model_fitness: ModelFitnessStore | None = None
    belief_graph: BeliefGraphStore | None = None
    audits: AuditStore | None = None
    verification: dict | None = None
    policy: MaintenancePolicy = field(default_factory=MaintenancePolicy)

    def __post_init__(self):
        self.scheduler = MultiUnitScheduler(SingleUnitRunner(self.log_for("maintainer"), shared_state={}))
        self._kinds: dict[str, str] = {}
        self.answered_since_idle = 0
        self.cycles = 0
        self.idle_since_last_question = False
        self.pending_amendments: dict[str, dict] = {}
        self.events: list[dict] = []        # what happened, in order -- for callers and tests

    @property
    def ledger(self) -> QuestionLedger:
        return self.idle.ledger

    # --- submitting work ------------------------------------------------------

    def submit_question(self, question_id: str, question: str) -> None:
        self.ledger.submit(QuestionLedgerEntry(id=question_id, status="queued"))
        unit = make_deliberation_unit(question, question_id, priority=0, reputability=self.idle.reputability,
                                      verification=self.verification, model_fitness=self.model_fitness,
                                      fidelity=self.idle.fidelity, belief_graph=self.belief_graph)
        self._kinds[unit.id] = "question"
        self.idle_since_last_question = False
        self.scheduler.submit(unit)

    def _submit_idle(self) -> None:
        self.cycles += 1
        cycle_id = f"idle-{self.cycles}"
        unit = make_idle_evolution_unit(self.idle, cycle_id, sample_size=self.policy.idle_sample_size,
                                        seed=self.cycles)
        self._kinds[unit.id] = "idle"
        self.answered_since_idle = 0
        self.idle_since_last_question = True
        self.scheduler.submit(unit)

    def _idle_in_flight(self) -> bool:
        return any(self._kinds.get(u.id) == "idle" for _, _, u in self.scheduler._heap)

    # --- running -----------------------------------------------------------------

    def tick(self) -> dict | None:
        """One scheduler round, plus whatever follows from it. Returns the
        event it produced, or None when there was nothing left to do."""
        if not self.scheduler._heap:
            # One idle cycle per dry spell -- and a cadence cycle that already
            # ran since the last question counts as that one.
            if self.idle_since_last_question or not self.ledger._state()["questions"]:
                return None
            self._submit_idle()
        unit = self.scheduler.process_one_round()
        if unit.status != "completed":
            return None
        kind = self._kinds.pop(unit.id)
        event = self._on_question_done(unit.id) if kind == "question" else self._on_idle_done(unit.id)
        self.events.append(event)
        return event

    def run(self, max_rounds: int = 10_000) -> list[dict]:
        """Tick until there's nothing left to do (or max_rounds)."""
        start = len(self.events)
        for _ in range(max_rounds):
            if self.tick() is None and not self.scheduler._heap:
                break
        return self.events[start:]

    # --- harvesting -----------------------------------------------------------------

    def _harvest(self, namespace: str, key: str):
        state = self.scheduler.runner.shared_state
        value = state[namespace][key]
        state.pop(namespace, None)  # bounded checkpoints: the result now lives in the ledger/stores
        return value

    def _on_question_done(self, question_id: str) -> dict:
        answer = self._harvest(f"deliberation:{question_id}", "answer")
        self.ledger.append_version(question_id, answer)
        rating = rate_and_store_importance(self.ledger, question_id, graph=self.belief_graph)
        self.answered_since_idle += 1
        if self.answered_since_idle >= self.policy.idle_every_questions and not self._idle_in_flight():
            self._submit_idle()
        return {"kind": "question", "question_id": question_id, "importance": rating["importance"]}

    def _on_idle_done(self, cycle_id: str) -> dict:
        result = self._harvest(f"idle:{cycle_id}", "idle_result")
        reopened = feed_reevaluation(self.idle, result, unit_log_for=lambda qid: self.log_for(f"reopen-{qid}-{cycle_id}"),
                                     importance_threshold=self.policy.importance_threshold,
                                     belief_graph=self.belief_graph)
        if result["amendment_proposal"] is not None:
            self.pending_amendments[cycle_id] = result["amendment_proposal"]
        adopted = []
        for pending_cycle, proposal in list(self.pending_amendments.items()):
            outcome = apply_amendment_if_approved(self.idle, pending_cycle, proposal)
            if outcome["adopted"] or outcome.get("reason") == "already adopted":
                adopted.append(pending_cycle)
                del self.pending_amendments[pending_cycle]
        audited = False
        if self.audits is not None and self.cycles % self.policy.audit_every_cycles == 0:
            reevaluation_audit(self.ledger, self.idle.reputability, audit_id=f"reeval-{cycle_id}",
                               seed=self.cycles, store=self.audits)
            if self.idle.consolidation is not None:
                consolidation_audit(self.idle.consolidation, audit_id=f"cons-{cycle_id}", seed=self.cycles,
                                    cites=self.idle.cites, store=self.audits)
            audited = True
        return {"kind": "idle", "cycle_id": cycle_id, "status_counts": result["status_counts"],
                "reopened": sorted(q for q, r in reopened.items() if r["reopened"]),
                "amendments_adopted": adopted, "audited": audited}
