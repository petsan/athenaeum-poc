"""
The maintenance cadence: the piece that makes the system evolve on its own
instead of waiting for someone to call each periodic function by hand.

A `Maintainer` owns one `MultiUnitScheduler` and feeds it two kinds of
work unit:
- questions (priority 0), each a full deliberation with every store wired
  in (reputability, model fitness, domain fidelity, Belief Graph); and
- idle-evolution cycles (priority -1), so real questions are always served
  first (brain-design.md 3.6: "between and alongside active questions");
- and, when submitted, ingestion batches (priority -1, batch 5 Phase Y):
  one source per round into the CAS and the Belief Graph (Section 9).

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

Restarts (batch 3, Phase Q): MultiUnitScheduler's queue is in memory, so
the Maintainer keeps its own registry of in-flight units, cadence counters
and pending amendments inside the scheduler's checkpointed state, saved
the moment they change. A new Maintainer over the same checkpoint log
resubmits every registered unit at its last completed round and harvests
any that finished but weren't recorded. Question answers are recorded
at-least-once and idempotently (never lost, never duplicated); an idle
cycle's follow-ups are at-most-once (see _complete).

Failing rounds (batch 5, Phase W): a round that raises is retried from the
unit's last completed round a bounded number of times, then the unit is
given up. A given-up question is marked `suspended`, and its error is kept
under `failed`, never silently dropped (see _on_round_failed).
"""
from __future__ import annotations
import time
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
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.ingestion import make_ingestion_unit
from .loop import make_deliberation_unit
from .idle_evolution import (
    IdleContext, make_idle_evolution_unit, apply_amendment_if_approved, feed_reevaluation,
)
from .reopening import rate_and_store_importance
from .audits import reevaluation_audit, consolidation_audit
from .evaluation import calibration_drift


@dataclass
class MaintenancePolicy:
    idle_every_questions: int = 3
    audit_every_cycles: int = 5
    idle_sample_size: int = 20
    importance_threshold: float = 0.3
    max_round_failures: int = 3   # attempts at a failing round before its unit is given up
    event_history: int = 200      # recent events kept in memory (Maintainer.events)


