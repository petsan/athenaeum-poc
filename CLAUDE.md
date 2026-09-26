# Athenaeum

A slow, deep-reasoning, memory-resident, evolving knowledge system split into
**Body** (infrastructure/elasticity) and **Brain** (cognitive logic: six
classical Master Agents plus World News, a seventh, deliberately added
2026-09-22 — see `brain-design.md` Section 2.0b). This repo is a
proof-of-work implementation, not the finished system — read
`docs/progress.md` before doing anything else.

## Guiding principles

These aren't aspirational — every one of them is here because violating it (or nearly violating it) actually cost real time or nearly caused real damage somewhere in this project's history. Re-read this list, not just the hard constraints below, before doing anything nontrivial.

1. **Verify empirically, don't trust — not even your own prior notes.** "Should work" isn't "works." A host that's routinely powered off between sessions means every session starts by checking real state, not recalling it — see "Suggested first move" below. `known-bugs.md` exists specifically because "it mostly worked" was repeatedly mistaken for "it worked as designed" (bug #19: a script that silently corrupted storage config still produced a working backup).
2. **Least privilege by default, expanded only when a specific error demands it.** Every scoped Proxmox token/role here started minimal and grew one privilege at a time, each addition traceable to an actual permission-denied error, never "grant broadly to save a round trip." `Sys.Modify` is deliberately withheld from the automation token even where it would be convenient — the two operations that genuinely need it (identity bootstrap, host-level firewall persistence) are host-only scripts run by a human, on purpose.
3. **Root-cause, not workaround.** Isolate to a minimal reproduction before accepting a fix (the `RLIMIT_CPU`/`unshare --fork` crash was proven with a two-line repro before trusting the finding; the Docker `FORWARD`-chain diagnosis came from watching actual packets on the wire, not guessing). A fix that "seems to work" without a known mechanism is a coincidence until proven otherwise.
4. **Infrastructure and decisions live in the repo (or memory), not just in chat.** Nothing about this project's Proxmox setup, its known bugs, or its open work should depend on any specific conversation surviving — `deployment-playbook.md`, `infra/proxmox/`, `known-bugs.md`, and `docs/progress.md` are the actual source of truth, kept current as work happens, not reconstructed from memory after the fact.
5. **State scope honestly — what's fixed, what's tested, and what's still just reasoned-through.** A fix gets called "closed" only once it's been observed working, not once it's been designed correctly (see the cold-boot checklist item this principle exists to unblock). Backup/DR claims say plainly what they don't cover (no off-host protection here) rather than letting "backups exist" be read as "fully protected."
6. **Confirm before consequential or hard-to-reverse actions**, especially anything touching shared state, security posture, or broad credentials — this repo's own hard constraints below (resource caps, no bare-host deploys, sandbox stays disabled) are instances of this principle, not exceptions to it.
7. **Keep the checkpoint current, every session.** `docs/progress.md` Section 26, `known-bugs.md`, and `CLAUDE.md`'s own "Current status" get updated as part of finishing a task, not as an afterthought — a stale checkpoint is worse than no checkpoint, because it's trusted.

## Read these first, in this order

1. **`docs/progress.md`** — resumable session-history checkpoint. What's
   built, what's tested, what's still open. This is the single most
   important file in the repo for picking up cold — **Section 26 is a
   maintained checklist of actual open work**, not scattered prose; check
   there first for "what's next" instead of re-deriving it from the
   narrative sections above it.
2. **`known-bugs.md`** — twenty real bugs hit during development, each
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

- **Resource cap on this Proxmox host: use at most 80% of total CPU/RAM**
  for any VM or LXC created here (raised from 50% by explicit user
  decision, 2026-09-23 — see `docs/progress.md` §38). Check real specs
  first (`lscpu`, `free -h`, or the Proxmox API) — don't assume the placeholder
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
  (`pytest -q`, currently 257 passed + 1 skipped when no GPU worker is online) and update `docs/progress.md` — don't
  let the checkpoint file go stale.

## Current status (see `docs/progress.md` for full detail)

- Body: storage/checkpoint/scheduler/concurrency/ingestion (now including
  a real `fetch_url()` network fetch, not just `FixtureSource`)/model-
  serving-router/sandbox/distributed worker dispatch (`distributed_worker.py`,
  real cross-process, network-based, proven against an actual killed
  worker process) all implemented and tested against everything this
  sandboxed dev environment could validate.
