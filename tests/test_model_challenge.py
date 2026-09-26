"""Owner decision 10 (batch 10, Phase AO): during idle re-examination a
model may challenge a model-backed claim. A provisional model's challenge is
recorded as dissent only; an established model's counts as a challenge."""
import pytest
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.scheduler.runner import SingleUnitRunner
from athenaeum_body.ledger import QuestionLedger
from athenaeum_body.reputability_store import ReputabilityStore
from athenaeum_body.consolidation_store import ConsolidationStore
from athenaeum_body.calibration_store import CalibrationStore
from athenaeum_body.model_fitness_store import ModelFitnessStore
from athenaeum_body.schemas import QuestionLedgerEntry
from athenaeum_brain import model_backed_reasoning
from athenaeum_brain.claims import Claim
from athenaeum_brain.model_backed_reasoning import DEFAULT_MODEL, CHALLENGE_PROMPT, model_challenge
from athenaeum_brain.model_fitness import admit_model, model_standing, ESTABLISHED_AFTER
from athenaeum_brain.idle_evolution import IdleContext, make_idle_evolution_unit

MODEL_CLAIM = "gravity holds the moon in orbit"


class Model:
    """Answers deliberation prompts with MODEL_CLAIM and challenge prompts with `verdict`."""
    def __init__(self, verdict):
        self.verdict, self.challenges_asked = verdict, []

    def __call__(self, question, *a, **k):
        if question.startswith(CHALLENGE_PROMPT.split("{")[0]):
            self.challenges_asked.append(question)
            return self.verdict
        return MODEL_CLAIM


def claim(statement=MODEL_CLAIM, serving_model=DEFAULT_MODEL, agent="Physics", source=None):
    return Claim(question_id="q1", round=1, issuing_agent=agent, statement=statement, claim_type="empirical",
                 confidence=0.6, defeat_condition="d", jurisdiction_check=True,
                 supporting_provenance=[source or f"llm:{serving_model}"], serving_model=serving_model,
                 status="committed")


@pytest.mark.parametrize("verdict, challenges", [("No.", True), ("no, it is not", True), ("NO", True),
                                                  ("Yes", False), ("Not sure", False), ("Nope", False),
                                                  (None, False), ("", False)])
def test_only_a_plain_no_is_a_challenge(monkeypatch, verdict, challenges):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: verdict)
    c = claim()
    result = model_challenge(c, "idle-1")
    assert (result is not None) == challenges
    if result:
        assert result.relation == "challenges" and result.target_claim_id == c.claim_id
        assert result.issuing_agent == f"model:{DEFAULT_MODEL}"


class World:
    def __init__(self, tmp, monkeypatch, verdict):
        self.model = Model(verdict)
        monkeypatch.setattr(model_backed_reasoning, "ask_model", self.model)
        self.cas = ContentAddressedStore(tmp / "cas")
        log = lambda name: CheckpointLog(cas=self.cas, index_path=tmp / f"{name}.txt")
        self.log = log
        self.ledger = QuestionLedger(log("ledger"))
        self.fitness = ModelFitnessStore(log("fit"))
        admit_model(self.fitness, DEFAULT_MODEL, rationale="test", admitted_by="owner")
        self.cal = CalibrationStore(log("cal"))
        self.cons = ConsolidationStore(log("cons"), ContentAddressedStore(tmp / "arch"))
        self.ctx = IdleContext(ledger=self.ledger, reputability=ReputabilityStore(log("rep")),
                               consolidation=self.cons, calibration=self.cal,
                               model_challenger=DEFAULT_MODEL, model_fitness=self.fitness)
        for qid, c in (("qm", claim()), ("qd", claim("17 is prime", serving_model=None, agent="Mathematics",
                                                        source="computed:trial_division"))):
            self.ledger.submit(QuestionLedgerEntry(id=qid))
            self.ledger.append_version(qid, {"question": "q", "frame": {}, "committed": [c.to_dict()],
                                             "dissent": [], "plural_answers": []})

    def establish(self):
        for _ in range(ESTABLISHED_AFTER):
            self.fitness.record_outcome("Physics", DEFAULT_MODEL, "corroborated")
        assert model_standing(self.fitness, DEFAULT_MODEL) == "established"

    def cycle(self, n=1):
        log = self.log(f"idle-{n}")
        runner = SingleUnitRunner(log, shared_state={})
        unit = make_idle_evolution_unit(self.ctx, f"idle-{n}", sample_size=10)
        while unit.status != "completed":
            runner.run_round(unit)
        return log.read_latest()["shared_state"]["idle_result"]


def test_a_provisional_models_challenge_is_dissent_only(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, verdict="No.")
    result = w.cycle()
    assert result["status_counts"]["disputed"] == 1 and result["status_counts"]["challenged"] == 0
    (dissent,) = result["model_dissent"]
    assert dissent["question_id"] == "qm" and "answers 'no'" in dissent["dissent"]
    assert "qm" not in result["reevaluation_candidates"]            # reopens nothing
    assert w.cons.get(f"Physics::{MODEL_CLAIM}") is None             # no survival credit either
    assert "Physics" not in w.cal.agents()                           # and no calibration outcome
    assert len(w.model.challenges_asked) == 1                         # the deterministic claim isn't put to it


def test_an_established_models_challenge_counts(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, verdict="No.")
    w.establish()
    result = w.cycle()
    assert result["status_counts"]["challenged"] == 1 and result["status_counts"]["disputed"] == 0
    assert result["model_dissent"] == []
    assert "qm" in result["reevaluation_candidates"]
    assert f"Physics::{MODEL_CLAIM}" in result["dispute_rulings"]


def test_a_model_that_agrees_changes_nothing(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, verdict="Yes.")
    result = w.cycle()
    assert result["status_counts"]["survived"] == 2 and result["status_counts"]["disputed"] == 0
    assert w.cons.get(f"Physics::{MODEL_CLAIM}")["cycles"] == 1


def test_without_a_challenger_nothing_is_asked(tmp_path, monkeypatch):
    w = World(tmp_path, monkeypatch, verdict="No.")
    w.ctx.model_challenger = None
    assert w.cycle()["status_counts"]["survived"] == 2 and w.model.challenges_asked == []


def test_the_api_turns_it_on_with_its_admitted_model(tmp_path, monkeypatch):
    from athenaeum_body.api import build_app
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)
    idle = build_app(tmp_path).maintainer.idle
    assert idle.model_challenger == DEFAULT_MODEL and idle.model_fitness is not None
