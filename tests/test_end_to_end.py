"""End-to-end: one realistic lifecycle through every Brain mechanism at
once, on real stores and the real scheduler -- deliberation with every
option on, a kill/resume, importance, idle evolution into consolidation,
a grade-driven reopen that must expand a compacted claim, a forecast
resolution, both audits, the integrity gates and the adversarial suite.

Per-phase tests prove each piece; this proves they compose. The model
fallback is stubbed (deterministic text) so the scenario never depends on
the model-lab guests' health; everything else is real."""
import subprocess
import sys
import pytest
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.scheduler.runner import SingleUnitRunner
from athenaeum_body.sandbox import SandboxResult
from athenaeum_body.ledger import QuestionLedger
from athenaeum_body.schemas import QuestionLedgerEntry
from athenaeum_body.reputability_store import ReputabilityStore
from athenaeum_body.consolidation_store import ConsolidationStore
from athenaeum_body.domain_fidelity_store import DomainFidelityStore
from athenaeum_body.human_checkpoint_store import HumanCheckpointStore
from athenaeum_body.model_fitness_store import ModelFitnessStore
from athenaeum_body.audit_store import AuditStore
from athenaeum_brain import model_backed_reasoning
from athenaeum_brain.loop import make_deliberation_unit
from athenaeum_brain.model_fitness import admit_model
from athenaeum_brain.reopening import rate_and_store_importance, reopen_if_material
from athenaeum_brain.idle_evolution import IdleContext, make_idle_evolution_unit
from athenaeum_brain.consolidation import should_promote_to_c, compact
from athenaeum_brain.audits import reevaluation_audit, consolidation_audit
from athenaeum_brain.evaluation import check_integrity_gates, run_adversarial_suite

QUESTIONS = {
    "prime": "is 17 prime?",
    "round": "should we round 2.5 up or down?",
    "forecast": "will an object dropped from 20m land within 3 seconds?",
    "history": "did world war i cause world war ii?",
    "orbit": "what force holds the moon in orbit?",   # only the model fallback can answer
}
PRIME_KEY = "Mathematics::17 is prime"


def local_runner(code):
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
    return SandboxResult(status="completed", stdout=p.stdout, stderr=p.stderr, returncode=p.returncode)


class System:
    def __init__(self, tmp):
        self.tmp, self.cas, self.n = tmp, ContentAddressedStore(tmp / "cas"), 0
        self.ledger = QuestionLedger(self.log("ledger"))
        self.rep = ReputabilityStore(self.log("rep"))
        self.cons = ConsolidationStore(self.log("cons"), ContentAddressedStore(tmp / "archive"))
        self.fid = DomainFidelityStore(self.log("fid"))
        self.cp = HumanCheckpointStore(self.log("cp"))
        self.fit = ModelFitnessStore(self.log("fit"))
        self.audits = AuditStore(self.log("audits"))
        self.idle = IdleContext(ledger=self.ledger, reputability=self.rep, consolidation=self.cons,
                                fidelity=self.fid, checkpoints=self.cp)

    def log(self, name):
        return CheckpointLog(cas=self.cas, index_path=self.tmp / f"{name}.txt")

    def fresh(self):
        self.n += 1
        return self.log(f"u{self.n}")

    def unit(self, question, qid):
        return make_deliberation_unit(question, qid, reputability=self.rep, model_fitness=self.fit,
                                      fidelity=self.fid,
                                      verification={"enabled": True, "sandbox_run": local_runner})

    def ask(self, qid, question, kill_after=None):
        self.ledger.submit(QuestionLedgerEntry(id=qid))
        name = f"ask-{qid}"
        log, unit = self.log(name), self.unit(question, qid)
        runner = SingleUnitRunner(log, shared_state={})
        while unit.status != "completed":
            if kill_after is not None and unit.round_index == kill_after:
                log = self.log(name)  # a fresh process reading the same checkpoint files
                runner = SingleUnitRunner(log, shared_state=log.read_latest()["shared_state"])
                unit = self.unit(question, qid)
                unit.round_index = runner.resume_round_index(qid)
                kill_after = None
            runner.run_round(unit)
        answer = log.read_latest()["shared_state"]["answer"]
        self.ledger.append_version(qid, answer)
        return answer

    def idle_cycle(self, i):
        log = self.log(f"idle-{i}")
        runner = SingleUnitRunner(log, shared_state={})
        unit = make_idle_evolution_unit(self.idle, f"idle-{i}", sample_size=50, seed=i)
        while unit.status != "completed":
            runner.run_round(unit)
        return log.read_latest()["shared_state"]["idle_result"]


