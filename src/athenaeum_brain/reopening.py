"""
Re-evaluation: importance rating (brain-design.md Section 7.1) and the
reopening procedure (7.3), built on the materiality test (7.2,
reevaluation.py).

- importance_rating: computed from the frame (domains implicated, output
  types), how many other questions depend on the same claims, and any
  explicit requester priority -- an estimate, never purely user-declared.
- reopen_question: re-runs the full deliberation with the prior answer as
  INPUT CONTEXT only (every round re-derives from scratch), expands any of
  the prior answer's claims that were consolidated to Tier C first
  (10.5), appends the result as a new ledger version, and attaches an
  explicit diff against the prior version saying what changed and why.
- reopen_if_material: the policy that decides whether to reopen at all --
  material AND important enough, except that a resolved forecast is
  always material regardless of importance (5.4, 7.2).
"""
from __future__ import annotations
from athenaeum_body.ledger import QuestionLedger
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.scheduler.runner import SingleUnitRunner
from .consolidation import claim_key, expand
from .loop import make_deliberation_unit
from .output_types import FORECAST, RESEARCH, evidence_weight, resolve_forecast
from .reevaluation import is_material, materiality_inputs, forecast_is_material, frame_staleness

# Section 7.1's inputs and how much each counts. Explicitly a placeholder
# policy, like GRADE_WEIGHT: which inputs matter is the design's, the
# weights are not.
IMPORTANCE_WEIGHTS = {"breadth": 0.4, "output_types": 0.1, "dependency": 0.3, "requested": 0.2}


# ---------------------------------------------------------------------------
# 7.1 Importance rating
# ---------------------------------------------------------------------------

def importance_rating(frame: dict, *, dependents: int = 0, requested_priority: float | None = None) -> dict:
    """Returns {'importance': 0..1, 'components': {...}} so the rating is
    explainable, not a bare number. Logic is excluded from breadth: it
    chairs every deliberation it's routed to, so it says nothing about how
    many *domains* a question implicates. Breadth saturates at three
    domains; dependency saturates smoothly (2 dependents -> 0.5)."""
    if requested_priority is not None and not 0.0 <= requested_priority <= 1.0:
        raise ValueError(f"requested_priority must be in [0, 1], got {requested_priority}")
    domains = [a for a in frame.get("routed_agents", []) if a != "Logic"]
    components = {
        "breadth": min(1.0, len(domains) / 3),
        "output_types": 1.0 if len(frame.get("output_types", [])) > 1 else 0.0,
        "dependency": dependents / (dependents + 2),
        "requested": requested_priority or 0.0,
    }
    importance = sum(IMPORTANCE_WEIGHTS[k] * v for k, v in components.items())
    return {"importance": round(importance, 4), "components": components}


def count_dependents(ledger: QuestionLedger, question_id: str) -> int:
    """How many OTHER questions' latest answers commit at least one of the
    same claims (by claim_key) this question's latest answer commits --
    if those claims change, those questions are implicated too. A proxy:
    the POC has no Belief Graph dependency edges yet, so shared committed
    claims are the closest real signal available."""
    state = ledger._state()["questions"]
    mine = state[question_id]["versions"]
    if not mine:
        return 0
    my_keys = {claim_key(c) for c in mine[-1].get("committed", [])}
    count = 0
    for qid, q in state.items():
        if qid == question_id or not q["versions"]:
            continue
        if my_keys & {claim_key(c) for c in q["versions"][-1].get("committed", [])}:
            count += 1
    return count


def rate_and_store_importance(ledger: QuestionLedger, question_id: str, *,
                              requested_priority: float | None = None) -> dict:
    """Computes importance from the question's latest answer's own frame
    and its current dependents, and stores it (7.1: revisable)."""
    entry = ledger.get(question_id)
    latest = entry.versions[-1]
    rating = importance_rating(latest["frame"], dependents=count_dependents(ledger, question_id),
                               requested_priority=requested_priority)
    ledger.update_importance(question_id, rating["importance"])
    return rating


# ---------------------------------------------------------------------------
# 7.3 Reopening
# ---------------------------------------------------------------------------

def _leading(answer: dict) -> dict | None:
    research = answer.get("output_answer", {}).get("sections", {}).get(RESEARCH)
    return research.get("leading_conclusion") if research else None


