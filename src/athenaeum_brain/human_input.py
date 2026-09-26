"""
Human Input Pipeline and Governance (Section 11): human contributions
enter as an ordinary claim, never a command (11.1), are examined never
auto-accepted (11.2), tracked like any other source (11.3, reusing
ReputabilityStore's already-generic subject_type -- Section 6.2 says this
extension is literal, not a new mechanism), can be fully rejected with a
written, logged rationale (11.4), and their highest-consequence effects
land at a human checkpoint rather than taking effect silently (11.5),
cleared only under role separation (11.7).
"""
from __future__ import annotations
from athenaeum_body.reputability_store import ReputabilityStore
from athenaeum_body.human_checkpoint_store import HumanCheckpointStore
from .claims import Claim
from .reevaluation import IMPORTANCE_THRESHOLD

ROLES = ("owner", "reviewer", "member", "service")
_LOW_WEIGHT_CONFIDENCE_CAP = 0.3


class HumanInputError(ValueError):
    """Raised for malformed submissions or governance violations -- e.g. a
    missing required field (11.1), an unauthorized checkpoint action, or an
    unrecognized role."""


class CheckpointConflictError(HumanInputError):
    """Section 11.7's conflict-of-interest rule: the person whose input
    triggered a pending_human_checkpoint state must not, by default, also
    be the one who clears it."""


def submit_human_input(*, question_id: str, round_no: int, submitter_id: str, submitter_role: str,
                        statement: str, justification: str, declared_scope: str,
                        requested_confidence: float = 0.6) -> dict:
    """Section 11.1: a human contribution, normalized to the same claim
    structure as everything else (claim_type='human_input'), plus the
    required metadata the design calls out by name. Returns a submission
    record (claim + metadata) rather than a bare Claim, since submitter_id/
    role/justification/declared_scope aren't part of the normalized claim
    structure itself (Section 3.5) -- they're the submission envelope
    around it, used by this module and by checkpoint governance, not by
    cross-examination.

    Section 11.1: justification is required, not optional -- but an
    unjustified (empty-string) submission is still accepted, capped at low
    confidence as testimony, never rejected outright and never treated as
    unexamined fact (11.1's own stated resolution of that tension)."""
    if submitter_role not in ROLES:
        raise HumanInputError(f"unknown role {submitter_role!r}; expected one of {ROLES}")
    if justification is None:
        raise HumanInputError("justification is required (Section 11.1)")
    if not declared_scope:
        raise HumanInputError("declared_scope is required (Section 11.1)")

    confidence = requested_confidence if justification.strip() else min(requested_confidence, _LOW_WEIGHT_CONFIDENCE_CAP)
    claim = Claim(
        question_id=question_id, round=round_no, issuing_agent=f"human:{submitter_id}",
        statement=statement, claim_type="human_input", confidence=confidence,
        defeat_condition="cross-examination overturns the stated justification, or the justification is shown unfounded",
        jurisdiction_check=True, subject=declared_scope,
        supporting_provenance=[f"human_submitter:{submitter_id}"],
    )
    return {
        "claim": claim, "submitter_id": submitter_id, "submitter_role": submitter_role,
        "justification": justification, "declared_scope": declared_scope,
    }


def record_submitter_outcome(reputability: ReputabilityStore, submission: dict, survived: bool) -> None:
    """Section 11.3: humans are graded like sources, transparently -- reuses
    ReputabilityStore.record_outcome's existing subject_type parameter
    rather than a parallel mechanism, exactly as the design describes this
    as an extension, not a new system."""
    reputability.record_outcome(
        submission["submitter_id"], "human_submitter",
        "corroborated" if survived else "challenged",
    )


def human_input_is_material(answer: dict, submission: dict, survived_cross_examination: bool) -> dict:
    """Section 11.5: a sufficiently weighted human input targeting a claim
    an existing answer relies on is, by definition, material -- extends
    reevaluation.is_material's shape ({'material': bool, 'reasons': [...]})
    for this distinct trigger (a new human_input claim, not a source-grade
    delta)."""
    if not survived_cross_examination:
        return {"material": False, "reasons": ["human input did not survive cross-examination"]}
    scope = submission["declared_scope"]
    committed_subjects = {c.get("subject") for c in answer.get("committed", [])}
    cited_sources = {src for c in answer.get("committed", []) for src in c.get("supporting_provenance", [])}
    if scope in committed_subjects or scope in cited_sources:
        return {"material": True, "reasons": [f"human input targets '{scope}', which this answer relies on"]}
    return {"material": False, "reasons": [f"human input targets '{scope}', not referenced by this answer"]}


def trigger_checkpoint_if_needed(checkpoints: HumanCheckpointStore, question_id: str,
                                  submission: dict, materiality: dict, *, importance: float | None = None,
                                  threshold: float = IMPORTANCE_THRESHOLD,
                                  changes_leading_conclusion: bool = False,
                                  overturns_tier_c: bool = False) -> dict | None:
    """Section 11.5: any re-deliberation triggered by human input that
    would change a leading conclusion, overturn a Tier C item, or touch an
    importance-thresholded question produces pending_human_checkpoint
    rather than going straight to current.

    Owner decision 5 (2026-09-26) puts the importance clause into effect.
    Material human input on a question rated below `threshold` (the same
    threshold re-evaluation uses) does NOT wait at a checkpoint; it stays
    an ordinary claim, cross-examined like any other. The other two
    clauses are not importance-gated in the design, so input that would
    change a leading conclusion or overturn a Tier C item always
    checkpoints. With no importance given, this stays conservative and
    checkpoints, as it always did."""
    if not materiality["material"]:
        return None
    reasons = list(materiality["reasons"])
    if changes_leading_conclusion:
        reasons.append("would change the leading conclusion")
    if overturns_tier_c:
        reasons.append("would overturn a Tier C (consolidated) claim")
    must = changes_leading_conclusion or overturns_tier_c
    if not must and importance is not None:
        if importance < threshold:
            return None
        reasons.append(f"question importance {importance} is at or above the {threshold} threshold")
    return checkpoints.set_pending(
        question_id, reason="; ".join(reasons),
        triggering_claim_id=submission["claim"].claim_id, submitter_id=submission["submitter_id"],
    )


def clear_checkpoint(checkpoints: HumanCheckpointStore, question_id: str, *, reviewer_id: str,
                      reviewer_role: str, decision: str, note: str = None) -> dict:
    """Section 11.5/11.7: approve / reject-with-note / request-more-
    deliberation, gated to the Reviewer role, with the conflict-of-interest
    check (the submitter who triggered this checkpoint may not clear it
    themselves) enforced here rather than left to caller discipline."""
    if reviewer_role != "reviewer":
        raise HumanInputError(f"role {reviewer_role!r} is not authorized to clear a checkpoint (Section 11.7)")
    cp = checkpoints.get(question_id)
    if cp is None:
        raise HumanInputError(f"no pending checkpoint for {question_id!r}")
    if reviewer_id == cp.get("submitter_id"):
        raise CheckpointConflictError(
            "the reviewer clearing a checkpoint must not be the submitter whose input triggered it (Section 11.7)")

    if decision == "approve":
        return checkpoints.approve(question_id, reviewer_id)
    if decision == "reject_with_note":
        if not note:
            raise HumanInputError("reject_with_note requires a note (Section 11.4: a rejection is not a silent drop)")
        return checkpoints.reject_with_note(question_id, reviewer_id, note)
    if decision == "request_more_deliberation":
        return checkpoints.request_more_deliberation(question_id, reviewer_id)
    raise HumanInputError(f"unknown decision {decision!r}")