@pytest.fixture
def system(tmp_path, monkeypatch):
    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: "gravity holds the moon in orbit")
    return System(tmp_path)


def test_full_lifecycle(system):
    s = system
    admit_model(s.fit, "olmo3-7b", rationale="evaluated on the workbench", admitted_by="owner")

    # --- 1. deliberation, every option on, one killed mid-way -----------------------
    answers = {qid: s.ask(qid, q, kill_after=2 if qid == "prime" else None) for qid, q in QUESTIONS.items()}

    prime = answers["prime"]
    assert [c["statement"] for c in prime["committed"]] == ["17 is prime"]
    assert prime["verification"]["routed"] == 1  # sieve-checked by Engineering
    assert answers["round"]["plural_answers"] and \
        answers["round"]["output_answer"]["sections"]["recommendation"]["chosen_option"].startswith("none chosen")
    forecast = answers["forecast"]["output_answer"]["sections"]["forecast"]
    assert forecast["available"] and forecast["probability"] == 0.9
    assert [c["statement"] for c in answers["history"]["committed"]] == [
        "'world war i' (1914-07-28) precedes 'world war ii' (1939-09-01), "
        "so a causal/contributing link is chronologically POSSIBLE"]
    orbit = answers["orbit"]
    assert orbit["fitness_at_use"] == {"Physics::olmo3-7b": 0.5} and orbit["unadmitted_models"] == []

    # --- 2. importance ---------------------------------------------------------------
    importance = {qid: rate_and_store_importance(s.ledger, qid)["importance"] for qid in QUESTIONS}
    assert importance["round"] > importance["prime"]  # three domains + two output types vs one domain

    # --- 3. idle evolution into consolidation ---------------------------------------
    results = [s.idle_cycle(i) for i in range(5)]
    assert all(r["status_counts"]["challenged"] == 0 for r in results)
    assert all(r["amendment_proposal"] is None for r in results)
    entry = s.cons.get(PRIME_KEY)
    assert entry["cycles"] == 5
    # idle evolution compacts on its own (10.3) what meets the default bar of two
    # independent sources: the World News claim cites two dated events
    history_key = f"WorldNews::{answers['history']['committed'][0]['statement']}"
    assert [k for r in results for k in r["compacted"]] == [history_key]
    # the one-source primality claim needs a lower bar, applied here by hand
    assert should_promote_to_c(entry, min_cycles=5, min_sources=1)["eligible"]
    compact(s.cons, PRIME_KEY)

    # --- 4. a source is contested: a grade-driven reopen with a diff ----------------
    for _ in range(3):
        s.rep.record_outcome("computed:trial_division", "source", "challenged")
    reopened = reopen_if_material(s.ledger, "prime", reputability=s.rep, unit_log=s.fresh(),
                                  importance_threshold=0.1, consolidation=s.cons)
    assert reopened["reopened"] is True
    new = reopened["answer"]
    assert [t["claim"] for t in new["reopen_context"]["expanded_traces"]] == [PRIME_KEY]  # 10.5
    [change] = new["diff"]["weight_changes"]
    assert change["direction"] == "decreased"
    assert s.ledger.get("prime").versions[0] == prime  # history intact

    # --- 5. the forecast resolves: reopened regardless of importance -----------------
    resolved = reopen_if_material(s.ledger, "forecast", reputability=s.rep, unit_log=s.fresh(),
                                  importance_threshold=1.0, forecast_outcome=True)
    assert resolved["reopened"] is True
    assert resolved["answer"]["reopen_context"]["forecast_resolution"]["outcome"] is True

    # --- 6. audits, integrity gates, adversarial suite -------------------------------
    re_audit = reevaluation_audit(s.ledger, s.rep, audit_id="e2e-1", store=s.audits)
    by_q = {r["question_id"]: r["classification"] for r in re_audit["sampled"]}
    assert by_q == {"prime": "weights_only", "forecast": "forecast_resolution"}
    assert re_audit["thrash_suspect_rate"] == 0.0
    assert re_audit["stagnation_candidates"] == []

    cons_audit = consolidation_audit(s.cons, audit_id="e2e-2", min_sources=1, store=s.audits)
    assert cons_audit["population"] == 2 and cons_audit["failed"] == []

    for qid in QUESTIONS:
        latest = s.ledger.get(qid).versions[-1]
        assert check_integrity_gates(latest)["passed"], (qid, check_integrity_gates(latest))

    suite = run_adversarial_suite()
    assert suite["passed"] == suite["total"] == 16