def answer_diff(prior: dict, new: dict) -> dict:
    """Section 7.3's explicit diff: which committed claims appeared or
    disappeared, whose evidence weight moved and which way, and what
    happened to the leading conclusion."""
    before = {claim_key(c): c for c in prior.get("committed", [])}
    after = {claim_key(c): c for c in new.get("committed", [])}
    weight_changes = []
    for key in before.keys() & after.keys():
        w0, w1 = evidence_weight(before[key]), evidence_weight(after[key])
        if abs(w1 - w0) > 1e-9:
            weight_changes.append({"claim": key, "from": w0, "to": w1,
                                   "direction": "increased" if w1 > w0 else "decreased"})

    lead0, lead1 = _leading(prior), _leading(new)
    if lead0 is None and lead1 is None:
        leading = {"change": "none_before_or_after"}
    elif lead0 is None:
        leading = {"change": "appeared", "to": lead1["statement"]}
    elif lead1 is None:
        leading = {"change": "disappeared", "from": lead0["statement"]}
    elif claim_key(lead0) != claim_key(lead1):
        leading = {"change": "changed", "from": lead0["statement"], "to": lead1["statement"]}
    else:
        w0, w1 = evidence_weight(lead0), evidence_weight(lead1)
        leading = {"change": "unchanged", "statement": lead1["statement"],
                   "confidence": "increased" if w1 > w0 else "decreased" if w1 < w0 else "same"}

    return {
        "added": sorted(after.keys() - before.keys()),
        "removed": sorted(before.keys() - after.keys()),
        "weight_changes": sorted(weight_changes, key=lambda c: c["claim"]),
        "leading_conclusion": leading,
        "plural_answers": {"before": len(prior.get("plural_answers", [])),
                           "after": len(new.get("plural_answers", []))},
    }


def reopen_question(ledger: QuestionLedger, question_id: str, *, reasons: list[str],
                    unit_log: CheckpointLog, reputability=None, consolidation=None,
                    extra_context: dict | None = None) -> dict:
    """Section 7.3. `unit_log` holds the re-run's own round checkpoints
    (kill/resume works exactly as for any deliberation). Returns the new
    answer, already appended to the ledger with its `diff`."""
    entry = ledger.get(question_id)
    if entry is None or not entry.versions:
        raise KeyError(f"no answered question {question_id!r} to reopen")
    prior = entry.versions[-1]
    if "question" not in prior:
        raise ValueError(f"{question_id!r}'s latest answer predates question recording; "
                         "it can't be re-derived without its question text")

    # 10.5: de-compaction is required before reasoning builds on a Tier C claim.
    expanded = []
    if consolidation is not None:
        for c in prior.get("committed", []):
            node = consolidation.get(claim_key(c))
            if node and node.get("tier") == "C":
                expanded.append({"claim": claim_key(c), "full_trace": expand(consolidation, claim_key(c))})

    prior_version = len(entry.versions) - 1
    context = {
        "prior_version": prior_version,
        "reasons": list(reasons),
        # the prior answer, minus ITS own reopen context, so context doesn't nest without bound
        "prior_answer": {k: v for k, v in prior.items() if k != "reopen_context"},
        "expanded_traces": expanded,
        **(extra_context or {}),
    }
    runner = SingleUnitRunner(unit_log, shared_state={})
    unit = make_deliberation_unit(prior["question"], question_id, reputability=reputability,
                                  reopen_context=context, unit_id=f"{question_id}-v{prior_version + 1}")
    while unit.status != "completed":
        runner.run_round(unit)
    new = unit_log.read_latest()["shared_state"]["answer"]
    new["diff"] = {**answer_diff(prior, new), "cause": list(reasons)}
    ledger.append_version(question_id, new)
    return new


def reopen_if_material(ledger: QuestionLedger, question_id: str, *, reputability, unit_log: CheckpointLog,
                       importance_threshold: float = 0.3, grade_threshold: int = 1,
                       forecast_outcome: bool | None = None, consolidation=None,
                       additional_reasons: list[str] = ()) -> dict:
    """Section 7.3's trigger: reopen when materiality (7.2) fires for a
    sufficiently important question. A forecast resolution is the one
    exception to the importance gate -- always material, unconditionally.
    The outcome is passed in explicitly, never looked up (9.9: the system
    must not see a resolution it could have learned early).

    additional_reasons: material findings from outside the grade-based
    rules -- e.g. idle evolution (3.6) finding that a claim this answer
    relied on is now challenged, 7.2's "newly challenged claim" trigger.
    They are subject to the same importance gate."""
    entry = ledger.get(question_id)
    prior = entry.versions[-1]
    current, under_prior = materiality_inputs(prior, reputability)
    materiality = is_material(prior, current, threshold=grade_threshold, prior_standard_grades=under_prior)
    reasons = (list(materiality["reasons"]) + frame_staleness(prior)["reasons"]  # 7.2 trigger 3
               + list(additional_reasons))
    extra = {}

    forecast = prior.get("output_answer", {}).get("sections", {}).get(FORECAST)
    forecast_resolved = False
    if forecast_outcome is not None and forecast and forecast.get("available"):
        resolved = resolve_forecast(forecast, forecast_outcome)
        fm = forecast_is_material(resolved)
        reasons += fm["reasons"]
        forecast_resolved = fm["material"]
        extra["forecast_resolution"] = {"outcome": forecast_outcome,
                                        "probability_given": forecast["probability"]}

    if not reasons:
        return {"reopened": False, "reason": "not material", "importance": entry.importance}
    if not forecast_resolved and entry.importance < importance_threshold:
        return {"reopened": False, "reason": f"material but importance {entry.importance} "
                                             f"is below the {importance_threshold} threshold",
                "materiality_reasons": reasons, "importance": entry.importance}
    answer = reopen_question(ledger, question_id, reasons=reasons, unit_log=unit_log,
                             reputability=reputability, consolidation=consolidation, extra_context=extra)
    return {"reopened": True, "answer": answer, "importance": entry.importance}
