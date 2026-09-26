"""
Adapts the 4 deliberation rounds into a Body-compatible round_handler,
so a deliberation runs on the SAME SingleUnitRunner / checkpointing /
kill-resume machinery already proven in athenaeum_body -- not a separate
toy runner. This is the actual integration point.
"""
from __future__ import annotations
from athenaeum_body.scheduler.work_unit import WorkUnit, RoundResult
from athenaeum_body.reputability_store import ReputabilityStore
from .rounds import framing_round, exploration_round, cross_examination_round, synthesis_round
from .claims import Claim
from .verification_routing import route_for_verification
from .output_types import (
    RESEARCH, FORECAST, RECOMMENDATION, build_research_answer, compose_answer,
    forecast_section_from_claims, recommendation_section_from_claims,
)


def _attach_grades_and_record_outcomes(result: dict, reputability: ReputabilityStore) -> dict:
    """Section 6.3: snapshot each cited source's grade AT TIME OF USE onto
    the answer first -- then record this deliberation's outcome, which can
    only affect the grade for FUTURE deliberations, never rewrite this one's
    snapshot (non-retroactive attachment)."""
    grades_at_use = {}
    for c in result["committed"]:
        for src in c.get("supporting_provenance", []):
            if src not in grades_at_use:
                grades_at_use[src] = reputability.current_grade(src)  # snapshot BEFORE recording below

    for c in result["committed"]:
        for src in c.get("supporting_provenance", []):
            reputability.record_outcome(src, "source", "corroborated")
    for d in result["dissent"]:
        for src in d["claim"].get("supporting_provenance", []):
            reputability.record_outcome(src, "source", "challenged")

    result["source_grades_at_use"] = grades_at_use
    return result


def make_deliberation_handler(question: str, question_id: str, reputability: ReputabilityStore = None,
                              reopen_context: dict = None, verification: dict = None):
    """Returns a round_handler(state, round_index) -> RoundResult usable
    directly as a WorkUnit.round_handler in athenaeum_body's scheduler.

    reopen_context (Section 7.3): the prior answer and why it was reopened.
    It is attached to the new answer as input context only -- every round
    still re-derives from scratch, so the prior answer is never a starting
    point to rubber-stamp.

    verification (task 44): {'enabled': bool, 'sandbox_run': optional
    runner}. Omitted means no routing. Callers derive 'enabled' from
    verification_routing.sandbox_enabled(), i.e. from config."""

    def handler(state: dict, round_index: int) -> RoundResult:
        if round_index == 0:
            frame = framing_round(question, question_id)
            return RoundResult(proposed_writes={"frame": frame}, done=False)

        if round_index == 1:
            frame = state["frame"]
            claims = exploration_round(frame, question_id)
            return RoundResult(
                proposed_writes={"exploration_claims": [c.to_dict() for c in claims]},
                done=False,
            )

        if round_index == 2:
            claims = [Claim(**d) for d in state["exploration_claims"]]
            exam = cross_examination_round(claims, question_id)
            # Task 44: formalizable claims routed to Engineering for an
            # independent executed check -- only when the caller passes an
            # enabled sandbox (config execution_sandbox.enabled), else skipped
            # and reported.
            routing = route_for_verification(
                claims, question_id, enabled=bool(verification and verification.get("enabled")),
                sandbox_run=(verification or {}).get("sandbox_run"))
            exam += routing["responses"]
            return RoundResult(
                proposed_writes={"exam_claims": [c.to_dict() for c in exam],
                                 "verification": {"routed": routing["routed"],
                                                  "skipped_reason": routing["skipped_reason"]}},
                done=False,
            )

        if round_index == 3:
            claims = [Claim(**d) for d in state["exploration_claims"]]
            exam = [Claim(**d) for d in state["exam_claims"]]
            # Grades read here are time-of-use: this deliberation's own
            # outcomes are only recorded afterwards, in
            # _attach_grades_and_record_outcomes.
            grade_lookup = (lambda src: reputability.current_grade(src)["grade"]) if reputability else None
            result = synthesis_round(claims, exam, grade_lookup=grade_lookup)
            answer = {
                # The question and its frame ride on the answer so a later
                # reopen (reopening.py, Section 7.3) and importance rating
                # (7.1) never depend on a caller remembering them.
                "question": question,
                "frame": state["frame"],
                "committed": [c.to_dict() for c in result["committed"]],
                "dissent": result["dissent"],
                "plural_answers": result["plural_answers"],
            }
            if reopen_context is not None:
                answer["reopen_context"] = reopen_context
            if "verification" in state:  # absent in checkpoints from before task 44
                answer["verification"] = state["verification"]
            # Section 5.4: one section per output type the framing round
            # classified this question as. Forecast and Recommendation are
            # built only from committed claims carrying that structure;
            # when none do, the section says so explicitly rather than
            # being silently left out.
            output_types = state["frame"].get("output_types", [RESEARCH])
            sections = {}
            if RESEARCH in output_types:
                sections[RESEARCH] = build_research_answer(
                    answer["committed"], answer["dissent"], answer["plural_answers"])
            if FORECAST in output_types:
                sections[FORECAST] = forecast_section_from_claims(answer["committed"])
            if RECOMMENDATION in output_types:
                sections[RECOMMENDATION] = recommendation_section_from_claims(answer["committed"])
            answer["output_answer"] = compose_answer(output_types, sections)
            if reputability is not None:
                answer = _attach_grades_and_record_outcomes(answer, reputability)
            return RoundResult(proposed_writes={"answer": answer}, done=True)
        raise ValueError(f"no round {round_index} in the deliberation loop")

    return handler


def make_deliberation_unit(question: str, question_id: str, priority: int = 0,
                            reputability: ReputabilityStore = None, reopen_context: dict = None,
                            unit_id: str = None, verification: dict = None) -> WorkUnit:
    """unit_id defaults to question_id; a reopen passes a distinct one so
    the new run's checkpoints never collide with the original's."""
    return WorkUnit(
        id=unit_id or question_id,
        priority=priority,
        round_handler=make_deliberation_handler(question, question_id, reputability, reopen_context,
                                                verification),
    )