# ---------------------------------------------------------------------------
# Batch 2 (J-N): the same system driven the way the async API drives it --
# through the Maintainer, with questions interleaved on one scheduler, the
# Belief Graph, fingerprints and the fixed number parsing all in play.
# ---------------------------------------------------------------------------

def test_full_lifecycle_through_the_maintainer(system):
    from athenaeum_body.belief_graph_store import BeliefGraphStore
    from athenaeum_brain.maintenance import Maintainer, MaintenancePolicy
    from athenaeum_brain.belief_graph import dependents

    s = system
    admit_model(s.fit, "olmo3-7b", rationale="evaluated on the workbench", admitted_by="owner")
    graph = BeliefGraphStore(s.log("graph"))
    m = Maintainer(idle=s.idle, log_for=s.log, model_fitness=s.fit, belief_graph=graph, audits=s.audits,
                   verification={"enabled": True, "sandbox_run": local_runner},
                   policy=MaintenancePolicy(idle_every_questions=10, audit_every_cycles=1))
    batch = {
        "p17": "is 17 prime?",
        "believe": "should we believe 17 is prime?",
        "round": "how should we round 2.5?",
        "even": "is 4 even?",                   # Phase K: no irrelevant primality claim
        "fall": "did the berlin wall fall in 1989?",  # #21: no 1989 m drop
    }
    for qid, q in batch.items():
        m.submit_question(qid, q)
    events = m.run()

    # every question answered -- its OWN question (known-bugs #26) -- then one idle cycle
    assert [e["kind"] for e in events] == ["question"] * 5 + ["idle"]
    latest = {qid: s.ledger.get(qid).versions[-1] for qid in batch}
    assert all(latest[qid]["question"] == q for qid, q in batch.items())
    assert [c["statement"] for c in latest["p17"]["committed"]] == ["17 is prime"]
    assert not any("prime" in c["statement"] for c in latest["even"]["committed"])
    assert not any("1989m" in c["statement"] for c in latest["fall"]["committed"])
    assert "Physics" not in latest["fall"]["frame"]["routed_agents"]  # #28: no physical context

    # Belief Graph: the shared claim links the two primality questions (Phase L)
    assert dependents(graph, "p17") == ["believe"]

    # a later claim about the same subject reopens the rounding question (7.2 trigger 2)
    s.ledger.update_importance("round", 0.9)
    m.submit_question("round-b", "should we round 2.50 up or down?")
    m.run()
    result = reopen_if_material(s.ledger, "round", reputability=s.rep, unit_log=s.fresh(), belief_graph=graph)
    assert result["reopened"] and any("newly relevant" in c for c in result["answer"]["diff"]["cause"])

    # every agent the idle cycle scored has a fingerprint (Phase J)
    from athenaeum_brain.domain_fidelity import FINGERPRINT_CHECKS
    from athenaeum_brain.agents import all_agents
    scored = [a.name for a in all_agents() if s.fid.history_for(a.name)]
    assert {"Mathematics", "Philosophy"} <= set(scored)
    assert all(agent in FINGERPRINT_CHECKS for agent in scored)

    # audits ran on their cadence; nothing left over in the scheduler's state
    assert s.audits.history("reevaluation")
    assert not [k for k in m.scheduler.runner.shared_state if k.startswith(("deliberation:", "idle:"))]

    for qid in list(batch) + ["round-b"]:
        assert check_integrity_gates(s.ledger.get(qid).versions[-1])["passed"], qid
    assert run_adversarial_suite()["passed"] == 16


