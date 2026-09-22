import pytest
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.reputability_store import ReputabilityStore
from athenaeum_body.human_checkpoint_store import HumanCheckpointStore
from athenaeum_brain.human_input import (
    submit_human_input, record_submitter_outcome, human_input_is_material,
    trigger_checkpoint_if_needed, clear_checkpoint, HumanInputError, CheckpointConflictError,
)


def make_reputability(tmp_path):
    cas = ContentAddressedStore(tmp_path / "cas")
    log = CheckpointLog(cas=cas, index_path=tmp_path / "reputability_index.txt")
    return ReputabilityStore(log)


def make_checkpoints(tmp_path):
    cas = ContentAddressedStore(tmp_path / "cas2")
    log = CheckpointLog(cas=cas, index_path=tmp_path / "checkpoint_index.txt")
    return HumanCheckpointStore(log)


def base_submission(**overrides):
    kwargs = dict(
        question_id="q1", round_no=1, submitter_id="alice", submitter_role="member",
        statement="the classical figure was actually born in 470 BCE, not 469 BCE",
        justification="cross-referenced two independent primary-source chronologies",
        declared_scope="claim-42",
    )
    kwargs.update(overrides)
    return submit_human_input(**kwargs)


def test_submit_human_input_produces_claim_type_human_input():
    sub = base_submission()
    assert sub["claim"].claim_type == "human_input"
    assert sub["claim"].jurisdiction_check is True
    assert sub["claim"].subject == "claim-42"


def test_submit_human_input_requires_justification():
    with pytest.raises(HumanInputError):
        submit_human_input(question_id="q1", round_no=1, submitter_id="alice", submitter_role="member",
                            statement="x", justification=None, declared_scope="claim-1")


def test_submit_human_input_requires_declared_scope():
    with pytest.raises(HumanInputError):
        submit_human_input(question_id="q1", round_no=1, submitter_id="alice", submitter_role="member",
                            statement="x", justification="because", declared_scope="")


def test_submit_human_input_rejects_unknown_role():
    with pytest.raises(HumanInputError):
        submit_human_input(question_id="q1", round_no=1, submitter_id="alice", submitter_role="admin",
                            statement="x", justification="because", declared_scope="claim-1")


def test_unjustified_input_accepted_but_capped_low_confidence():
    sub = base_submission(justification="   ", requested_confidence=0.9)
    assert sub["claim"].confidence <= 0.3  # low-weight testimony, not full weight, not rejected


def test_justified_input_gets_its_requested_confidence():
    sub = base_submission(requested_confidence=0.8)
    assert sub["claim"].confidence == 0.8


def test_submitter_track_record_reuses_reputability_store(tmp_path):
    reputability = make_reputability(tmp_path)
    sub = base_submission()
    record_submitter_outcome(reputability, sub, survived=True)
    record_submitter_outcome(reputability, sub, survived=False)
    grade = reputability.current_grade("alice")
    assert grade["grade"] in ("provisionally_accepted", "contested", "rejected", "foundational")


def test_human_input_material_when_targets_committed_claim():
    sub = base_submission(declared_scope="17")
    answer = {"committed": [{"subject": "17", "statement": "17 is prime", "supporting_provenance": []}]}
    result = human_input_is_material(answer, sub, survived_cross_examination=True)
    assert result["material"] is True


def test_human_input_not_material_when_scope_not_referenced():
    sub = base_submission(declared_scope="unrelated-claim")
    answer = {"committed": [{"subject": "17", "statement": "17 is prime", "supporting_provenance": []}]}
    result = human_input_is_material(answer, sub, survived_cross_examination=True)
    assert result["material"] is False


def test_human_input_not_material_if_it_did_not_survive():
    sub = base_submission(declared_scope="17")
    answer = {"committed": [{"subject": "17", "statement": "17 is prime", "supporting_provenance": []}]}
    result = human_input_is_material(answer, sub, survived_cross_examination=False)
    assert result["material"] is False


