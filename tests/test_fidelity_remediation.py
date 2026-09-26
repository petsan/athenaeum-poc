"""Section 2.4.3: a Domain Fidelity drop starts a staged remediation path --
flagged style review, re-grounding (model fallback suppressed), then human
escalation -- never a silent behaviour change."""
import pytest
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.scheduler.runner import SingleUnitRunner
from athenaeum_body.domain_fidelity_store import DomainFidelityStore
from athenaeum_body.human_checkpoint_store import HumanCheckpointStore
from athenaeum_body.ledger import QuestionLedger
from athenaeum_body.schemas import QuestionLedgerEntry
from athenaeum_body.reputability_store import ReputabilityStore
from athenaeum_brain import model_backed_reasoning
from athenaeum_brain.model_backed_reasoning import fallback_suppressed, model_backed_claim
from athenaeum_brain.human_input import clear_checkpoint
from athenaeum_brain.loop import make_deliberation_unit
from athenaeum_brain.idle_evolution import IdleContext, make_idle_evolution_unit
from athenaeum_brain.fidelity_remediation import (
    remediate, regrounding_agents, checkpoint_key, REGROUNDING_CYCLES,
)


@pytest.fixture
def world(tmp_path):
    cas = ContentAddressedStore(tmp_path / "cas")
    log = lambda name: CheckpointLog(cas=cas, index_path=tmp_path / f"{name}.txt")
    return {"fid": DomainFidelityStore(log("fid")), "cp": HumanCheckpointStore(log("cp")),
            "log": log, "tmp": tmp_path}


@pytest.fixture
def stub_model(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: "gravity holds the moon in orbit")


ON_STYLE = [{"issuing_agent": "Mathematics", "supporting_provenance": ["computed:trial_division"]}]
OFF_STYLE = [{"issuing_agent": "Mathematics", "supporting_provenance": ["llm:olmo3-7b"]}]


def _reading(store, score, agent="Mathematics"):
    store.record(agent, {"domain_fidelity_score": score})


def _flag(store, agent="Mathematics"):
    """Three baseline readings at 1.0, then a drop -- enough for needs_review."""
    for _ in range(3):
        _reading(store, 1.0, agent)
    _reading(store, 0.5, agent)


# --- the state machine ------------------------------------------------------------

def test_no_flag_no_remediation(world):
    for _ in range(4):
        _reading(world["fid"], 1.0)
    assert remediate(world["fid"], "Mathematics", recent_claims=OFF_STYLE, cycle_id="c1")["stage"] == "none"
    assert world["fid"].remediation("Mathematics") is None


def test_flag_not_confirmed_on_style_is_cleared(world):
    _flag(world["fid"])
    record = remediate(world["fid"], "Mathematics", recent_claims=ON_STYLE, cycle_id="c1")
    assert record["stage"] == "cleared" and "not confirmed" in record["history"][-1]["reason"]
    assert regrounding_agents(world["fid"]) == []


def test_confirmed_drift_starts_regrounding(world):
    _flag(world["fid"])
    record = remediate(world["fid"], "Mathematics", recent_claims=OFF_STYLE, cycle_id="c1")
    assert record["stage"] == "regrounding"
    assert record["until_reading"] == 4 + REGROUNDING_CYCLES
    assert regrounding_agents(world["fid"]) == ["Mathematics"]


def test_regrounding_waits_its_full_period(world):
    _flag(world["fid"])
    remediate(world["fid"], "Mathematics", recent_claims=OFF_STYLE, cycle_id="c1")
    _reading(world["fid"], 0.5)
    assert remediate(world["fid"], "Mathematics", recent_claims=OFF_STYLE, cycle_id="c2")["stage"] == "regrounding"


def _through_regrounding(world, claims_after):
    _flag(world["fid"])
    remediate(world["fid"], "Mathematics", recent_claims=OFF_STYLE, cycle_id="c1", checkpoints=world["cp"])
    for i in range(REGROUNDING_CYCLES):
        _reading(world["fid"], 1.0)
    return remediate(world["fid"], "Mathematics", recent_claims=claims_after, cycle_id="c-end",
                     checkpoints=world["cp"])


def test_recovered_style_after_regrounding_is_cleared(world):
    assert _through_regrounding(world, ON_STYLE)["stage"] == "cleared"
    assert regrounding_agents(world["fid"]) == []
    assert world["cp"].get(checkpoint_key("Mathematics")) is None


def test_persistent_drift_escalates_to_the_human_checkpoint(world):
    record = _through_regrounding(world, OFF_STYLE)
    assert record["stage"] == "escalated"
    cp = world["cp"].get(checkpoint_key("Mathematics"))
    assert cp["status"] == "pending_human_checkpoint" and cp["submitter_id"] == "domain-fidelity"
    assert regrounding_agents(world["fid"]) == ["Mathematics"]  # still suppressed while escalated