# ---------------------------------------------------------------------------
# Batch 3 (O-R): whole-word routing, idle-driven compaction, and a
# Maintainer that is killed and replaced part-way through.
# ---------------------------------------------------------------------------

def test_lifecycle_across_a_restart_with_self_compaction(system):
    from athenaeum_brain.maintenance import Maintainer, MaintenancePolicy
    from athenaeum_brain.idle_evolution import IdleContext
    from athenaeum_brain.rounds import framing_round

    s = system
    idle = IdleContext(ledger=s.ledger, reputability=s.rep, consolidation=s.cons, fidelity=s.fid,
                       checkpoints=s.cp, consolidation_min_cycles=3, consolidation_min_sources=1)
    make = lambda: Maintainer(idle=idle, log_for=s.log, audits=s.audits,
                              policy=MaintenancePolicy(idle_every_questions=1, audit_every_cycles=1))

    # Phase O: routing is by whole words and physical context
    assert framing_round("does a ball fall faster than a feather?", "x")["routed_agents"] == ["Physics"]

    # Phase Q: killed with work in flight, then replaced
    m = make()
    m.submit_question("p1", "is 17 prime?")
    m.submit_question("p2", "how long does it take to fall 20 meters?")
    m.tick(); m.tick(); m.tick()
    del m
    m = make()
    assert sorted(m.recovered) == ["p1", "p2"]
    m.run()
    assert [c["statement"] for c in s.ledger.get("p1").versions[0]["committed"]] == ["17 is prime"]
    assert len(s.ledger.get("p1").versions) == 1 and len(s.ledger.get("p2").versions) == 1

    # Phase P: each new question brings another idle cycle; by the third,
    # the surviving claims are compacted by idle evolution itself
    for i in range(3):
        m.submit_question(f"more{i}", f"is {23 + 6 * i} prime?")
        m.run()
    assert s.cons.get(PRIME_KEY)["tier"] == "C"
    compacted = [k for k, e in s.cons.entries().items() if e["tier"] == "C"]
    assert consolidation_audit(s.cons, audit_id="b3", min_cycles=3, min_sources=1)["failed"] == []
    assert len(compacted) >= 2  # the fall-time claim too

    # audits ran every cycle; the demo (Phase R) has its own test
    assert len(s.audits.history("consolidation")) >= 3


# ---------------------------------------------------------------------------
# Batch 4 (S-V): calibration fed and audited, grade weights amended under the
# versioned standard, and citations ingested into the Maintainer's graph --
# all through one Maintainer. (V, the client, has its own tests.)
# ---------------------------------------------------------------------------