@dataclass
class Maintainer:
    idle: IdleContext                       # ledger, reputability, consolidation, fidelity, checkpoints
    log_for: Callable[[str], CheckpointLog]  # fresh checkpoint log by name (scheduler, reopens)
    model_fitness: ModelFitnessStore | None = None
    belief_graph: BeliefGraphStore | None = None
    audits: AuditStore | None = None
    verification: dict | None = None
    policy: MaintenancePolicy = field(default_factory=MaintenancePolicy)
    ingestion_cas: ContentAddressedStore | None = None  # where ingested source content goes (Section 9)
    fetch: Callable | None = None                      # ingestion's fetch seam; None means a real fetch_url

    def __post_init__(self):
        log = self.log_for("maintainer")
        latest = log.read_latest()
        shared = latest["shared_state"] if latest and "shared_state" in latest else {}
        self.scheduler = MultiUnitScheduler(SingleUnitRunner(log, shared_state=shared))
        # Everything the Maintainer must remember across a restart lives in the
        # scheduler's own checkpointed state, and is written the moment it
        # changes (_save), not just at the next round boundary.
        self._m = shared.setdefault("maintenance", {
            "units": {}, "cycles": 0, "answered_since_idle": 0,
            "idle_since_last_question": False, "pending_amendments": {},
        })
        self.events: list[dict] = []        # what happened recently, in order (bounded: emit)
        self.recovered: list[str] = []
        # progress, in memory only (batch 8, Phase AG): read by the API's health
        # check without its lock, so plain attributes rebound, never mutated
        self.rounds_run = 0
        self.last_round_at: float | None = None
        if self.idle.belief_graph is None:
            self.idle.belief_graph = self.belief_graph  # idle cycles read ingested citations from it
        self._recover()

    # counters and registry, persisted in the checkpoint
    cycles = property(lambda self: self._m["cycles"])
    answered_since_idle = property(lambda self: self._m["answered_since_idle"])
    idle_since_last_question = property(lambda self: self._m["idle_since_last_question"])
    pending_amendments = property(lambda self: self._m["pending_amendments"])

    @property
    def ledger(self) -> QuestionLedger:
        return self.idle.ledger

    def _save(self, forget: tuple[str, ...] = ()) -> None:
        """`forget`: units that just left the registry. The runner keeps a
        per-unit record (round reached, status) for resuming. Once a unit is
        harvested or given up nothing reads it again, and keeping it would
        grow every checkpoint forever (batch 6, Phase AB)."""
        log = self.scheduler.runner.log
        state = log.read_latest() or {"units": {}}
        for unit_id in forget:
            state.get("units", {}).pop(unit_id, None)
        state["shared_state"] = self.scheduler.runner.shared_state
        log.write_checkpoint(state, label="maintenance")

    # --- submitting work ------------------------------------------------------

    def _question_unit(self, question_id: str, question: str):
        return make_deliberation_unit(question, question_id, priority=0, reputability=self.idle.reputability,
                                      verification=self.verification, model_fitness=self.model_fitness,
                                      fidelity=self.idle.fidelity, belief_graph=self.belief_graph, mirror=False)

    def _idle_unit(self, cycle_id: str, info: dict):
        return make_idle_evolution_unit(self.idle, cycle_id, sample_size=info["sample_size"], seed=info["seed"],
                                        mirror=False)

    def _ingestion_unit(self, batch_id: str, info: dict):
        return make_ingestion_unit(batch_id, info["sources"], self.ingestion_cas, self.belief_graph,
                                   fetch=self.fetch)

    def _unit_for(self, unit_id: str, info: dict):
        """A fresh unit for a registered one (after a restart or a failed round)."""
        if info["kind"] == "question":
            return self._question_unit(unit_id, info["question"])
        if info["kind"] == "ingestion":
            return self._ingestion_unit(unit_id, info)
        return self._idle_unit(unit_id, info)

    def submit_ingestion(self, batch_id: str, sources: list[dict]) -> None:
        """Section 9: ingest a batch of sources (ingestion.source_from_spec
        specs) as a low-priority unit, one source per round, recorded in the
        CAS and the Belief Graph. Questions are served first."""
        if self.ingestion_cas is None:
            raise ValueError("this Maintainer has no ingestion_cas to store source content in")
        if batch_id in self._m["units"]:
            raise ValueError(f"unit {batch_id!r} is already registered")
        info = {"kind": "ingestion", "sources": [dict(s) for s in sources]}
        self._m["units"][batch_id] = info
        self._save()
        self.scheduler.submit(self._ingestion_unit(batch_id, info))

    def submit_question(self, question_id: str, question: str) -> None:
        self.ledger.submit(QuestionLedgerEntry(id=question_id, status="queued"))
        self._m["units"][question_id] = {"kind": "question", "question": question}
        self._m["idle_since_last_question"] = False
        self._save()
        self.scheduler.submit(self._question_unit(question_id, question))

    def _submit_idle(self) -> None:
        self._m["cycles"] += 1
        cycle_id = f"idle-{self._m['cycles']}"
        info = {"kind": "idle", "seed": self._m["cycles"], "sample_size": self.policy.idle_sample_size}
        self._m["units"][cycle_id] = info
        self._m["answered_since_idle"] = 0
        self._m["idle_since_last_question"] = True
        self._save()
        self.scheduler.submit(self._idle_unit(cycle_id, info))

    def _idle_in_flight(self) -> bool:
        return any(self._m["units"].get(u.id, {}).get("kind") == "idle" for _, _, u in self.scheduler._heap)

    # --- recovery -----------------------------------------------------------------

    def _recover(self) -> None:
        """Resubmit every registered unit a previous Maintainer left behind:
        mid-way units resume from their last completed round (the runner's
        own checkpoint says which); units that completed but were never
        harvested are harvested now."""
        runner_units = (self.scheduler.runner.log.read_latest() or {}).get("units", {})
        for unit_id, info in list(self._m["units"].items()):
            done = runner_units.get(unit_id, {}).get("status") == "completed"
            if done:
                event = self._complete(unit_id)
            else:
                unit = self._unit_for(unit_id, info)
                unit.round_index = self.scheduler.runner.resume_round_index(unit_id)
                self.scheduler.submit(unit)
                event = None
            self.recovered.append(unit_id)
            if event:
                self.emit(event)

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
        upcoming = self.scheduler._heap[0][2]
        if self._m["units"].get(upcoming.id, {}).get("kind") == "question" and upcoming.round_index == 0:
            self.ledger.set_status(upcoming.id, "active")  # queued -> active as its first round starts
        try:
            unit = self.scheduler.process_one_round()
        except Exception as e:  # the scheduler has already dropped the unit from its queue
            self._round_done()
            event = self._on_round_failed(upcoming, e)
            self.emit(event)
            return event
        self._round_done()
        if unit.status != "completed":
            return None
        event = self._complete(unit.id)
        if event:
            self.emit(event)
        return event

    def _round_done(self) -> None:
        """A round ran (to completion or to an exception): work is moving."""
        self.rounds_run += 1
        self.last_round_at = time.time()

    def emit(self, event: dict) -> None:
        """`events` is a window of the most recent `policy.event_history`,
        not a full history: the Maintainer lives as long as its process, and
        the durable record is in the stores (batch 7, Phase AD)."""
        self.events.append(event)
        overflow = len(self.events) - self.policy.event_history
        if overflow > 0:
            del self.events[:overflow]

    def _complete(self, unit_id: str) -> dict | None:
        """Questions are at-least-once and idempotent: the answer is recorded
        before the unit leaves the registry, and a replay (after a crash)
        skips a question the ledger already has as completed. Idle cycles'
        follow-ups (reopens, amendments, audits) are at-most-once: the unit
        leaves the registry first, because a replayed reopen would append a
        duplicate version, while a lost one is found again by the next cycle.
        An ingestion batch has no follow-ups; its records were written by its
        own rounds."""
        info = self._m["units"][unit_id]
        if info["kind"] == "question":
            event = self._on_question_done(unit_id)
            del self._m["units"][unit_id]
            self._save(forget=(unit_id,))
            return event
        del self._m["units"][unit_id]
        self._save(forget=(unit_id,))
        if info["kind"] == "ingestion":
            result = self._harvest(f"ingestion:{unit_id}", "ingestion_result")
            return {"kind": "ingestion", **result} if result is not None else None
        return self._on_idle_done(unit_id)

    def _namespaces(self, unit_id: str) -> tuple[str, ...]:
        return f"deliberation:{unit_id}", f"idle:{unit_id}", f"ingestion:{unit_id}"

    def _on_round_failed(self, unit, error: Exception) -> dict:
        """A round raised. Its unit's scratch state goes back to the last
        checkpoint, since a handler may have changed it before raising. The
        unit is then retried from its last completed round, up to
        `max_round_failures` attempts. After that it is given up: dropped
        from the registry and recorded under `failed`, and a question is
        marked `suspended`. The failure count is persisted, so a restart
        doesn't reset it."""
        info = self._m["units"][unit.id]
        info["failures"] = info.get("failures", 0) + 1
        info["last_error"] = f"{type(error).__name__}: {error}"
        state = self.scheduler.runner.shared_state
        saved = (self.scheduler.runner.log.read_latest() or {}).get("shared_state", {})
        for ns in self._namespaces(unit.id):
            if ns in saved:
                state[ns] = saved[ns]
            else:
                state.pop(ns, None)
        event = {"kind": "unit_error", "unit_id": unit.id, "unit_kind": info["kind"],
                 "error": info["last_error"], "failures": info["failures"]}
        if info["failures"] < self.policy.max_round_failures:
            retry = self._unit_for(unit.id, info)
            retry.round_index = self.scheduler.runner.resume_round_index(unit.id)
            self._save()
            self.scheduler.submit(retry)
            return {**event, "retrying": True}
        del self._m["units"][unit.id]
        self._m.setdefault("failed", {})[unit.id] = info
        for ns in self._namespaces(unit.id):
            state.pop(ns, None)
        if info["kind"] == "question":
            self.ledger.set_status(unit.id, "suspended")
        self._save(forget=(unit.id,))
        return {**event, "kind": "unit_failed", "retrying": False}

    def record_failure(self, unit_id: str, info: dict, error: Exception) -> None:
        """Records work that failed outside the scheduler -- the API's
        synchronous path -- the same way a given-up unit is recorded, so
        every failure is reported in one place."""
        self._m.setdefault("failed", {})[unit_id] = {**info, "failures": 1,
                                                     "last_error": f"{type(error).__name__}: {error}"}
        self._save()

    @property
    def failed(self) -> dict:
        """Units given up after repeated round failures: {unit_id: info with last_error}."""
        return self._m.get("failed", {})

    def run(self, max_rounds: int = 10_000) -> list[dict]:
        """Tick until there's nothing left to do (or max_rounds). Returns
        every event this call produced, however many -- collected here,
        not sliced from the bounded `events` window."""
        produced = []
        for _ in range(max_rounds):
            event = self.tick()
            if event is not None:
                produced.append(event)
            elif not self.scheduler._heap:
                break
        return produced

    # --- harvesting -----------------------------------------------------------------

    def _harvest(self, namespace: str, key: str):
        state = self.scheduler.runner.shared_state
        value = state.get(namespace, {}).get(key)
        state.pop(namespace, None)  # bounded checkpoints: the result now lives in the ledger/stores
        return value

    def _on_question_done(self, question_id: str) -> dict:
        answer = self._harvest(f"deliberation:{question_id}", "answer")
        with self.ledger.log.batch():   # the answer and its rating: one ledger checkpoint
            if answer is not None and self.ledger.get(question_id).status != "completed":
                self.ledger.append_version(question_id, answer)
            rating = rate_and_store_importance(self.ledger, question_id, graph=self.belief_graph)
        self._m["answered_since_idle"] += 1
        if self._m["answered_since_idle"] >= self.policy.idle_every_questions and not self._idle_in_flight():
            self._submit_idle()
        return {"kind": "question", "question_id": question_id, "importance": rating["importance"]}

    def _on_idle_done(self, cycle_id: str) -> dict:
        result = self._harvest(f"idle:{cycle_id}", "idle_result")
        if result is None:  # harvested before a crash; its follow-ups are at-most-once
            return None
        reopened = feed_reevaluation(self.idle, result, unit_log_for=lambda qid: self.log_for(f"reopen-{qid}-{cycle_id}"),
                                     importance_threshold=self.policy.importance_threshold,
                                     belief_graph=self.belief_graph)
        pending = self._m["pending_amendments"]
        if result["amendment_proposal"] is not None:
            pending[cycle_id] = result["amendment_proposal"]
        adopted = []
        for pending_cycle, proposal in list(pending.items()):
            outcome = apply_amendment_if_approved(self.idle, pending_cycle, proposal)
            if outcome["adopted"] or outcome.get("reason") == "already adopted":
                adopted.append(pending_cycle)
                del pending[pending_cycle]
        self._save()
        audited = False
        if self.audits is not None and self.cycles % self.policy.audit_every_cycles == 0:
            reevaluation_audit(self.ledger, self.idle.reputability, audit_id=f"reeval-{cycle_id}",
                               seed=self.cycles, store=self.audits)
            if self.idle.consolidation is not None:
                consolidation_audit(self.idle.consolidation, audit_id=f"cons-{cycle_id}", seed=self.cycles,
                                    cites=self.idle.citation_map(), store=self.audits)
            audited = True
        drifting = []
        if self.idle.calibration is not None:
            # 9.3: calibration as a continuous health metric -- per agent, every cycle
            report = {a: calibration_drift(self.idle.calibration, a) for a in self.idle.calibration.agents()}
            drifting = sorted(a for a, r in report.items() if r["drifting"])
            if self.audits is not None:
                self.audits.record("calibration", {"audit_id": f"cal-{cycle_id}", "agents": report,
                                                   "drifting": drifting})
        return {"kind": "idle", "cycle_id": cycle_id, "status_counts": result["status_counts"],
                "reopened": sorted(q for q, r in reopened.items() if r["reopened"]),
                "amendments_adopted": adopted, "audited": audited, "calibration_drifting": drifting}