def test_escalation_clears_only_after_a_reviewer_approves(world):
    _through_regrounding(world, OFF_STYLE)
    _reading(world["fid"], 1.0)
    assert remediate(world["fid"], "Mathematics", recent_claims=ON_STYLE, cycle_id="c-x",
                     checkpoints=world["cp"])["stage"] == "escalated"
    clear_checkpoint(world["cp"], checkpoint_key("Mathematics"), reviewer_id="rev",
                     reviewer_role="reviewer", decision="approve")
    record = remediate(world["fid"], "Mathematics", recent_claims=ON_STYLE, cycle_id="c-y",
                       checkpoints=world["cp"])
    assert record["stage"] == "cleared" and "approved by rev" in record["history"][-1]["reason"]


def test_a_second_escalation_is_not_cleared_by_the_first_approval(world):
    _through_regrounding(world, OFF_STYLE)
    clear_checkpoint(world["cp"], checkpoint_key("Mathematics"), reviewer_id="rev",
                     reviewer_role="reviewer", decision="approve")
    remediate(world["fid"], "Mathematics", recent_claims=ON_STYLE, cycle_id="c-clear", checkpoints=world["cp"])
    # drift again, all the way through a second re-grounding
    _reading(world["fid"], 0.5)
    remediate(world["fid"], "Mathematics", recent_claims=OFF_STYLE, cycle_id="c-2", checkpoints=world["cp"])
    for _ in range(REGROUNDING_CYCLES):
        _reading(world["fid"], 0.5)
    assert remediate(world["fid"], "Mathematics", recent_claims=OFF_STYLE, cycle_id="c-3",
                     checkpoints=world["cp"])["stage"] == "escalated"
    assert world["cp"].get(checkpoint_key("Mathematics"))["status"] == "pending_human_checkpoint"


def test_repeating_a_cycle_is_a_no_op(world):
    _flag(world["fid"])
    first = remediate(world["fid"], "Mathematics", recent_claims=OFF_STYLE, cycle_id="c1")
    again = remediate(world["fid"], "Mathematics", recent_claims=ON_STYLE, cycle_id="c1")
    assert again == first and len(again["history"]) == 1


# --- suppression ------------------------------------------------------------------

def test_suppression_is_scoped_to_the_block(stub_model):
    with fallback_suppressed(["Physics"]):
        assert model_backed_claim(agent_name="Physics", question="q?", question_id="q") is None
        assert model_backed_claim(agent_name="Theology", question="q?", question_id="q") is not None
    assert model_backed_claim(agent_name="Physics", question="q?", question_id="q") is not None


def _deliberate(world, name, fidelity):
    log = world["log"](f"unit-{name}")
    runner = SingleUnitRunner(log, shared_state={})
    unit = make_deliberation_unit("what force holds the moon in orbit?", name, fidelity=fidelity)
    while unit.status != "completed":
        runner.run_round(unit)
    return log.read_latest()["shared_state"]["answer"]


def test_regrounding_agent_asserts_only_what_it_can_ground(world, stub_model):
    normal = _deliberate(world, "q1", world["fid"])
    assert [c["issuing_agent"] for c in normal["committed"]] == ["Physics"]  # the model fallback

    # Set the stage directly to test what re-grounding DOES, independent of
    # how it's entered (entry is covered above and in test_fingerprints.py).
    world["fid"].set_remediation("Physics", {"stage": "regrounding", "until_reading": 99, "history": []})

    grounded = _deliberate(world, "q2", world["fid"])
    assert grounded["committed"] == []
    assert grounded["regrounding_agents"] == ["Physics"]


# --- inside an idle cycle ---------------------------------------------------------------

def test_idle_cycle_starts_remediation_for_a_drifting_agent(world):
    fid = world["fid"]
    for _ in range(3):
        _reading(fid, 1.0)
    ledger = QuestionLedger(world["log"]("ledger"))
    ledger.submit(QuestionLedgerEntry(id="q1"))
    drifted = {"question_id": "q1", "round": 1, "issuing_agent": "Mathematics",
               "statement": "a model-written maths claim", "claim_type": "formal", "confidence": 0.6,
               "defeat_condition": "x", "jurisdiction_check": True, "status": "committed",
               "supporting_provenance": ["llm:olmo3-7b"], "serving_model": "olmo3-7b"}
    ledger.append_version("q1", {"question": "q", "frame": {}, "committed": [drifted],
                                 "dissent": [], "plural_answers": []})
    ctx = IdleContext(ledger=ledger, reputability=ReputabilityStore(world["log"]("rep")),
                      fidelity=fid, checkpoints=world["cp"])
    log = world["log"]("idle")
    runner = SingleUnitRunner(log, shared_state={})
    unit = make_idle_evolution_unit(ctx, "idle-1")
    while unit.status != "completed":
        runner.run_round(unit)
    result = log.read_latest()["shared_state"]["idle_result"]
    assert "Mathematics" in result["fidelity_flags"]
    assert result["remediation"]["Mathematics"] == "regrounding"