def test_lifecycle_with_calibration_weights_and_ingested_citations(system):
    from athenaeum_body.belief_graph_store import BeliefGraphStore
    from athenaeum_body.calibration_store import CalibrationStore
    from athenaeum_body.ingestion import FixtureSource, seed_load
    from athenaeum_brain.maintenance import Maintainer, MaintenancePolicy

    s = system
    graph, cal = BeliefGraphStore(s.log("graph")), CalibrationStore(s.log("cal"))
    idle = IdleContext(ledger=s.ledger, reputability=s.rep, consolidation=s.cons, fidelity=s.fid,
                       checkpoints=s.cp, calibration=cal)
    m = Maintainer(idle=idle, log_for=s.log, belief_graph=graph, audits=s.audits,
                   policy=MaintenancePolicy(idle_every_questions=1, audit_every_cycles=1))

    # Phase U: ingestion writes citations into the Maintainer's own graph,
    # which idle evolution now reads
    seed_load([FixtureSource(url="https://b.example/review", content=b"review", license="cc-by",
                             cites=["https://a.example/paper"]),
               FixtureSource(url="https://c.example/closed", content=b"x", license="all-rights-reserved")],
              s.cas, graph)
    assert idle.belief_graph is graph
    assert idle.citation_map() == {"https://b.example/review": ["https://a.example/paper"]}

    # Phase S: answering brings idle cycles, which feed calibration and audit it
    m.submit_question("p1", "is 17 prime?")
    events = m.run()
    before = s.ledger.get("p1").versions[0]
    assert before["committed"][0]["reputability_factor"] == 0.8  # ungraded source, seed weight
    idle_events = [e for e in events if e["kind"] == "idle"]
    assert idle_events and idle_events[-1]["calibration_drifting"] == []
    assert "Mathematics" in cal.agents()
    assert s.audits.history("calibration")[-1]["drifting"] == []

    # Phase T: a weights-only amendment applies to new answers only...
    s.rep.adopt_standard(dict(s.rep.current_standard()["params"]), "ungraded sources weigh less",
                         grade_weights={"foundational": 1.0, "provisionally_accepted": 0.6,
                                        "contested": 0.3, "rejected": 0.0})
    m.submit_question("p2", "is 29 prime?")
    events = m.run()
    assert s.ledger.get("p2").versions[0]["committed"][0]["reputability_factor"] == 0.6
    # ...never rewrites or reopens an earlier one (not material under 7.2)...
    assert s.ledger.get("p1").versions == [before]
    assert all(e["reopened"] == [] for e in events if e["kind"] == "idle")
    # ...but idle re-examination does see p1's claim as weaker than when made,
    # and 'weakened' still counts as verified for calibration
    last = [e for e in events if e["kind"] == "idle"][-1]
    assert last["status_counts"]["weakened"] >= 1
    report = s.audits.history("calibration")[-1]
    assert report["drifting"] == [] and "Mathematics" in report["agents"]


# ---------------------------------------------------------------------------
# Batch 5 (W-Z), on the API's own wiring (build_app): scheduled ingestion, a
# failing question given up visibly, a grade change reaching every dependent
# answer through the graph, and the review queue -- read back the way the
# client reads it.
# ---------------------------------------------------------------------------

def test_lifecycle_on_the_api_wiring(tmp_path, monkeypatch):
    from athenaeum_body.api import build_app
    from athenaeum_brain import maintenance

    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)
    real_factory = maintenance.make_deliberation_unit

    def factory(question, qid, **kw):   # Phase W: one question's deliberation always breaks
        unit = real_factory(question, qid, **kw)
        if qid == "q-4":
            def broken(state, round_index):
                raise RuntimeError("backend exploded")
            unit.round_handler = broken
        return unit
    monkeypatch.setattr(maintenance, "make_deliberation_unit", factory)

    app = build_app(tmp_path)
    submit, list_questions, get_question, _ = app
    m = app.maintainer
    m.policy.idle_sample_size, m.policy.importance_threshold = 1, 0.0

    # Phase Y: a scheduled ingestion batch fills the graph the idle cycles read
    m.submit_ingestion("seed", [
        {"url": "fixture:paper", "license": "cc-by", "content": "a paper"},
        {"url": "fixture:review", "license": "cc-by", "content": "a review", "cites": ["fixture:paper"]},
        {"url": "https://paywalled.example", "license": "cc-by", "is_paid_or_metered": True},
    ])
    for i, n in enumerate((17, 19, 23), start=1):
        m.submit_question(f"q-{i}", f"is {n} prime?")
    m.submit_question("q-4", "is 29 prime?")
    events = m.run()
    (ingested,) = [e for e in events if e["kind"] == "ingestion"]
    assert ingested["accepted"] == ["fixture:paper", "fixture:review"]
    assert m.idle.citation_map() == {"fixture:review": ["fixture:paper"]}

    # Phase W: the broken question is suspended with its error; the rest answered
    q4 = get_question("q-4")
    assert q4["status"] == "suspended" and "backend exploded" in q4["error"] and q4["question"] == "is 29 prime?"
    assert app.maintenance_status()["failed_units"] == ["q-4"]
    assert [q["status"] for q in list_questions()] == ["completed", "completed", "completed", "suspended"]

    # Phase X: the primality source is downgraded; the next cycle reopens every
    # answer resting on it, though it samples a single claim
    src = "computed:trial_division"
    rep = app.maintainer.idle.reputability
    before = rep.current_grade(src)["grade"]
    while rep.current_grade(src)["grade"] == before:
        rep.record_outcome(src, "source", "challenged")
    for _ in range(5):
        rep.record_outcome(src, "source", "challenged")
    m.submit_question("q-5", "is 31 prime?")
    (cycle,) = [e for e in m.run() if e["kind"] == "idle"]
    assert cycle["reopened"] == ["q-1", "q-2", "q-3"]
    assert all(len(get_question(f"q-{i}")["versions"]) == 2 for i in (1, 2, 3))
    assert get_question("q-1")["versions"][1]["diff"]["cause"]

    # Phase Z: what waits for a reviewer is visible, read-only
    app.maintainer.idle.checkpoints.set_pending("q-5", reason="human input disputes the answer",
                                                triggering_claim_id="c1", submitter_id="alice")
    (pending,) = [c for c in app.checkpoints() if c["status"] == "pending_human_checkpoint"]
    assert pending["kind"] == "question" and pending["ref"] == "q-5"

    # and the synchronous path still works alongside, on the same stores
    assert submit("is 37 prime?")["answer"]["committed"][0]["statement"] == "37 is prime"


