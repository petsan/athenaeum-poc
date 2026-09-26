"""Section 2.4.1: style fingerprints for Physics, Philosophy and Theology,
checked against the agents' REAL claims -- each marker must pass an
agent's own method and fail a general-purpose model answering in its place."""
import pytest
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.domain_fidelity_store import DomainFidelityStore
from athenaeum_brain import model_backed_reasoning
from athenaeum_brain.agents import all_agents, MasterOfPhysics, MasterOfPhilosophy, MasterOfTheology
from athenaeum_brain.domain_fidelity import FINGERPRINT_CHECKS, fingerprint_deviation, compute_score
from athenaeum_brain.fidelity_remediation import remediate


@pytest.fixture
def no_model(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)


@pytest.fixture
def model(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: "a model's general answer")


def _dicts(claims):
    return [c.to_dict() for c in claims]


def test_every_current_agent_has_a_fingerprint():
    assert {a.name for a in all_agents()} <= set(FINGERPRINT_CHECKS)


@pytest.mark.parametrize("agent,question", [
    (MasterOfPhysics, "how long does an object take to fall from 19.6m?"),
    (MasterOfPhysics, "will an object dropped from 20m land within 3 seconds?"),  # incl. the forecast claim
    (MasterOfPhilosophy, "should we ban it?"),
    (MasterOfTheology, "what does stoicism hold about the good life?"),
])
def test_agents_own_method_is_on_style(no_model, agent, question):
    claims = _dicts(agent().explore(question, "q"))
    assert claims and fingerprint_deviation(agent.name, claims) == 0.0


@pytest.mark.parametrize("agent,question", [
    (MasterOfPhysics, "what force holds the moon in orbit?"),
    (MasterOfPhilosophy, "is courage good?"),  # in jurisdiction ("good"), no ought to name
])
def test_a_model_answering_in_the_agents_place_is_off_style(model, agent, question):
    [claim] = _dicts(agent().explore(question, "q"))
    assert claim["supporting_provenance"][0].startswith("llm:")
    assert fingerprint_deviation(agent.name, [claim]) == 1.0


def test_theology_style_is_the_traditional_typing_itself():
    typed = {"issuing_agent": "Theology", "claim_type": "traditional"}
    mistyped = {"issuing_agent": "Theology", "claim_type": "empirical"}
    assert fingerprint_deviation("Theology", [typed, mistyped]) == 0.5


def test_physics_claim_with_a_vacuous_defeat_condition_is_off_style():
    claim = {"issuing_agent": "Physics", "defeat_condition": "none"}
    assert fingerprint_deviation("Physics", [claim]) == 1.0


def test_physics_drift_can_now_be_confirmed_and_regrounded(tmp_path, model):
    """The Phase F gap: with no Physics fingerprint, a Physics drift could
    be flagged but never confirmed. Now it can."""
    store = DomainFidelityStore(CheckpointLog(cas=ContentAddressedStore(tmp_path / "cas"),
                                              index_path=tmp_path / "fid.txt"))
    own = _dicts(MasterOfPhysics()._explore_deterministic("how long does it take to fall 20 meters?", "q"))
    drifted = _dicts(MasterOfPhysics().explore("what force holds the moon in orbit?", "q"))
    for _ in range(3):
        store.record("Physics", compute_score("Physics", own, []))
    store.record("Physics", compute_score("Physics", drifted, []))
    assert remediate(store, "Physics", recent_claims=drifted, cycle_id="c1")["stage"] == "regrounding"
