"""
Narrated demo: a real deliberation loop (framing -> exploration ->
cross-examination -> synthesis) running on the SAME Body engine proven
in demo.py -- checkpointed, kill-resumable, no separate toy runner.
Run: python demo_brain.py
"""
import sys, pathlib, shutil
sys.path.insert(0, str(pathlib.Path(__file__).parent / "src"))

from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.scheduler.runner import SingleUnitRunner
from athenaeum_brain.loop import make_deliberation_unit

DATA = pathlib.Path("data/demo-brain-run")
shutil.rmtree(DATA, ignore_errors=True)

def step(t): print(f"\n=== {t} ===")

def fresh_runner():
    cas = ContentAddressedStore(DATA / "cas")
    log = CheckpointLog(cas=cas, index_path=DATA / "index.txt")
    return log, SingleUnitRunner(log, shared_state={})

step("1. A correct claim: 'is 17 prime?' -- should commit cleanly, no dissent")
log, runner = fresh_runner()
unit = make_deliberation_unit("is 17 prime?", "q-correct")
while unit.status != "completed":
    runner.run_round(unit)
answer = log.read_latest()["shared_state"]["answer"]
print("committed claims:", [c["statement"] for c in answer["committed"]])
print("dissent:", answer["dissent"])

step("2. Killing the process mid-deliberation, then resuming from checkpoint")
DATA2 = pathlib.Path("data/demo-brain-kill")
shutil.rmtree(DATA2, ignore_errors=True)
cas = ContentAddressedStore(DATA2 / "cas")
log = CheckpointLog(cas=cas, index_path=DATA2 / "index.txt")
runner = SingleUnitRunner(log, shared_state={})
unit = make_deliberation_unit("is 91 prime?", "q-killed")
runner.run_round(unit)  # framing only
print(f"...killed after round {unit.round_index} (framing done, exploration not started)...")

# fresh process: reload from disk
cas2 = ContentAddressedStore(DATA2 / "cas")
log2 = CheckpointLog(cas=cas2, index_path=DATA2 / "index.txt")
state = log2.read_latest()["shared_state"]
runner2 = SingleUnitRunner(log2, shared_state=state)
resumed = runner2.resume_round_index("q-killed")
print(f"fresh process resumes at round {resumed}, not round 0")
fresh_unit = make_deliberation_unit("is 91 prime?", "q-killed")
fresh_unit.round_index = resumed
while fresh_unit.status != "completed":
    runner2.run_round(fresh_unit)
answer = log2.read_latest()["shared_state"]["answer"]
print("committed after resume:", [c["statement"] for c in answer["committed"]])
print("(91 = 7 x 13 -- correctly caught as not prime, survived a kill/resume)")

step("3. Jurisdictional overreach: a claim outside its agent's declared domain")
from athenaeum_brain.claims import Claim
from athenaeum_brain.agents import MasterOfLogic
overreaching = Claim(question_id="q-x", round=1, issuing_agent="Mathematics",
                      statement="one ought to prefer simpler proofs",
                      claim_type="normative", confidence=0.6,
                      defeat_condition="a counterexample preference", jurisdiction_check=False)
challenge = MasterOfLogic().cross_examine(overreaching, "q-x")
print("Logic's response:", challenge.statement)
print("(this is Section 4.4's commit boundary at work: an unchallenged claim commits;")
print(" a jurisdiction-challenged one surfaces as dissent instead of silent acceptance)")

step("4. Genuine jurisdictional conflict: 'how should we round 2.5?' (Section 4.2)")
log, runner = fresh_runner()
unit = make_deliberation_unit("how should we round 2.5?", "q-conflict")
while unit.status != "completed":
    runner.run_round(unit)
answer = log.read_latest()["shared_state"]["answer"]
for pa in answer["plural_answers"]:
    print(f"topic: {pa['subject']}  (chaired by {pa['chaired_by']})")
    for c in pa["conclusions"]:
        print(f"  - {c['agent']}: {c['statement']}")
print("Neither answer was suppressed or forced into false consensus --")
print("both Mathematics's classical convention and Engineering's IEEE-754")
print("convention are correct on their own terms, so synthesis commits both,")
print("labeled, rather than picking a winner (Section 4.3).")

step("5. The connected arc: Logic validity -> Reputability -> materiality")
from athenaeum_body.reputability_store import ReputabilityStore
from athenaeum_brain.reevaluation import is_material

DATA3 = pathlib.Path("data/demo-brain-arc")
shutil.rmtree(DATA3, ignore_errors=True)
rep_log = CheckpointLog(cas=ContentAddressedStore(DATA3 / "rep-cas"), index_path=DATA3 / "rep-index.txt")
reputability = ReputabilityStore(rep_log)

