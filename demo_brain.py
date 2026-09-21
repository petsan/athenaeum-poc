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
    print(f"topic: {pa['topic']}  (chaired by {pa['chaired_by']})")
    for c in pa["conclusions"]:
        print(f"  - {c['agent']}: {c['statement']}")
print("Neither answer was suppressed or forced into false consensus --")
print("both Mathematics's classical convention and Engineering's IEEE-754")
print("convention are correct on their own terms, so synthesis commits both,")
print("labeled, rather than picking a winner (Section 4.3).")

print("\n=== brain demo complete ===")
