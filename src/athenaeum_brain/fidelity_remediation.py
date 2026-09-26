"""
Domain Fidelity remediation (brain-design.md Section 2.4.3): a drop in an
agent's Domain Fidelity Score never changes its behaviour silently. It
starts a staged, recorded remediation path instead:

  flagged review -> the agent's recent claims are re-examined for STYLE
                    (fingerprint deviation), not correctness. Not confirmed
                    -> cleared.
  re-grounding   -> confirmed: for REGROUNDING_CYCLES of the agent's own
                    fidelity readings, its model-backed fallback is
                    suppressed, so it can only assert what its grounded,
                    deterministic computation produces -- the POC's
                    mechanical form of "increase weight toward the agent's
                    foundational corpus" (model completions being the
                    newer, less-disciplined material 2.4.3 has in mind).
  escalated      -> still drifting when re-grounding ends: the human
                    checkpoint (11.5) takes over; the system does not keep
                    adjudicating its own agent indefinitely. Suppression
                    stays on until a Reviewer approves the checkpoint.

A reading is one recorded fidelity score for that agent (normally one
idle-evolution cycle that sampled it), so "time" here is measured in
evidence about the agent, not wall-clock. Every transition is appended to
the record's history with its reason; a repeated call for the same cycle
id is a no-op, matching idle_evolution's kill/resume discipline.
"""
from __future__ import annotations
from athenaeum_body.domain_fidelity_store import DomainFidelityStore
from athenaeum_body.human_checkpoint_store import HumanCheckpointStore
from .domain_fidelity import fingerprint_deviation, needs_review

STYLE_CONFIRM_THRESHOLD = 0.25   # placeholder, like every other threshold in this repo
REGROUNDING_CYCLES = 3
SUBMITTER = "domain-fidelity"
SUPPRESSING_STAGES = ("regrounding", "escalated")


def checkpoint_key(agent_name: str) -> str:
    return f"domain-fidelity:{agent_name}"


def regrounding_agents(store: DomainFidelityStore) -> list[str]:
    """Agents whose model fallback must currently be suppressed."""
    return store.agents_in_stage(*SUPPRESSING_STAGES)


def remediate(store: DomainFidelityStore, agent_name: str, *, recent_claims: list[dict], cycle_id: str,
              checkpoints: HumanCheckpointStore | None = None) -> dict:
    """Advances one agent's remediation by at most one step, given the
    agent's claims just re-examined this cycle. Call AFTER this cycle's
    fidelity score has been recorded. Returns the (possibly unchanged)
    record."""
    record = store.remediation(agent_name) or {"stage": "none", "history": []}
    if record["history"] and record["history"][-1]["cycle_id"] == cycle_id:
        return record  # already advanced for this cycle
    readings = len(store.history_for(agent_name))
    deviation = fingerprint_deviation(agent_name, recent_claims)
    stage, new_stage, reason = record["stage"], None, None

    if stage in ("none", "cleared"):
        flag = needs_review(store, agent_name)
        if flag["needs_review"]:
            if deviation >= STYLE_CONFIRM_THRESHOLD:
                new_stage = "regrounding"
                record["until_reading"] = readings + REGROUNDING_CYCLES
                reason = (f"{flag['reason']}; confirmed on style re-examination (fingerprint deviation "
                          f"{deviation:.2f}); model fallback suppressed for {REGROUNDING_CYCLES} readings")
            else:
                new_stage = "cleared"
                reason = (f"{flag['reason']}; not confirmed on style re-examination "
                          f"(fingerprint deviation {deviation:.2f})")
    elif stage == "regrounding" and readings >= record["until_reading"]:
        if deviation >= STYLE_CONFIRM_THRESHOLD:
            new_stage = "escalated"
            reason = f"still drifting after re-grounding (fingerprint deviation {deviation:.2f})"
            # Always (re-)arm: an earlier escalation's approved checkpoint
            # must not clear this new one. The cycle-id guard above already
            # stops a resumed cycle from arming it twice.
            if checkpoints is not None:
                checkpoints.set_pending(checkpoint_key(agent_name), reason=f"{agent_name}: {reason}",
                                        triggering_claim_id=cycle_id, submitter_id=SUBMITTER)
        else:
            new_stage = "cleared"
            reason = f"style recovered after re-grounding (fingerprint deviation {deviation:.2f})"
    elif stage == "escalated" and checkpoints is not None:
        cp = checkpoints.get(checkpoint_key(agent_name))
        if cp is not None and cp["status"] == "current":
            new_stage = "cleared"
            reason = f"human checkpoint approved by {cp['reviewer_id']}"

    if new_stage is None:
        return record
    record["stage"] = new_stage
    record["history"].append({"stage": new_stage, "cycle_id": cycle_id, "reading": readings, "reason": reason})
    store.set_remediation(agent_name, record)
    return record
