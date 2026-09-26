"""Batch 4, Phase U: ingestion records sources and their citations in the
Belief Graph, and idle evolution (consolidation, disputes, audits) reads
citation data from there instead of only from a hand-passed map."""
import pytest
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.scheduler.runner import SingleUnitRunner
from athenaeum_body.ledger import QuestionLedger
from athenaeum_body.schemas import QuestionLedgerEntry
from athenaeum_body.reputability_store import ReputabilityStore
from athenaeum_body.consolidation_store import ConsolidationStore
from athenaeum_body.belief_graph_store import BeliefGraphStore
from athenaeum_body.ingestion import FixtureSource, ingest, seed_load
from athenaeum_brain import model_backed_reasoning
from athenaeum_brain.belief_graph import citations, record_answer
from athenaeum_brain.claims import Claim
from athenaeum_brain.idle_evolution import IdleContext, make_idle_evolution_unit
from athenaeum_brain.maintenance import Maintainer

STATEMENT = "an object falling from 19.6m takes approximately 2.00s to hit the ground (v0=0, g=9.8 m/s^2)"
KEY = f"Physics::{STATEMENT}"


@pytest.fixture(autouse=True)
def _no_model_fallback(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)


def _log(tmp, name, cas):
    return CheckpointLog(cas=cas, index_path=tmp / f"{name}.txt")


@pytest.fixture
def world(tmp_path):
    cas = ContentAddressedStore(tmp_path / "cas")
    return {"cas": cas, "graph": BeliefGraphStore(_log(tmp_path, "graph", cas)),
            "log": lambda name: _log(tmp_path, name, cas)}


def _src(url, cites=(), license="cc-by"):
    return FixtureSource(url=url, content=url.encode(), license=license, cites=list(cites))


# --- ingestion -> graph -------------------------------------------------------------

def test_ingest_records_the_source_and_its_citations(world):
    g = world["graph"]
    entry = ingest(_src("https://a.example", cites=["https://b.example"]), world["cas"], g)
    node = g.node("source:https://a.example")
    assert node.node_type == "source"
    assert node.data["license"] == "cc-by" and node.data["content_hash"] == entry.content_hash
    assert g.node("source:https://b.example") is not None  # cited but not yet ingested: a bare node
    assert citations(g) == {"https://a.example": ["https://b.example"]}


def test_ingesting_twice_is_idempotent(world):
    g = world["graph"]
    for _ in range(2):
        ingest(_src("https://a.example", cites=["https://b.example"]), world["cas"], g)
    assert len(g.edges(edge_type="cites")) == 1
    assert citations(g) == {"https://a.example": ["https://b.example"]}


def test_rejected_sources_leave_no_trace_and_seed_load_records_the_rest(world):
    g = world["graph"]
    entries = seed_load([_src("https://a.example", cites=["https://b.example"]),
                         _src("https://closed.example", license="all-rights-reserved")], world["cas"], g)
    assert [e.id for e in entries] == ["https://a.example"]
    assert g.node("source:https://closed.example") is None


def test_without_a_graph_ingestion_is_unchanged(world):
    entry = ingest(_src("https://a.example", cites=["https://b.example"]), world["cas"])
    assert entry.metadata == {"license": "cc-by", "cites": ["https://b.example"]}


def test_citations_ignore_claim_provenance_edges(world):
    g = world["graph"]
    claim = Claim(question_id="q1", round=1, issuing_agent="Physics", statement=STATEMENT, claim_type="empirical",
                  confidence=0.9, defeat_condition="d", jurisdiction_check=True,
                  supporting_provenance=["https://a.example"], status="committed")
    record_answer(g, "q1", {"question": "q", "committed": [claim.to_dict()], "dissent": []}, version=1)
    assert citations(g) == {}  # claim -cites-> source is provenance, not citation between sources


# --- idle evolution reads citations from the graph ------------------------------------

def test_citation_map_merges_hand_supplied_and_graph_citations(world):
    ingest(_src("https://a.example", cites=["https://b.example", "https://c.example"]), world["cas"], world["graph"])
    ctx = IdleContext(ledger=QuestionLedger(world["log"]("ledger")), reputability=ReputabilityStore(world["log"]("rep")),
                      cites={"https://a.example": ["https://c.example"], "https://x.example": ["https://y.example"]},
                      belief_graph=world["graph"])
    assert ctx.citation_map() == {"https://a.example": ["https://c.example", "https://b.example"],
                                  "https://x.example": ["https://y.example"]}
    assert ctx.cites == {"https://a.example": ["https://c.example"], "https://x.example": ["https://y.example"]}


def _run_cycles(world, graph, n):
    ledger = QuestionLedger(world["log"]("ledger"))
    ledger.submit(QuestionLedgerEntry(id="q1"))
    claim = Claim(question_id="q1", round=1, issuing_agent="Physics", statement=STATEMENT, claim_type="empirical",
                  confidence=0.95, defeat_condition="a timed drop disagreeing", jurisdiction_check=True,
                  supporting_provenance=["https://a.example", "https://b.example"], status="committed")
    ledger.append_version("q1", {"question": "q", "frame": {}, "committed": [claim.to_dict()],
                                 "dissent": [], "plural_answers": []})
    cons = ConsolidationStore(world["log"]("cons"), ContentAddressedStore(world["cas"].root.parent / "archive"))
    ctx = IdleContext(ledger=ledger, reputability=ReputabilityStore(world["log"]("rep")), consolidation=cons,
                      belief_graph=graph, consolidation_min_cycles=3, consolidation_min_sources=2)
    for i in range(1, n + 1):
        log = world["log"](f"idle-{i}")
        runner = SingleUnitRunner(log, shared_state={})
        unit = make_idle_evolution_unit(ctx, f"idle-{i}")
        while unit.status != "completed":
            runner.run_round(unit)
    return cons.get(KEY)


def test_independent_ingested_sources_let_a_claim_be_compacted(world):
    seed_load([_src("https://a.example"), _src("https://b.example")], world["cas"], world["graph"])
    assert _run_cycles(world, world["graph"], 3)["tier"] == "C"


def test_ingested_citation_makes_two_sources_count_once(world):
    # b cites a, so they are one line of evidence (6.4.2) -- known only from the graph
    seed_load([_src("https://a.example"), _src("https://b.example", cites=["https://a.example"])],
              world["cas"], world["graph"])
    entry = _run_cycles(world, world["graph"], 3)
    assert entry["tier"] == "B" and entry["cycles"] == 3


def test_maintainer_shares_its_graph_with_idle_evolution(world):
    ctx = IdleContext(ledger=QuestionLedger(world["log"]("ledger")), reputability=ReputabilityStore(world["log"]("rep")))
    Maintainer(idle=ctx, log_for=world["log"], belief_graph=world["graph"])
    assert ctx.belief_graph is world["graph"]
    own = BeliefGraphStore(world["log"]("own"))
    ctx2 = IdleContext(ledger=QuestionLedger(world["log"]("ledger2")), reputability=ReputabilityStore(world["log"]("rep2")),
                       belief_graph=own)
    Maintainer(idle=ctx2, log_for=world["log"], belief_graph=world["graph"])
    assert ctx2.belief_graph is own  # an explicitly given graph is kept
