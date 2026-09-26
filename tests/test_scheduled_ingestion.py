"""Batch 5, Phase Y: ingestion as a scheduled, checkpointed work unit
(Section 9) -- one source per round into the CAS and the Belief Graph, safe
to kill at any point, and run by the Maintainer behind questions."""
import functools
import http.server
import threading
import pytest
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.scheduler.runner import SingleUnitRunner
from athenaeum_body.ledger import QuestionLedger
from athenaeum_body.reputability_store import ReputabilityStore
from athenaeum_body.belief_graph_store import BeliefGraphStore
from athenaeum_body.ingestion import FixtureSource, FetchError, make_ingestion_unit
from athenaeum_brain import model_backed_reasoning
from athenaeum_brain.belief_graph import citations
from athenaeum_brain.idle_evolution import IdleContext
from athenaeum_brain.maintenance import Maintainer, MaintenancePolicy


@pytest.fixture(autouse=True)
def _no_model_fallback(monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)


class FakeWeb:
    """A fetch seam that counts requests per URL; unknown URLs fail like a dead host."""
    def __init__(self, pages):
        self.pages, self.calls = pages, {}

    def __call__(self, url, *, license):
        self.calls[url] = self.calls.get(url, 0) + 1
        if url not in self.pages:
            raise FetchError(f"fetch failed for {url!r}: connection refused")
        return FixtureSource(url=url, content=self.pages[url].encode(), license=license)


SPECS = [
    {"url": "https://a.example/paper", "license": "cc-by"},
    {"url": "https://b.example/review", "license": "cc-by", "cites": ["https://a.example/paper"]},
    {"url": "https://c.example/closed", "license": "all-rights-reserved"},
    {"url": "https://d.example/paywall", "license": "cc-by", "is_paid_or_metered": True},
    {"url": "https://e.example/down", "license": "cc-by"},
    {"url": "fixture:local-note", "license": "public-domain", "content": "a hand-authored note"},
]
WEB = {"https://a.example/paper": "paper text", "https://b.example/review": "review text",
       "https://c.example/closed": "closed text"}


@pytest.fixture
def world(tmp_path):
    cas = ContentAddressedStore(tmp_path / "cas")
    return {"tmp": tmp_path, "cas": cas, "graph": BeliefGraphStore(CheckpointLog(cas=cas, index_path=tmp_path / "g.txt")),
            "log": lambda name: CheckpointLog(cas=cas, index_path=tmp_path / f"{name}.txt")}


def _run(unit, log):
    runner = SingleUnitRunner(log, shared_state=(log.read_latest() or {}).get("shared_state", {}))
    unit.round_index = runner.resume_round_index(unit.id)
    while unit.status != "completed":
        runner.run_round(unit)
    return runner.shared_state[f"ingestion:{unit.id}"]


def test_one_batch_records_what_passes_and_says_why_the_rest_did_not(world):
    web = FakeWeb(WEB)
    state = _run(make_ingestion_unit("batch-1", SPECS, world["cas"], world["graph"], fetch=web), world["log"]("u"))
    result = state["ingestion_result"]
    assert result["accepted"] == ["https://a.example/paper", "https://b.example/review", "fixture:local-note"]
    assert result["rejected"] == {
        "https://c.example/closed": "no license permitting reuse",
        "https://d.example/paywall": "paid or metered access -- hard invariant, never fetched",
        "https://e.example/down": "fetch failed: fetch failed for 'https://e.example/down': connection refused",
    }
    assert "https://d.example/paywall" not in web.calls   # a paid source is never requested at all
    assert citations(world["graph"]) == {"https://b.example/review": ["https://a.example/paper"]}
    assert world["graph"].node("source:https://c.example/closed") is None
    paper = [o for o in state["outcomes"] if o["url"] == "https://a.example/paper"][0]
    assert world["cas"].get(paper["content_hash"]) == b"paper text"


def test_a_kill_between_rounds_refetches_nothing(world):
    web, log = FakeWeb(WEB), world["log"]("u")
    unit = make_ingestion_unit("batch-1", SPECS, world["cas"], world["graph"], fetch=web)
    runner = SingleUnitRunner(log, shared_state={})
    runner.run_round(unit); runner.run_round(unit)          # then the process dies
    _run(make_ingestion_unit("batch-1", SPECS, world["cas"], world["graph"], fetch=web), world["log"]("u"))
    assert all(n == 1 for n in web.calls.values())