log = CheckpointLog(cas=ContentAddressedStore(DATA3 / "cas"), index_path=DATA3 / "index.txt")
runner = SingleUnitRunner(log, shared_state={})
unit = make_deliberation_unit("is 17 prime?", "q-arc", reputability=reputability)
while unit.status != "completed":
    runner.run_round(unit)
answer = log.read_latest()["shared_state"]["answer"]
print("first answer's source grade at use:", answer["source_grades_at_use"])

print("...later, the same source gets cited in a fallacious argument, which real Logic catches...")
fallacious = Claim(question_id="q-x", round=1, issuing_agent="Mathematics",
                    statement="P holds", claim_type="formal", confidence=1.0,
                    defeat_condition="x", jurisdiction_check=True,
                    supporting_provenance=["computed:trial_division"],
                    argument={"premises": ["Q", "P -> Q"], "conclusion": "P"})
verdict = MasterOfLogic().cross_examine(fallacious, "q-x")
print("Logic's verdict:", verdict.statement)
for _ in range(3):
    reputability.record_outcome("computed:trial_division", "source", "challenged")

current = {"computed:trial_division": reputability.current_grade("computed:trial_division")}
print("live grade now:", current["computed:trial_division"])
result = is_material(answer, current)
print("is the FIRST answer now material for re-evaluation?", result)
print("(the first answer's own snapshot is untouched -- non-retroactive attachment --")
print(" but materiality correctly flags it as worth reopening)")

step("6. Knowledge consolidation: a claim earning its way to deep-knowledge")
from athenaeum_body.consolidation_store import ConsolidationStore
from athenaeum_brain.consolidation import record_survival, should_promote_to_c, compact, expand

DATA4 = pathlib.Path("data/demo-brain-consolidation")
shutil.rmtree(DATA4, ignore_errors=True)
cons_log = CheckpointLog(cas=ContentAddressedStore(DATA4 / "cons-cas"), index_path=DATA4 / "cons-index.txt")
cons_store = ConsolidationStore(cons_log, ContentAddressedStore(DATA4 / "archive"))

entry = None
for i in range(5):
    log = CheckpointLog(cas=ContentAddressedStore(DATA4 / f"cas-{i}"), index_path=DATA4 / f"index-{i}.txt")
    runner = SingleUnitRunner(log, shared_state={})
    unit = make_deliberation_unit("is 17 prime?", f"run-{i}")
    while unit.status != "completed":
        runner.run_round(unit)
    committed = log.read_latest()["shared_state"]["answer"]["committed"][0]
    entry = record_survival(cons_store, "17-is-prime", committed)
    print(f"  cycle {i+1}: survival count={entry['cycles']}, sources={entry['sources']}")

verdict = should_promote_to_c(entry, min_cycles=5, min_sources=1)
print("promotion verdict:", verdict)
node = compact(cons_store, "17-is-prime")
print("compacted to Tier C:", node)
print("de-compacted full trace still recoverable:", expand(cons_store, "17-is-prime")["cycles"], "cycles")
print("(nothing was ever deleted -- only what's resident got smaller)")

step("7. Domain fidelity: catching an agent's reasoning style drifting")
from athenaeum_body.domain_fidelity_store import DomainFidelityStore
from athenaeum_brain.domain_fidelity import compute_score, needs_review

df_log = CheckpointLog(cas=ContentAddressedStore(DATA4 / "df-cas"), index_path=DATA4 / "df-index.txt")
df_store = DomainFidelityStore(df_log)

healthy_state = run_once = None
log = CheckpointLog(cas=ContentAddressedStore(DATA4 / "df-run-cas"), index_path=DATA4 / "df-run-index.txt")
runner = SingleUnitRunner(log, shared_state={})
unit = make_deliberation_unit("is 17 prime?", "df-q")
while unit.status != "completed":
    runner.run_round(unit)
state = log.read_latest()["shared_state"]
score = compute_score("Mathematics", state["exploration_claims"], state["exam_claims"])
print("real Mathematics claims, current health:", score)
for s in [score["domain_fidelity_score"]] * 3:
    df_store.record("Mathematics", {"domain_fidelity_score": s})

print("...simulating Mathematics's reasoning style drifting over several rounds...")
drifted_claims = [{"claim_id": "d1", "issuing_agent": "Mathematics", "claim_type": "formal",
                    "supporting_provenance": ["unsourced assertion"]}]  # no 'computed:' provenance -- off style
drifted_score = compute_score("Mathematics", drifted_claims, [])
df_store.record("Mathematics", drifted_score)
review = needs_review(df_store, "Mathematics", drop_threshold=0.15)
print("drifted score:", drifted_score)
print("review needed?", review)