# ---------------------------------------------------------------------------
# Batch 6 (AA-AB), over real HTTP: bad input is refused before anything is
# written, good questions flow through the background Maintainer, and what
# lands on disk has the Phase AB shape.
# ---------------------------------------------------------------------------

def test_lifecycle_over_http_with_bounded_checkpoints(tmp_path, monkeypatch):
    import json
    import socket
    import threading
    import time
    from http.server import ThreadingHTTPServer
    from athenaeum_body.api import make_handler

    monkeypatch.setattr(model_backed_reasoning, "ask_model", lambda *a, **k: None)
    data = tmp_path / "data"
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(data))
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def request(method, path, body=b"", length=None):
        head = (f"{method} {path} HTTP/1.1\r\nHost: x\r\nConnection: close\r\n"
                f"Content-Type: application/json\r\nContent-Length: {len(body) if length is None else length}\r\n\r\n")
        with socket.create_connection(server.server_address, timeout=10) as s:
            s.sendall(head.encode() + body)
            raw = b""
            while chunk := s.recv(65536):
                raw += chunk
        head, _, payload = raw.partition(b"\r\n\r\n")
        return int(head.split()[1]), json.loads(payload)

    try:
        # Phase AA: refused before anything is written -- and #32's traversal stays closed
        assert request("POST", "/api/questions", json.dumps({"question": 5}).encode())[0] == 400
        assert request("POST", "/api/questions", b"{}", length=10_000_000)[0] == 413
        assert request("GET", "/../pyproject.toml")[0] == 404
        assert request("GET", "/api/questions")[1] == []

        ids = [request("POST", "/api/questions", json.dumps({"question": q, "async": True}).encode())[1]["id"]
               for q in ("is 17 prime?", "  how should we round 2.5?  ", "is 21 prime?")]
        deadline = time.time() + 60
        while time.time() < deadline:
            questions = request("GET", "/api/questions")[1]
            maintenance = request("GET", "/api/maintenance")[1]
            if (all(q["status"] == "completed" for q in questions) and maintenance["idle_cycles"] >= 1
                    and maintenance["queued_units"] == 0):
                break
            time.sleep(0.1)
        assert [q["id"] for q in questions] == ids and all(q["status"] == "completed" for q in questions)
        assert questions[1]["question"] == "how should we round 2.5?"   # stored trimmed
        assert not any(e["kind"] in ("error", "unit_error", "unit_failed") for e in maintenance["recent_events"])
    finally:
        server.shutdown()

    # Phase AB, read straight from disk: one graph checkpoint per recorded answer,
    # and the Maintainer's state at rest carries nothing but its own registry
    cas = ContentAddressedStore(data / "cas")
    graph_entries = len(CheckpointLog(cas=cas, index_path=data / "belief-graph.txt")._read_index())
    versions = sum(len(q["versions"]) for q in questions)
    assert graph_entries == versions
    saved = CheckpointLog(cas=cas, index_path=data / "maintainer.txt").read_latest()
    assert list(saved["shared_state"]) == ["maintenance"] and saved["units"] == {}
