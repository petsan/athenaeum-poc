"""Batch 5, Phase X: a source's grade change reaches every answer resting on
it, through the Belief Graph (source <- claim <- answer), instead of only
the claims one idle cycle happened to sample."""
import pytest
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.ledger import QuestionLedger
from athenaeum_body.reputability_store import ReputabilityStore
from athenaeum_body.belief_graph_store import BeliefGraphStore
from athenaeum_body.ingestion import FixtureSource, ingest
from athenaeum_brain import model_backed_reasoning
from athenaeum_brain.belief_graph import questions_relying_on_source, record_answer
from athenaeum_brain.idle_evolution import IdleContext, grade_change_candidates
from athenaeum_brain.maintenance import Maintainer, MaintenancePolicy

SRC = "computed:trial_division"
PRIMES = {"q1": "is 17 prime?", "q2": "is 19 prime?", "q3": "is 23 prime?"}


@pytest.fixture(autouse=True)
def _no_model_fallback(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)


class Host:
    def __init__(self, tmp):
        self.tmp, self.cas = tmp, ContentAddressedStore(tmp / "cas")
        self.rep = ReputabilityStore(self.log("rep"))
        self.ledger = QuestionLedger(self.log("ledger"))
        self.graph = BeliefGraphStore(self.log("graph"))

    def log(self, name):
        return CheckpointLog(cas=self.cas, index_path=self.tmp / f"{name}.txt")

    def maintainer(self, with_graph=True):
        # sample one claim per cycle, and let importance never be the reason a reopen doesn't happen
        idle = IdleContext(ledger=self.ledger, reputability=self.rep)
        return Maintainer(idle=idle, log_for=self.log, belief_graph=self.graph if with_graph else None,
                          policy=MaintenancePolicy(idle_every_questions=100, idle_sample_size=1,
                                                   importance_threshold=0.0))

    def downgrade(self, src=SRC, margin=5):
        """Challenge the source until its grade changes, then `margin` more
        times: every later deliberation citing it records a corroboration,
        which would otherwise flip a borderline grade straight back."""
        before = self.rep.current_grade(src)["grade"]
        for _ in range(50):
            self.rep.record_outcome(src, "source", "challenged")
            if self.rep.current_grade(src)["grade"] != before:
                for _ in range(margin):
                    self.rep.record_outcome(src, "source", "challenged")
                return self.rep.current_grade(src)["grade"]
        raise AssertionError("grade never changed")


def _idle_events(events):
    return [e for e in events if e["kind"] == "idle"]


def test_a_grade_change_reopens_every_dependent_answer_not_just_the_sampled_one(tmp_path):
    h = Host(tmp_path)
    m = h.maintainer()
    for qid, q in PRIMES.items():
        m.submit_question(qid, q)
    assert _idle_events(m.run())[-1]["reopened"] == []   # nothing has changed yet

    now = h.downgrade()
    m.submit_question("q4", "is 29 prime?")   # answered under the new grade; brings the next cycle
    (cycle,) = _idle_events(m.run())
    assert cycle["reopened"] == ["q1", "q2", "q3"]
    for qid in PRIMES:
        versions = h.ledger.get(qid).versions
        assert len(versions) == 2
        assert versions[1]["source_grades_at_use"][SRC]["grade"] == now
        assert any(SRC in r for r in versions[1]["reopen_context"]["reasons"])
    assert len(h.ledger.get("q4").versions) == 1  # its answer already reflects the new grade

    # once reopened, the snapshots match: the next cycle has nothing to do
    m.submit_question("q5", "is 31 prime?")
    assert _idle_events(m.run())[-1]["reopened"] == []


def test_without_the_graph_the_same_change_reaches_no_answer(tmp_path):
    """The gap Phase X closes: a 'contested' source only makes the sampled
    claim 'weakened', which is not a reevaluation candidate -- and the other
    answers are never looked at."""
    h = Host(tmp_path)
    m = h.maintainer(with_graph=False)
    for qid, q in PRIMES.items():
        m.submit_question(qid, q)
    m.run()
    h.downgrade()
    m.submit_question("q4", "is 29 prime?")
    (cycle,) = _idle_events(m.run())
    assert cycle["reopened"] == [] and all(len(h.ledger.get(q).versions) == 1 for q in PRIMES)


# --- the graph query and the candidate finder ------------------------------------

def _claim(statement, source):
    return {"statement": statement, "issuing_agent": "Mathematics", "claim_type": "formal",
            "supporting_provenance": [source]}


def test_only_latest_committed_reliance_counts(tmp_path):
    h = Host(tmp_path)
    g = h.graph
    record_answer(g, "old", {"committed": [_claim("a", "s1")], "dissent": []}, version=0)
    record_answer(g, "old", {"committed": [_claim("b", "s2")], "dissent": []}, version=1)  # superseded s1
    record_answer(g, "dissent-only", {"committed": [], "dissent": [{"claim": _claim("c", "s1")}]}, version=0)
    record_answer(g, "current", {"committed": [_claim("a", "s1")], "dissent": []}, version=0)
    ingest(FixtureSource(url="s3", content=b"x", license="cc-by", cites=["s1"]), h.cas, g)  # source->source
    assert questions_relying_on_source(g, "s1") == ["current"]
    assert questions_relying_on_source(g, "s2") == ["old"]
    assert questions_relying_on_source(g, "unknown") == []


def test_candidates_need_a_graph_and_a_real_difference(tmp_path):
    h = Host(tmp_path)
    m = h.maintainer()
    m.submit_question("q1", "is 17 prime?")
    m.run()
    ctx = m.idle
    assert grade_change_candidates(ctx) == {}   # graded, but unchanged since the answer
    h.downgrade()
    assert grade_change_candidates(ctx) == {"q1": [SRC]}
    assert grade_change_candidates(IdleContext(ledger=h.ledger, reputability=h.rep)) == {}  # no graph
