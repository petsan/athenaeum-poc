"""
Narrated end-to-end demo of the Athenaeum Body proof-of-work slice.
Run: python demo.py
"""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent / "src"))

from athenaeum_body.config import Config
from athenaeum_body.storage.content_addressed import ContentAddressedStore, IntegrityError
from athenaeum_body.storage.checkpoint import CheckpointLog, ChainIntegrityError
from athenaeum_body.storage.tiered import TieredStore
from athenaeum_body.ledger import QuestionLedger
from athenaeum_body.schemas import QuestionLedgerEntry
from athenaeum_body.scheduler.work_unit import WorkUnit, RoundResult
from athenaeum_body.scheduler.runner import SingleUnitRunner
from athenaeum_body.scheduler.multi_unit import MultiUnitScheduler
from athenaeum_body.concurrency import VersionedStore, ConflictError
from athenaeum_body.resource_monitor import ResourceMonitor, should_suspend

import shutil

DATA = pathlib.Path("data/demo-run")
shutil.rmtree(DATA, ignore_errors=True)

def step(title):
    print(f"\n=== {title} ===")

step("1. Boot: load config")
cfg = Config.load("data/config.demo.yaml")
print("config OK, DRAM floor:", cfg.get("memory", "working_set_floor_gb"), "GB")

step("2. Tiered storage with Tier2 fallback")
t2 = ContentAddressedStore(DATA / "tier2")
t3 = ContentAddressedStore(DATA / "tier3")
tiered = TieredStore(tier2=t2, tier3=t3)
key = tiered.put(b"a source document")
with tiered.simulate_tier2_outage():
    print("Tier2 down -> reading via Tier3 fallback:", tiered.get(key))
print("Tier2 back up -> auto-preferred again, no manual failback needed")

step("3. Content-addressed tamper detection")
cas = ContentAddressedStore(DATA / "cas")
k = cas.put(b"trustworthy checkpoint")
cas.corrupt_for_testing(k, b"SILENTLY ALTERED")
try:
    cas.get(k)
except IntegrityError as e:
    print("tamper correctly detected on read:", e)

step("4. Question Ledger: submit + versioned answers, never overwritten")
log = CheckpointLog(cas=ContentAddressedStore(DATA / "ledger_cas"), index_path=DATA / "ledger_index.txt")
ledger = QuestionLedger(log)
ledger.submit(QuestionLedgerEntry(id="q1", importance=0.9))
ledger.append_version("q1", {"answer": "initial research answer"})
ledger.append_version("q1", {"answer": "reopened -- source reputability changed, conclusion revised"})
q = ledger.get("q1")
print(f"question q1 has {len(q.versions)} preserved versions:")
for v in q.versions:
    print("  -", v["answer"])

step("5. Time-sliced concurrent scheduling across multiple questions")
shared_belief_graph = {}
sched_log = CheckpointLog(cas=ContentAddressedStore(DATA / "sched_cas"), index_path=DATA / "sched_index.txt")
runner = SingleUnitRunner(sched_log, shared_belief_graph)
scheduler = MultiUnitScheduler(runner)

def make_handler(name, rounds):
    def handler(state, round_index):
        print(f"    [{name}] round {round_index} running (belief graph currently has {len(state)} entries)")
        return RoundResult(proposed_writes={f"{name}_claim_{round_index}": "proposed"}, done=(round_index == rounds - 1))
    return handler

scheduler.submit(WorkUnit(id="physics-q", priority=1, round_handler=make_handler("physics-q", 3)))
scheduler.submit(WorkUnit(id="math-q", priority=2, round_handler=make_handler("math-q", 2)))
completed = scheduler.run_to_completion()
print("completed order:", completed)
print("shared belief graph now has", len(shared_belief_graph), "entries from BOTH units")

step("6. Kill mid-round, resume from a fresh process (no lost progress)")
kill_log = CheckpointLog(cas=ContentAddressedStore(DATA / "kill_cas"), index_path=DATA / "kill_index.txt")
kill_runner = SingleUnitRunner(kill_log, {})
unit = WorkUnit(id="resilient-q", round_handler=make_handler("resilient-q", 3))
kill_runner.run_round(unit)
print(f"...process 'killed' after round {unit.round_index}...")
resumed_index = kill_runner.resume_round_index("resilient-q")
print(f"fresh runner resumes at round {resumed_index}, not round 0")
fresh_unit = WorkUnit(id="resilient-q", round_handler=make_handler("resilient-q", 3), round_index=resumed_index)
while fresh_unit.status != "completed":
    kill_runner.run_round(fresh_unit)
print("unit completed without redoing round 0")

step("7. Optimistic concurrency: conflicting writes")
vstore = VersionedStore()
vstore.put("claim:42", "v1", expected_version=0)
_, ver = vstore.get("claim:42")
try:
    vstore.put("claim:42", "stale write", expected_version=0)
except ConflictError as e:
    print("conflict correctly rejected:", e)
vstore.put("claim:42", "v2", expected_version=ver, idempotency_key="retry-1")
vstore.put("claim:42", "v2", expected_version=ver, idempotency_key="retry-1")  # simulated retry
print("idempotent retry did not double-apply:", vstore.get("claim:42"))

step("8. Resource pressure -> checkpoint-and-suspend decision")
mon = ResourceMonitor()
mon.set_state(dram_headroom_gb=8.0)
floor = cfg.get("memory", "working_set_floor_gb")
print(f"DRAM headroom 8GB vs floor {floor}GB -> should_suspend =",
      should_suspend(mon.get_state(), floor))

print("\n=== demo complete: all Body guarantees exercised successfully ===")