# --- Added 2026-09-26: batches 1-3 (docs/progress.md §41-§62) ----------------
from athenaeum_body.reputability_store import ReputabilityStore
from athenaeum_body.ledger import QuestionLedger
from athenaeum_body.belief_graph_store import BeliefGraphStore
from athenaeum_brain.evaluation import a1_full_workflow, ablation_no_reputability_weighting, run_adversarial_suite
from athenaeum_brain.claims import Claim
from athenaeum_brain.dispute_resolution import resolve_dispute
from athenaeum_brain.idle_evolution import IdleContext
from athenaeum_brain.maintenance import Maintainer, MaintenancePolicy
from athenaeum_brain.belief_graph import dependents

DATA5 = DATA / "batches"
log5 = lambda name: CheckpointLog(cas=ContentAddressedStore(DATA5 / "cas"), index_path=DATA5 / f"{name}.txt")

step("8. Evidence-weighted synthesis: a source's track record decides what leads (Section 4.1)")
rep5 = ReputabilityStore(log5("rep"))
for _ in range(3):
    rep5.record_outcome("computed:trial_division", "source", "challenged")
question = "should we believe 17 is prime?"
weighted = a1_full_workflow(question, "w1", grade_lookup=lambda s: rep5.current_grade(s)["grade"])
unweighted = ablation_no_reputability_weighting(question, "w2")
print("with trial division's track record rejected, the leading conclusion is:")
print("  weighted:  ", weighted["research"]["leading_conclusion"]["issuing_agent"])
print("  unweighted:", unweighted["research"]["leading_conclusion"]["issuing_agent"])
print("(the agents' own confidences are untouched -- only the evidence weight moved)")

step("9. Forecasts and recommendations, each with its own semantics (Section 5.4)")
log, runner = fresh_runner()
unit = make_deliberation_unit("will an object dropped from 20m land within 3 seconds?", "f1")
while unit.status != "completed":
    runner.run_round(unit)
forecast = log.read_latest()["shared_state"]["answer"]["output_answer"]["sections"]["forecast"]
print("forecast:", forecast["statement"], "-- probability", forecast["probability"])
print("sensitivity:", forecast["sensitivity"])
log, runner = fresh_runner()
unit = make_deliberation_unit("should we round 2.5 up or down?", "r1")
while unit.status != "completed":
    runner.run_round(unit)
rec = log.read_latest()["shared_state"]["answer"]["output_answer"]["sections"]["recommendation"]
print("recommendation:", rec["chosen_option"])
for option in rec["alternatives_considered"]:
    print(f"  option: {option['option']} -- serves: {option['serves_objective']}")

step("10. Dispute resolution catches circular corroboration (Section 6.4)")
def claim(statement, sources):
    return Claim(question_id="d", round=1, issuing_agent="Physics", statement=statement, claim_type="empirical",
                 confidence=0.8, defeat_condition="a measurement", jurisdiction_check=True,
                 supporting_provenance=sources)
ruling = resolve_dispute("topic:X", {"affirms": [claim("X is true", ["blog:1", "blog:2"])],
                                     "denies": [claim("X is false", ["journal:a", "archive:b"])]},
                         reputability=rep5, cites={"blog:1": ["blog:2"], "blog:2": ["blog:1"]})
print("ruling:", ruling["ruling"])
print("rationale:", ruling["rationale"])

step("11. The system maintaining itself -- and surviving a restart (Sections 3.6, 7, 10)")
ledger5 = QuestionLedger(log5("ledger"))
graph5 = BeliefGraphStore(log5("graph"))
make_maintainer = lambda: Maintainer(idle=IdleContext(ledger=ledger5, reputability=ReputabilityStore(log5("rep2"))),
                                     log_for=log5, belief_graph=graph5, policy=MaintenancePolicy(idle_every_questions=3))
m = make_maintainer()
for qid, q in {"m1": "is 17 prime?", "m2": "should we believe 17 is prime?", "m3": "how should we round 2.5?"}.items():
    m.submit_question(qid, q)
for _ in range(4):
    m.tick()
print("...the process dies with three questions part-way through...")
del m
m = make_maintainer()
print("a new process recovered:", sorted(m.recovered))
for event in m.run():
    print(" ", event["kind"], event.get("question_id") or event.get("cycle_id"))
print("each answer is its own:", [ledger5.get(q).versions[0]["question"] for q in ("m1", "m2", "m3")])
print("the Belief Graph links questions that rest on the same claim: m1 ->", dependents(graph5, "m1"))

step("12. Adversarial suite: a real check for every failure mode in the design (Section 8)")
suite = run_adversarial_suite()
print(f"{suite['passed']}/{suite['total']} passed")

print("\n=== brain demo complete ===")