- Brain: deliberation loop, all **seven** Master Agents now implemented
  as deterministic toy agents (Mathematics, Logic, Engineering, Physics,
  Philosophy, Theology, World News — see brain-design.md Section 2.0b for
  the seventh's rationale), registered via `agents.py`'s `@master_agent`
  decorator so adding another domain needs no edit to `rounds.py`,
  Reputability Engine,
  Model Fitness tracking, knowledge consolidation, domain fidelity
  monitoring, Output Types (Research/Forecast/Recommendation, §5.4), Human
  Input Pipeline and governance (§11), Content Integrity enforcement
  (§12, verified by construction), and Evaluation Infrastructure (§9b —
  ground-truth benchmarks, a 6-case adversarial suite, calibration
  tracking, baselines/ablations, non-compensatory integrity gates) all
  implemented. Engineering's `verify_code()`/`verify_claim()` run real,
  unmocked code in the Body's sandbox — the first Master Agent capability
  that's genuinely real end-to-end, not a stand-in. No real LLM backend
  yet for most reasoning — `model_serving.py` now has a real
  `LlamaCppBackend` (2026-09-23) talking to six live model-lab guests
  (`infra/proxmox/model-lab/`, one CPU-quantized open-weight model each:
  OLMo-2-1B, Qwen2.5-Coder-1.5B, Qwen2.5-1.5B, Phi-3.5-mini, Granite-3.1-2B,
  Mistral-7B-v0.3), proven end-to-end including `evaluation.py`'s
  previously-blocked B1 baseline. **Six of seven Master Agents now have a
  real OLMo 3 fallback** (`model_backed_reasoning.py` — swapped from OLMo
  2 on 2026-09-23, see `docs/progress.md` §38) for when their own
  narrow deterministic computation finds nothing — Logic is the one
  deliberate exception (§2.2: never asserts first-order claims, so no
  fallback path exists for it at all). Deterministic computation still
  always wins when it finds something; the fallback only fires on a
  genuine "nothing to say" gap. `docs/infra-topology.md` (brainbox XSmall/Medium/Large/
  XLarge sizing convention, CPU-RAM-only pending GPU nodes) and
  `docs/brain-session-log.md` (running decision log) added 2026-09-22 —
  see `docs/progress.md` §§27–34 for the full session.
- **A real, elastic GPU worker pool now exists outside the Proxmox host**
  (`src/athenaeum_body/elastic_workers.py`, `elastic_workers.yaml`,
  `infra/elastic-workers/windows-gpu-worker/`, 2026-09-23) — independently
  owned machines (starting with one Windows desktop's RTX 3070 Ti running
  OLMo 3 7B at ~84 tok/s) that can be brought online/offline at will;
  health is checked live on every call, never cached, and both
  `ModelServingLayer.request()` and `model_backed_reasoning.ask_model()`
  fall back to the CPU model-lab guests transparently the instant a
  worker goes dark — see `docs/progress.md` §39 and
  `docs/brain-session-log.md` for the design reasoning.
- **Proxmox is live and access is set up** (see `deployment-playbook.md`,
  `infra/proxmox/`, and the project's own memory notes) — a scoped API
  token, a standing test LXC (VMID 104, `athenaeum-preflight`,
  `192.168.0.150`, privileged+nesting for sandbox testing) with working
  SSH, and real specs confirmed (2× Xeon E5-2690 v2, 40 threads, ~504GB
  RAM, PVE 9.2.20). `scripts/preflight_check.py` has been run for real on
  this host: `RLIMIT_CPU` still crashes `unshare --fork` here (matches the
  original reference environment, wall-clock kill remains primary CPU-time
  enforcement — no code change needed). Fork containment briefly reopened
  on this host (cgroups v2 only, `sandbox.py` had assumed v1) and is now
  fixed and re-verified — see `known-bugs.md` entry 17. **Full `pytest -q`
  suite has been run for real in that LXC — 113/113.**
- A shared, multi-project tools container (VMID 106, `athenaeum-tools`,
  `192.168.0.151`) holds `pve-ops`, a CLI with credentials preinstalled;
  both guests auto-start on host boot (`onboot: 1`); the Docker
  `FORWARD`-chain networking fix and a daily `vzdump` backup (to `local`,
  self-pruned to 7 copies) both persist via systemd units. All of this is
  scripted, not just done once by hand — see `infra/proxmox/README.md`.
  This host is routinely powered OFF between sessions by design (see
  "Suggested first move" below) — none of the above has been drilled
  through an actual full power-cycle yet, only reasoned through; worth
  treating as "should work" until it's been observed working after a
  real cold boot.

## Suggested first move in a new session

Read `docs/progress.md`. Proxmox access is already set up (see
`deployment-playbook.md`); if starting infra work from scratch on a
*different* host or project, follow that playbook rather than
re-deriving the setup.

**This Proxmox host is routinely powered OFF between sessions by design**
(it's a test box, not production — the user turns it off when not
actively working). This is the normal start-of-session state, not an
incident. Before assuming anything about current guest/network state:
1. Check reachability first (`ping 192.168.0.100` or similar) — if it's
   down, that's expected, not a problem to diagnose. Ask the user to
   power it on if Proxmox-related work is actually needed this session.
2. Once it's up, don't trust prior-session memory notes about "what's
   running" at face value — `onboot: 1` means both guests (104, 106)
   *should* autostart, and the Docker `FORWARD`-chain fix *should*
   reapply via its systemd unit, but "should" isn't "verified this
   boot." Run `infra/proxmox/05-verify.sh` (or the equivalent manual
   checks: ping the guest, SSH in, check `systemctl status
   pve-docker-bridge-fix.service`) before building on top of an assumed
   state.
3. This is exactly why `infra/proxmox/` and `deployment-playbook.md`
   exist as the durable record instead of only this session's own
   memory — verify against them, don't just recall them.
