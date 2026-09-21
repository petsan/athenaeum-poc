"""
Adapts the 4 deliberation rounds into a Body-compatible round_handler,
so a deliberation runs on the SAME SingleUnitRunner / checkpointing /
kill-resume machinery already proven in athenaeum_body -- not a separate
toy runner. This is the actual integration point.
"""
from __future__ import annotations
from athenaeum_body.scheduler.work_unit import WorkUnit, RoundResult
from .rounds import framing_round, exploration_round, cross_examination_round, synthesis_round
from .claims import Claim


def make_deliberation_handler(question: str, question_id: str):
    """Returns a round_handler(state, round_index) -> RoundResult usable
    directly as a WorkUnit.round_handler in athenaeum_body's scheduler."""

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
            return RoundResult(
                proposed_writes={"exam_claims": [c.to_dict() for c in exam]},
                done=False,
            )

        if round_index == 3:
            claims = [Claim(**d) for d in state["exploration_claims"]]
            exam = [Claim(**d) for d in state["exam_claims"]]
            result = synthesis_round(claims, exam)
            return RoundResult(
                proposed_writes={
                    "answer": {
                        "committed": [c.to_dict() for c in result["committed"]],
                        "dissent": result["dissent"],
                    }
                },
                done=True,
            )
        raise ValueError(f"no round {round_index} in the deliberation loop")

    return handler


def make_deliberation_unit(question: str, question_id: str, priority: int = 0) -> WorkUnit:
    return WorkUnit(
        id=question_id,
        priority=priority,
        round_handler=make_deliberation_handler(question, question_id),
    )
