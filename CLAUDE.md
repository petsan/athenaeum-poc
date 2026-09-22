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
2. **`known-bugs.md`** — eighteen real bugs hit during development, each
   with root cause and generalizable lesson. Read the relevant section
   before touching sandboxing/namespace code, checkpoint/content-addressed
   storage, any narrated demo script (`demo.py`, `demo_brain.py`), or any
   Proxmox guest-networking issue (entry 18 — check `iptables -L FORWARD`
   before any other theory).
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
6. **`deployment-playbook.md`** and **`infra/proxmox/`** — required
   reading before any new Proxmox access setup or new guest creation on
   this host. The playbook is the narrative; `infra/proxmox/` is the same
   thing as executable scripts (`README.md` there maps each script to
   the playbook section it implements). Distilled from the first live
   deployment session (see `known-bugs.md` 17–18): scoped token/role/ACL
   creation (including the token+user grant-pairing gotcha and the
   `VM.Audit` omission that silently broke guest listing), the
   standing-guest template, and the mandatory `iptables -L FORWARD` check
   before chasing any other networking theory. A shared, multi-project
   tools container (`athenaeum-tools`, `192.168.0.151`) now holds a CLI
   (`pve-ops`) with credentials preinstalled — prefer
   `ssh root@192.168.0.151 pve-ops -p athenaeum <command>` over re-deriving
   raw API calls for routine operations.

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
  (`pytest -q`, currently 113/113) and update `docs/progress.md` — don't
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
- **Proxmox is live and access is set up** (see `deployment-playbook.md`
  and the project's own memory notes) — a scoped API token, a standing
  test LXC (VMID 104, `athenaeum-preflight`, `192.168.0.150`) with working
  SSH, and real specs confirmed (2× Xeon E5-2690 v2, 40 threads, ~504GB
  RAM, PVE 9.2.20). `scripts/preflight_check.py` has been run for real on
  this host: `RLIMIT_CPU` still crashes `unshare --fork` here (matches the
  original reference environment, wall-clock kill remains primary CPU-time
  enforcement — no code change needed). Fork containment briefly reopened
  on this host (cgroups v2 only, `sandbox.py` had assumed v1) and is now
  fixed and re-verified — see `known-bugs.md` entry 17.

## Suggested first move in a new session

Read `docs/progress.md`. Proxmox access is already set up (see
`deployment-playbook.md`); if starting infra work from scratch on a
*different* host or project, follow that playbook rather than
re-deriving the setup.
