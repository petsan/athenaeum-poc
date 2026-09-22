# Athenaeum

A slow, deep-reasoning, memory-resident, evolving knowledge system split into
**Body** (infrastructure/elasticity) and **Brain** (cognitive logic: six
classical Master Agents). This repo is a proof-of-work implementation, not
the finished system — read `docs/progress.md` before doing anything else.

## Read these first, in this order

1. **`docs/progress.md`** — resumable session-history checkpoint. What's
   built, what's tested, what's still open, what the last suggested next
   step was. This is the single most important file in the repo for
   picking up cold.
2. **`known-bugs.md`** — sixteen real bugs hit during development, each
   with root cause and generalizable lesson. Read the relevant section
   before touching sandboxing/namespace code, checkpoint/content-addressed
   storage, or any narrated demo script (`demo.py`, `demo_brain.py`).
3. **`docs/body-design.md`** and **`docs/brain-design.md`** — the actual
   design intent. The code in `src/athenaeum_body/` and `src/athenaeum_brain/`
   implements a deliberate subset of these; when in doubt about *why*
   something is shaped a certain way, or what a not-yet-built piece is
   supposed to become, these are the source of truth, not the code.
4. **`security-review-sandbox.md`** — required reading before any change
   to `src/athenaeum_body/sandbox.py`. `execution_sandbox.enabled` stays
   `false` until every scenario in this document passes on the actual
   target environment — re-run `scripts/preflight_check.py` on any new
   host before assuming the existing scorecard carries over.
5. **`acceptance-criteria.md`**, **`schemas.md`**, **`tech-stack.md`** —
   supporting reference: what "done" means for the highest-risk tasks,
   field-level shapes for the core stores, and the committed tech
   decisions (Python, flat-file CAS, SHA-256, YAML config).

## Hard constraints — do not violate these

- **Resource cap on this Proxmox host: use at most 50% of total CPU/RAM**
  for any VM or LXC created here for testing. Check real specs first
  (`lscpu`, `free -h`, or the Proxmox API) — don't assume the placeholder
  numbers in `docs/design.md` (40 cores / 512GB / 10 GPUs) match this
  actual box.
- **Deploy inside a VM or LXC — never directly on the Proxmox host OS.**
- **`execution_sandbox.enabled` stays `false`** in `config.defaults.yaml`
  unless every scenario in `security-review-sandbox.md` has a passing
  automated test on *this specific* host, verified via
  `scripts/preflight_check.py`, not assumed from the reference
  environment's scorecard.
- **No paid or metered external services, ever** — this is a hard
  invariant enforced in `config.py` itself (`disallow_paid_apis`), not
  just a policy.
- Before marking any task "done," run the actual test suite
  (`pytest -q`, currently 109/109) and update `docs/progress.md` — don't
  let the checkpoint file go stale.

## Current status (see `docs/progress.md` for full detail)

- Body: storage/checkpoint/scheduler/concurrency/ingestion/model-serving-
  router/sandbox all implemented and tested against everything this
  sandboxed dev environment could validate.
- Brain: deliberation loop, six-Master-Agent structure (three implemented
  as deterministic toy agents — Mathematics, Logic, Engineering — three
  not yet built: Physics, Philosophy, Theology), Reputability Engine,
  knowledge consolidation, domain fidelity monitoring all implemented.
  No real LLM backend yet — `model_serving.py`'s router/eviction/fallback
  logic is tested against a `MockBackend` only.
- One genuinely open technical question: does `RLIMIT_CPU` work correctly
  under `unshare --fork` on this host's actual kernel? Run
  `scripts/preflight_check.py` to find out — the answer determines a
  small, well-defined change to `sandbox.py` either way.

## Suggested first move in a new session

Read `docs/progress.md`, then run `scripts/preflight_check.py` against
this host before deploying anything else.