def test_checkpoint_triggered_only_when_material(tmp_path):
    checkpoints = make_checkpoints(tmp_path)
    sub = base_submission(declared_scope="17")
    not_material = {"material": False, "reasons": []}
    assert trigger_checkpoint_if_needed(checkpoints, "q1", sub, not_material) is None
    assert checkpoints.get("q1") is None

    material = {"material": True, "reasons": ["targets 17"]}
    cp = trigger_checkpoint_if_needed(checkpoints, "q1", sub, material)
    assert cp["status"] == "pending_human_checkpoint"
    assert checkpoints.get("q1")["status"] == "pending_human_checkpoint"


def test_clear_checkpoint_requires_reviewer_role(tmp_path):
    checkpoints = make_checkpoints(tmp_path)
    sub = base_submission(declared_scope="17")
    trigger_checkpoint_if_needed(checkpoints, "q1", sub, {"material": True, "reasons": ["x"]})
    with pytest.raises(HumanInputError):
        clear_checkpoint(checkpoints, "q1", reviewer_id="bob", reviewer_role="member", decision="approve")


def test_clear_checkpoint_blocks_submitter_from_clearing_own_checkpoint(tmp_path):
    checkpoints = make_checkpoints(tmp_path)
    sub = base_submission(submitter_id="alice", declared_scope="17")
    trigger_checkpoint_if_needed(checkpoints, "q1", sub, {"material": True, "reasons": ["x"]})
    with pytest.raises(CheckpointConflictError):
        clear_checkpoint(checkpoints, "q1", reviewer_id="alice", reviewer_role="reviewer", decision="approve")


def test_clear_checkpoint_approve_makes_answer_current(tmp_path):
    checkpoints = make_checkpoints(tmp_path)
    sub = base_submission(submitter_id="alice", declared_scope="17")
    trigger_checkpoint_if_needed(checkpoints, "q1", sub, {"material": True, "reasons": ["x"]})
    cp = clear_checkpoint(checkpoints, "q1", reviewer_id="bob", reviewer_role="reviewer", decision="approve")
    assert cp["status"] == "current"


def test_clear_checkpoint_reject_with_note_requires_note(tmp_path):
    checkpoints = make_checkpoints(tmp_path)
    sub = base_submission(submitter_id="alice", declared_scope="17")
    trigger_checkpoint_if_needed(checkpoints, "q1", sub, {"material": True, "reasons": ["x"]})
    with pytest.raises(HumanInputError):
        clear_checkpoint(checkpoints, "q1", reviewer_id="bob", reviewer_role="reviewer",
                          decision="reject_with_note", note="")


def test_clear_checkpoint_reject_with_note_stays_pending_not_silently_dropped(tmp_path):
    checkpoints = make_checkpoints(tmp_path)
    sub = base_submission(submitter_id="alice", declared_scope="17")
    trigger_checkpoint_if_needed(checkpoints, "q1", sub, {"material": True, "reasons": ["x"]})
    cp = clear_checkpoint(checkpoints, "q1", reviewer_id="bob", reviewer_role="reviewer",
                           decision="reject_with_note", note="justification doesn't hold up")
    assert cp["status"] == "pending_human_checkpoint"  # not silently current, not silently gone
    assert cp["note"] == "justification doesn't hold up"


def test_human_input_claim_flows_through_cross_examination_and_synthesis():
    """Section 11.2: a human_input claim goes through the SAME cross-
    examination and synthesis path as any other claim -- no special case."""
    from athenaeum_brain.rounds import cross_examination_round, synthesis_round
    sub = base_submission(declared_scope="17")
    exam = cross_examination_round([sub["claim"]], "q1")
    result = synthesis_round([sub["claim"]], exam)
    assert any(c.claim_id == sub["claim"].claim_id for c in result["committed"])


def test_clear_checkpoint_unknown_decision_raises(tmp_path):
    checkpoints = make_checkpoints(tmp_path)
    sub = base_submission(submitter_id="alice", declared_scope="17")
    trigger_checkpoint_if_needed(checkpoints, "q1", sub, {"material": True, "reasons": ["x"]})
    with pytest.raises(HumanInputError):
        clear_checkpoint(checkpoints, "q1", reviewer_id="bob", reviewer_role="reviewer", decision="veto")