def test_a_kill_inside_a_round_refetches_that_source_only_and_records_nothing_twice(world):
    web, log = FakeWeb(WEB), world["log"]("u")
    unit = make_ingestion_unit("batch-1", SPECS, world["cas"], world["graph"], fetch=web)
    runner = SingleUnitRunner(log, shared_state={})
    runner.run_round(unit)
    unit.round_handler(dict(runner.shared_state), 1)   # round 1's side effects happen, its checkpoint never does
    edges_before = len(world["graph"].edges())
    state = _run(make_ingestion_unit("batch-1", SPECS, world["cas"], world["graph"], fetch=web), world["log"]("u"))
    assert web.calls["https://b.example/review"] == 2 and web.calls["https://a.example/paper"] == 1
    assert len(world["graph"].edges()) == edges_before     # the re-run round wrote nothing new
    assert [o["url"] for o in state["outcomes"]] == [s["url"] for s in SPECS]  # each outcome once


def test_an_empty_batch_completes(world):
    assert _run(make_ingestion_unit("empty", [], world["cas"]), world["log"]("u"))["ingestion_result"] == {
        "batch_id": "empty", "accepted": [], "rejected": {}}


def test_a_real_http_fetch_over_localhost(world):
    site = world["tmp"] / "site"
    site.mkdir()
    (site / "paper.txt").write_bytes(b"served over real HTTP")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
    handler.log_message = lambda *a: None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        specs = [{"url": f"{base}/paper.txt", "license": "cc-by"}, {"url": f"{base}/missing.txt", "license": "cc-by"}]
        state = _run(make_ingestion_unit("live", specs, world["cas"], world["graph"]), world["log"]("u"))
    finally:
        server.shutdown()
    result = state["ingestion_result"]
    assert result["accepted"] == [f"{base}/paper.txt"]
    assert "404" in result["rejected"][f"{base}/missing.txt"]
    assert world["cas"].get(state["outcomes"][0]["content_hash"]) == b"served over real HTTP"


# --- through the Maintainer ------------------------------------------------------

def _maintainer(world, web, **kw):
    idle = IdleContext(ledger=QuestionLedger(world["log"]("ledger")), reputability=ReputabilityStore(world["log"]("rep")))
    return Maintainer(idle=idle, log_for=world["log"], belief_graph=world["graph"], ingestion_cas=world["cas"],
                      fetch=web, policy=MaintenancePolicy(idle_every_questions=100), **kw)


def test_the_maintainer_serves_questions_before_ingestion(world):
    m = _maintainer(world, FakeWeb(WEB))
    m.submit_ingestion("seed", SPECS)
    m.submit_question("q1", "is 17 prime?")
    events = m.run()
    kinds = [e["kind"] for e in events]
    assert kinds.index("question") < kinds.index("ingestion")
    (ingested,) = [e for e in events if e["kind"] == "ingestion"]
    assert ingested["batch_id"] == "seed" and len(ingested["accepted"]) == 3
    assert m.idle.citation_map() == {"https://b.example/review": ["https://a.example/paper"]}
    assert "ingestion:seed" not in m.scheduler.runner.shared_state   # harvested, checkpoints stay bounded


def test_an_ingestion_batch_survives_a_maintainer_restart(world):
    web = FakeWeb(WEB)
    m = _maintainer(world, web)
    m.submit_ingestion("seed", SPECS)
    m.tick(); m.tick()
    del m
    m = _maintainer(world, web)
    assert m.recovered == ["seed"]
    (ingested,) = [e for e in m.run() if e["kind"] == "ingestion"]
    assert len(ingested["accepted"]) == 3 and all(n == 1 for n in web.calls.values())


def test_ingestion_needs_somewhere_to_store_content(world):
    idle = IdleContext(ledger=QuestionLedger(world["log"]("ledger")), reputability=ReputabilityStore(world["log"]("rep")))
    m = Maintainer(idle=idle, log_for=world["log"])
    with pytest.raises(ValueError, match="ingestion_cas"):
        m.submit_ingestion("seed", SPECS)
    m = _maintainer(world, FakeWeb(WEB))
    m.submit_ingestion("seed", SPECS)
    with pytest.raises(ValueError, match="already registered"):
        m.submit_ingestion("seed", SPECS)
