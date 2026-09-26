# Athenaeum — Progress Snapshot

**Purpose of this file:** a resumable checkpoint of where the project stands. Read this first in any new session before touching the design docs or the repo.

**Naming note (2026-09-22):** this repo was renamed from `athenaeum-body-poc` to `athenaeum-poc` — see Section 26. Earlier sections below still say `athenaeum-body-poc` where that was the actual name at the time; those aren't errors, just history. The current name, everywhere it matters going forward, is `athenaeum-poc`.

---

## 1. Where we are, in one paragraph

The system is split into **Body** (infrastructure/elasticity, implementation-agnostic) and **Brain** (cognitive logic: five classical Master Agents plus a sixth, Engineering, for coding competence). Both have full design documents. A proof-of-work code slice of the Body's highest-risk mechanics has been built, tested (19/19 passing), and committed to a git repo. Nothing on the Brain side has been implemented yet — it's design-only.

---

## 2. Documents and their current status

| Document | Status | Covers |
|---|---|---|
| `design.md` | rev 2 | Original full-system document (infra + cognition, unsplit). Superseded in practice by the Body/Brain split below, but still the source for the concurrency/multi-question model and the reputability-arbitration resolution (Section 8.4/9) that both later docs build on. |
| `body-design.md` | rev 3 | Infrastructure only: storage tiers, elasticity, concurrency execution mechanics, ingestion mechanics, **Local Model Serving Layer** (Section 4.5 — vLLM/GPU + llama.cpp/CPU-fallback behind a router; LM Studio repositioned as a pre-admission human workbench, not the runtime), **sandboxed execution capability** (Section 4.6, off by default pending security review). Deliberately implementation-agnostic elsewhere. |
| `brain-design.md` | rev 4 | Cognitive logic: the deliberation loop, synthesis/dispute authority (structured plural answers for jurisdictional conflicts), the Reputability Engine (including Model Fitness tracking, Section 6.7), re-evaluation judgment, knowledge consolidation (deep-knowledge tiering), human input + checkpoint governance, content-integrity rules (ingested/human content is always evidence, never instructions), and the **sixth Master Agent, Engineering** (Section 2.0, 2.2 — coding competence, grounded in the classical constructive tradition: Euclid, Archimedes, Heron, Vitruvius). |
| `estimate.md` | as delivered | Effort estimate for the *Body* task backlog only, in AI-session/review-hour terms rather than person-months. Rough range: 8–14 weeks, bottlenecked by review turnaround. Not yet redone for the Brain backlog. |

**Provenance note carried in both `body-design.md` and `brain-design.md`:** an alternate design package (`athenaeum-complete-project-v1_0.zip`) was reviewed and partially cherry-picked — three output types, proposal-only writes with a single commit boundary, integrity gates, held-out evaluation, governance roles, content-addressed storage, idempotent/versioned writes. Its infrastructure pivot (single VM, no elasticity) and its taxonomy pivot (three roles instead of five/six Master Agents) were explicitly declined. See the "Provenance of This Revision" section at the top of each doc for the full adopt/reject list and rationale.

---

## 3. What's actually built and verified

**Repo:** `athenaeum-body-poc` (delivered as a zip; already `git init`'d with two commits — just needs `git remote add origin ... && git push`).

**113/113 tests passing** (Body storage/scheduling/API/sandbox + Brain deliberation/agents/reputability/consolidation/domain-fidelity; 109 through Section 21, 4 more from Section 22's cgroups v2 fix), verified by actually running the suite before each delivery, not just writing it — most recently as a real run on the actual Proxmox LXC target, not just this dev environment (Section 22).

### Body slice (`src/athenaeum_body/`)
- Content-addressed, tamper-evident storage (`storage/content_addressed.py`) — corrupting a file on disk is detected on read, not silently served.
- Append-only, hash-chained checkpoint log (`storage/checkpoint.py`) — chain verification catches corruption anywhere in history, including in a checkpoint's payload, not just its metadata.
- Tiered storage with Tier2→Tier3 fallback and automatic recovery, no manual failback (`storage/tiered.py`).
- Question Ledger with permanent, append-only version history (`ledger.py`).
- Single-unit runner with kill-safe, round-boundary resume (`scheduler/runner.py`).
- Time-sliced, priority-ordered multi-unit scheduler (`scheduler/multi_unit.py`), including cross-unit-visibility.
- Optimistic concurrency: expected-version conflict detection + idempotency-key deduplication (`concurrency.py`).
- Config loader enforcing hard invariants (`config.py`).
- `demo.py` — narrated end-to-end walkthrough.

**Two real bugs found and fixed during the Body build:** a checkpoint-entry hash computed before a field was attached to it (broke reads), and `verify_chain()` initially only checking metadata, not payload content (a corrupted checkpoint body would have passed as "verified"). Both fixed, both now regression-tested.

### Brain slice (`src/athenaeum_brain/`) — added second
Implements Section 3's four deliberation rounds (framing, exploration, cross-examination, synthesis) and Section 4.4's proposal-only commit boundary, running as a real `round_handler` on the *same* Body engine above — not a separate toy runner, so this proves the Brain/Body interface contract actually works.
- `claims.py` — the normalized claim structure (Section 3.5).
- `agents.py` — two **deterministic** Master Agents (Mathematics, Logic), deliberately not LLM-backed since the Local Model Serving Layer doesn't exist yet. Mathematics does real primality computation; Logic does real jurisdiction-validity checks. This validates deliberation *mechanics* honestly, without pretending to validate reasoning quality.
- `rounds.py` — framing/exploration/cross-examination/synthesis, including jurisdictional-dissent handling (a challenged claim surfaces as dissent rather than being silently committed or silently dropped — Section 4.2/4.3).
- `loop.py` — adapts the four rounds into a Body-compatible `round_handler`, the actual integration point.
- `demo_brain.py` — narrated demo including a deliberation killed mid-run and resumed from checkpoint (verified: 91 correctly caught as not-prime, 7×13, across the kill).

**Three test-authoring bugs were found and fixed while building this slice** (not library bugs — worth distinguishing): a test question missing a routing keyword, a test agent incorrectly cross-examining its own claim (which the design correctly forbids), and a test reading the wrong level of the checkpoint's nested state on resume.

### Jurisdictional conflict → plural answers (Section 4.2) — added third
A third toy agent, `MasterOfEngineering`, was added specifically to exercise a code path the loop had never tested: two agents that each *genuinely and correctly* claim jurisdiction over the same question but reach different conclusions. Scenario: "how should we round 2.5?" — Mathematics computes the classical round-half-up answer (3), Engineering computes the real IEEE-754 round-half-to-even answer (2), both via actual `decimal` module computation, both correct on their own terms. `synthesis_round` now detects this (via a demo-only `topic` field used for conflict-grouping — a real implementation would need a richer mechanism, flagged as unresolved) and commits **both** conclusions as a labeled, Logic-chaired plural answer instead of forcing a single winner — Section 4.3's "never manufacture false consensus" principle, now actually enforced in code rather than just stated in the design doc. 5 new tests, including a full kill/resume of a conflicted deliberation through the real Body engine.

**Explicitly not built yet:** real hardware polling, elastic GPU/distributed-core paths, ingestion pipeline, the Local Model Serving Layer's real backends, the sandboxed execution capability, Physics/Philosophy/Theology/Engineering agents, the Reputability Engine, re-evaluation, knowledge consolidation, human input.

**No license is in the repo** (per instruction — "no copyright for now"). Add one before treating it as anything beyond a private proof of concept.

---

## 4. Immediate open items (from the last architecture review)

Before more of the Body backlog is implemented "for real" (beyond this proof-of-work slice), these were flagged as missing:
1. A committed tech stack (language/storage engine/serialization were left deliberately abstract in the design; the POC picked Python + flat-file CAS for speed of validation, not as a final decision).
2. Field-level schemas for the five Section 5.1 stores (the POC's `schemas.py` is a minimal placeholder, not the final shape).
3. Concrete API contracts / function signatures for round handlers and the resource-state signal.
4. Filled-in defaults for every `<config>` placeholder in `body-design.md` Section 8.
5. Per-task acceptance criteria for the ~47-item Body work breakdown.
6. Dedicated security/threat review for the sandboxed execution capability before it's enabled (it's off by default in config for exactly this reason).

On the Brain side, nothing has been implemented, and several open questions remain unresolved in `brain-design.md` Section 14 (notably: confidence aggregation across plural/multi-type answers, Sybil risk on submitter track records, consolidation threshold tuning, sandbox trust boundary, model-fitness cold-start weighting).

---

## 5. All three queued options — closed out

- **(a) Richer conflict detection:** agents no longer coordinate on a shared topic string — each independently sets `subject`, and synthesis groups via normalized numeric equality (`decimal`), so differently-formatted references to the same value still correctly conflict-group. Still a simplification (general semantic "same question" detection needs (b)), but a real decoupling step.
- **(b) Local Model Serving Layer stub:** `src/athenaeum_body/model_serving.py` — content-addressed model registry (reuses 3.4's tamper detection), a router that never lets callers address a backend directly, VRAM-budget LRU eviction, and transparent GPU-unavailable→CPU-fallback redirection. No real vLLM/llama.cpp integration (no GPU/network here) — a real backend just implements the same `Backend` protocol as `MockBackend`.
- **(c) Hardening docs:** `tech-stack.md`, `schemas.md`, `config.defaults.yaml`, `acceptance-criteria.md`.

## 6. Backend-independent wrap-up — closed out

Extending `acceptance-criteria.md` to the full ~47-task backlog surfaced two real, previously-untested gaps, both now closed:
- **`schemas.py` (Task 2)** had zero tests — added round-trip coverage for all five core schemas.
- **`resource_monitor.py` (Tasks 8-10)** had zero tests — added pure-function coverage plus a genuine end-to-end test that a DRAM-floor breach actually stops a running unit's rounds (not just flags a state) and resumes cleanly once headroom returns.

Also newly implemented: **the ingestion pipeline mechanics (Tasks 14-17, `ingestion.py`)** — license/ToS/paid-access checks, parse/normalize into the Provenance schema, and running as an ordinary scheduled work unit via the same engine as everything else. No real network available here, so `fetch()` takes a `FixtureSource` standing in for a real HTTP fetch — the same substitution pattern already used for `MockBackend` and `simulate_tier2_outage()`.

**16 new tests (56 total), five commits total.**

**What remains is now genuinely blocked on infrastructure this sandbox doesn't have** — not just unscheduled: Tasks 21/22 (GPU-vs-CPU output equivalence — needs real GPU access to compare against) and Task 23 (distributed worker dispatch — needs a second process/host to be meaningful). Everything else backend-independent in the original backlog is implemented and tested.

## 8. Remote access — closed out

Two deliverables, deliberately different in kind:
- **Real path:** `src/athenaeum_body/api.py` — stdlib-only HTTP server (no new dependencies) exposing submit/list/get questions and health, serving `client/index.html` (mobile-responsive) on the same origin. One process, one port; reachable over LAN or via a tunnel/reverse proxy to wherever this is deployed. Known, stated limitation: handles requests synchronously, which only works because the toy loop is fast — needs to become async (submit → poll) once real LLM-backed agents exist.
- **Available right now:** a published mobile page (self-contained, no deployment needed) running the same toy deliberation logic ported to JavaScript, so it's usable on a phone immediately without the real backend.

5 new tests hitting a real running server. One bug found and fixed: `list_questions()` calling `.to_dict()` on already-serialized dicts.

## 9. The recommended trio — closed out

- **Real Logic validity-checking** (`logic_engine.py`): genuine propositional-logic validity via brute-force truth-table enumeration (general, not a fixed fallacy lookup table) — Logic finally does what Section 2.2 always said it should. Wired into `MasterOfLogic.cross_examine` via an optional `Claim.argument` field.
- **Reputability Engine storage mechanics** (`reputability_store.py`, Body-owned): versioned grading, evidence accumulation from cross-examination outcomes, append-only dispute log. Grading *policy* is explicitly labeled a placeholder — real judgment needs a model. Wired into `loop.py`'s synthesis round with correct non-retroactive-attachment sequencing (grade snapshotted before this deliberation's own outcome is recorded), proven across two real deliberations, not just asserted.
- **Re-evaluation materiality** (`reevaluation.py`): pure function per Section 7.2 — newly contested/rejected is always material regardless of magnitude, smaller shifts material only past a threshold, ungraded sources correctly not treated as a change.

`demo_brain.py` step 5 walks the full connected arc: a fallacious argument gets caught by real Logic, downgrades a source's reputability, and materiality correctly flags a *different*, earlier answer as worth reopening — while that earlier answer's own snapshot stays untouched.

13 new tests. Two bugs caught and fixed: a heredoc-escaping error that broke `agents.py`'s syntax outright, and a test's own incorrect expectation about the grading policy's rejection threshold.

**82/82 tests, nine commits total.**

## 11. Items 4, 5, and 6 — closed out

- **(4) Knowledge consolidation** (`consolidation_store.py` Body, `consolidation.py` Brain): Section 10.2's Tier B→C promotion criteria implemented exactly, including the rule the design calls out by name — a claim meeting survival-cycle and independent-source thresholds is still excluded from promotion if its confidence trend is declining, even though it hasn't been overturned. Compaction archives the full trace content-addressed and never deletes it; de-compaction recovers it intact. Proven against 5 real repeated deliberations.
- **(5) Domain fidelity monitoring** (`domain_fidelity_store.py` Body, `domain_fidelity.py` Brain): Section 2.4's two drift signals — jurisdictional overreach rate and reasoning-fingerprint deviation — combined into one tracked score, with a rolling-baseline drop detector that flags review rather than auto-correcting (2.4.3). `demo_brain.py` step 7 shows a real healthy score (1.0) against a simulated drifted one (0.5).
- **(6) Sandbox security review** (`security-review-sandbox.md`, design-only): a threat model with five ranked failure modes, six required properties with rationale, and eight concrete fault-injection scenarios — everything Task 23g needs before implementation, none of it implemented. `execution_sandbox.enabled` should stay `false` until every scenario has a passing automated test.

18 new tests for (4)/(5) — 99 total, twelve commits total. One repeated mistake caught before commit: the same "duplicate final print statement" bug from the reputability session recurred when adding demo steps again — worth knowing it's now a recognized pattern in this file, not a one-off.

## 12. Suggested next step — superseded, see Sections 13-14

## 13. The small task and Task 23g

- **Small task, closed:** `api.py` now wires `ReputabilityStore` into the deliberation path — every answer served over HTTP carries `source_grades_at_use`, matching the in-process demo. 1 new test.
- **Task 23g, started and honestly scored, not finished:** `sandbox.py` is a real OS-level isolation implementation (`unshare` + `chroot` into a freshly-built minimal root) — this environment turned out to have genuine `CAP_SYS_ADMIN`, so it's a real reference implementation, not a stub. Tested against all 8 scenarios in `security-review-sandbox.md`: **6 pass exactly as specified** (network egress, filesystem read/write containment, memory limits, environment scrubbing, scratch freshness). **2 have a documented gap** — CPU-time and fork-count containment both rely on an external wall-clock `timeout -s KILL` rather than the in-process `RLIMIT_CPU`/`RLIMIT_NPROC` originally specified, because `RLIMIT_CPU`'s signal delivery reliably breaks `unshare --fork`'s own signal handling in this specific container environment — a reproducible, empirically-confirmed finding, not a guess, documented in `security-review-sandbox.md` Section 7. **`execution_sandbox.enabled` stays `false`** regardless of these results, exactly as the review's own Section 5 requires — passing tests here is necessary, not sufficient.

Three real bugs caught during empirical testing, each worth remembering: an `env={}` meant to scrub the sandboxed code's environment accidentally wiped `PATH` for the outer orchestration tools too; `chroot` lives in `/usr/sbin`, not `/usr/bin`; Python's `subprocess` reports a SIGKILL-terminated process as returncode `-9`, not the shell's `128+signal` convention (`137`) that the first version of the code assumed.

8 new tests — 108 total, fifteen commits total.

## 15. Continued: closing the fork-containment gap for real

Went back into 23g rather than leaving both gaps as permanent. **Fork containment is now closed** — a real cgroups `pids` controller does work in this environment; the initial wiring had a genuine race condition (process joined the cgroup *after* `Popen()` returned, letting a fast `fork()` loop complete before the limit took effect), fixed via `preexec_fn` and verified stable across repeated runs, not a single lucky pass. Also corrected an inaccurate claim from the prior session: the fork-containment and CPU-time gaps were never the same root cause — `RLIMIT_NPROC`'s failure and `RLIMIT_CPU`'s failure are two separate, independently-confirmed issues.

**CPU-time enforcement remains genuinely open**, and this time for a confirmed reason, not a guess: a minimal reproduction with *no* chroot, no other namespaces — bare `unshare --fork` wrapping a process that hits `RLIMIT_CPU` — crashes every time. This rules out the module's own composition as the cause; it's this container environment's `unshare --fork` implementation itself. The external wall-clock kill remains the real mitigation.

**7 of 8 scenarios now pass exactly as originally specified** (up from 6). `execution_sandbox.enabled` is unchanged — still `false`. 1 new test — 109 total, sixteen commits total.

## 17. Preflight check for real deployment targets

Built `scripts/preflight_check.py` — standalone (stdlib only, no repo import needed) re-validation of every scenario in `security-review-sandbox.md`, including the isolated `RLIMIT_CPU`/`unshare --fork` reproduction that determined this environment's one open finding. Verified working before delivery — ran it here and it reproduces the exact same 7/8-pass pattern. Also delivered standalone outside the repo (`preflight_check.py`) so it can be run immediately, on any machine available now, before Proxmox is even ready — the repo copy is for permanence as the standard re-validation step on every future deployment target.

`security-review-sandbox.md` Section 7.3 (new) makes this explicit: the scorecard is a report on one environment, not a universal claim, and should be re-run rather than assumed to carry over.

1 new file, seventeen commits total. Tests unchanged (109/109 — this is a standalone script, not part of the pytest suite, by design, so it can run with zero dependencies on a bare host).

## 19. Bug catalog

`known-bugs.md` — twenty real bugs from across this project's development (sixteen at the time this section was first written; entries 17–20 added in Sections 22–26), catalogued by category with root cause, fix, and generalizable lesson: shell/OS gotchas (dash vs. bash, `PATH` scrubbing at the wrong layer, `subprocess`'s signal-return convention), namespace-isolation findings (`RLIMIT_NPROC` silent non-enforcement, `RLIMIT_CPU`/`SIGXCPU` crashing `unshare --fork`, a real cgroup-join race condition, a cgroups-v1-only path assumption that silently broke fork containment on a v2-only host), storage correctness (checkpoint hash-before-field-attached, `verify_chain` not checking payload content), one API data-shape bug, four test-authoring mistakes, one corrected documentation claim, one recurring workflow mistake (the duplicate final-print bug, which happened twice), and three Proxmox-host-specific deployment gotchas (Docker's `FORWARD`-chain DROP policy silently breaking bridged guest traffic; a host-only script assuming `jq` was present on the Proxmox host itself when it wasn't; `systemd` `Persistent=true` not catching up a run that was only ever manually triggered, not timer-triggered). Linked from the README, meant to be read before similar work, not just consulted after something breaks.

Eighteen commits total.

## 20. Suggested next step — superseded by Section 21

## 21. Full consolidation into one self-contained package

Everything that had been living as separate chat deliverables is now actually in the repo:
- `CLAUDE.md` — new, read automatically by Claude Code on startup, points at every doc below plus the hard constraints (50% resource cap, no bare-host deployment, sandbox stays disabled until re-validated on the real host).
- `docs/` — `design.md`, `body-design.md` (+ PDF), `brain-design.md` (+ PDF), `estimate.md`, and this file (`progress.md`) — all previously chat-only, now committed.
- `client/standalone-demo.html` — the self-contained JS port of the deliberation loop, runs with zero backend.

Nothing meaningful is external to the repo anymore. One zip is the whole project: design intent, implementation, tests, bug history, and session history together.

Nineteen commits total.

## 22. Proxmox server up — preflight run for real, one gap found and closed, one confirmed unchanged

The Proxmox host (`proxmox01`, 2× Xeon E5-2690 v2 / 40 threads, ~504GB RAM, PVE 9.2.20) is up. Access is scoped, not root: a Privilege-Separation API token (`claude@pve!athenaeum`) confined to a resource pool (`athenaeum-poc`), a dedicated storage (`local-thin-multi`, ~1.09TB dedicated to this project), the node (read-only status), and the SDN zone needed for guest networking — see the project's own memory notes for the exact ACL layout and a host-specific quirk (this PVE version needs matching ACL grants on *both* the token and its underlying user for a Privilege-Separated token to actually resolve any permissions — granting the token alone silently resolves to nothing).

A privileged, nesting-enabled Debian 12 LXC (VMID 104, 2 vCPU/2GB/8GB on `local-thin-multi`) was stood up specifically to run `scripts/preflight_check.py` against a real target deployment host, per Section 17 and `security-review-sandbox.md` Section 7.3's explicit instruction not to assume the reference environment's scorecard carries over.

**Result: it didn't carry over cleanly, and re-validating was the right call.**
- The CPU-time question resolved exactly as the reference environment found: `unshare --fork` still crashes on `SIGXCPU` delivery here too. No code change needed — the external wall-clock `timeout -s KILL` remains correct as primary CPU-time enforcement.
- Fork containment — previously marked "CLOSED" in Section 15 — reopened on this host. This LXC runs cgroups v2 only (no `/sys/fs/cgroup/pids` v1 path at all), and both `sandbox.py` and the preflight script had hardcoded the v1 path. `_cgroup_pids_available()` returned `False`, which silently sent `run_sandboxed()` into the `RLIMIT_NPROC` fallback — already proven unenforced by bug #5. So fork containment was not actually enforced by anything on this class of host, despite the earlier fix.
- Fixed: `sandbox.py` now auto-detects cgroups v1 vs. v2 (`_cgroup_pids_version()`) and creates the pids cgroup under the correct root either way. Verified against this same container's real cgroups v2 setup, not a mock: fork containment now blocks correctly (blocked after 2 forks against a limit of 5). Full writeup: `known-bugs.md` entry 17; scorecard update: `security-review-sandbox.md` Section 7.4.
- Added `tests/test_cgroup_pids_version_*` (pure logic, no root needed) to `tests/test_sandbox.py`.

**Update, same night: root-caused and fixed, then the real full suite was actually run.** The container's total inability to leave the host (blocking both internet egress above AND a separate gap where this Windows workstation couldn't reach the container at all) turned out to be one shared cause: this Proxmox host runs Docker for something unrelated to Athenaeum, and Docker sets the kernel's `FORWARD` chain to default-`DROP`, which — via `bridge-nf-call-iptables` — silently catches all IP traffic bridged through `vmbr0`, while leaving ARP untouched (the diagnostic tell: ARP resolved fine, ICMP/TCP didn't). Fixed with one rule in the chain Docker guarantees it won't overwrite: `iptables -I DOCKER-USER -i vmbr0 -o vmbr0 -j ACCEPT`. Full writeup and a "check this first next time" rule saved to project memory, since three separate red herrings (Proxmox ACLs, per-guest/cluster firewall, DHCP/ARP staleness, physical-LAN theories) were chased before finding this.

With that fixed: direct SSH to the container now works (`ssh -i ~/.ssh/athenaeum_poc root@192.168.0.150`), internet egress works, `apt install python3-pytest python3-yaml` succeeded, the `src/`+`tests/`+`client/`+`pyproject.toml`+`config.defaults.yaml` tree was copied over via `scp`, and **the real `pytest -q` was run as root in the actual target LXC, with genuine `unshare`/`chroot`/cgroups capability — 113/113 passed** (109 original + 4 new `_cgroup_pids_version()` tests). One transient failure on the first run (`test_static_client_served`, 404) was an environment gap, not a code bug — `client/` hadn't been copied over yet; copying it and rerunning gave a clean pass. The cgroups v2 fix is now covered by the full regression suite, not just direct exercise of the mechanism — fully closed, not just "solid."

`execution_sandbox.enabled` stays `false`, unchanged — the CPU-time gap alone (mitigated by wall-clock kill) is enough reason on its own, independent of the fork-containment fix above.

Twenty commits total.

## 23. Deployment playbook, then validated by rebuilding VMID 104 clean

Wrote `deployment-playbook.md` — everything from Section 22 distilled into a single mechanical procedure (one `.proxmox.env` config template, one SSH key) reusable for standing up scoped Proxmox access for *any* future project on this host, not just Athenaeum. `CLAUDE.md` was also stale relative to Sections 22–23 (still said sixteen bugs, 109/109 tests, `RLIMIT_CPU` as an open question) — synced.

Immediately validated the playbook for real: destroyed VMID 104 and rebuilt it from scratch via the exact Section 6 procedure. One mistake surfaced and corrected in the process — `pct set 104 -unprivileged 0` on an already-created guest fails (`unable to modify read-only option`), even though that exact constraint was already written into the playbook minutes earlier; the correct sequence is destroy + `pct create ... -unprivileged 0 ...` from scratch. Also newly documented: a rebuilt guest gets fresh SSH host keys even reusing the same IP, which trips the client's "host identification changed" warning — expected, not an incident, clear with `ssh-keygen -R`. Post-rebuild: SSH verified working, cgroups v2 `pids` controller present, filesystem genuinely clean. Both new findings folded into `deployment-playbook.md` itself, at the point in the procedure where they'd actually be hit.

Twenty-two commits total.

## 24. Infrastructure as code, a shared multi-project tools container, and a simple backup

Per explicit request ("in case I need to rebuild any of it, and you're unavailable"), turned the playbook's narrative procedure into actual scripts: `infra/proxmox/` — `00-bootstrap-identity.sh`/`04-persist-docker-forward-fix.sh`/`06-setup-backups.sh` are host-only (need `root@pam`/root, by design — that's a real security boundary, not an oversight); `01-`/`02-`/`03-`/`05-` are API-driven and runnable from anywhere. `rebuild-all.sh` chains the non-host-only steps. `infra/proxmox/README.md` maps every script to the playbook section it implements.

Also stood up VMID 106 (`athenaeum-tools`, `192.168.0.151`): a persistent, unprivileged LXC holding `pve-ops`, a **multi-project** CLI (`-p <project>` selects per-project credentials from `/opt/athenaeum-tools/keys/<project>.env`) — built this way specifically so future, unrelated projects can reuse this one box instead of each re-deriving Proxmox API access from scratch. Plain `curl -k` on Linux, no more PowerShell `ICertificatePolicy` cert-bypass boilerplate for routine operations. `athenaeum-ops` kept as a symlink. Both guests now have `onboot: 1`.

Found and fixed a real gap while dogfooding the CLI: the `ClaudeAgent` role never included `VM.Audit`, so bulk guest-listing (`/nodes/{node}/lxc`, `/qemu`) silently returned an empty array with no error, while everything operating on a *known* vmid worked fine regardless. Added to the role and to `00-bootstrap-identity.sh` for any future project from the start.

**Simplest viable backup added**: `06-setup-backups.sh` installs a systemd service+timer running a daily `vzdump` snapshot of both guests to `local` (physically separate from `local-thin-multi`, where the live disks are), self-pruned to the last 7 copies. Explicitly scoped in the docs as protecting against a deleted/corrupted guest on an otherwise-healthy host, NOT against losing the physical host itself (backups live on the same machine) — stated plainly rather than left implicit. Confirmed working: real 154M/201M archives, service exited `0/SUCCESS`.

Caught one real bug while setting it up, with an actual (not hypothetical) consequence: `06-setup-backups.sh`'s one `jq` usage assumed `jq` would be present on the Proxmox host itself — it wasn't (only ever installed on the guests). The broken pipe made a `$()` substitution empty, and the resulting `pvesh set /storage/local --content ,backup` **silently replaced** `local`'s content types, dropping `vztmpl`/`iso` and leaving only `backup` — confirmed via `pvesh get /storage/local` afterward. The rest of the script still completed and produced a working backup, which nearly hid the corruption behind an apparently-successful run. No actual data was lost (the two already-downloaded templates were still on disk, just unlisted); restored with `pvesh set /storage/local --content iso,vztmpl,backup`, confirmed templates reappeared immediately. Rewrote the script's `jq` usage as `grep`/`cut` on raw JSON (zero host dependencies) and added a hard-fail guard for an empty extraction instead of silently proceeding. `known-bugs.md` entry 19 — two lessons, not one: "mostly worked" isn't "worked as designed," and a config value built by substituting another command's output needs to be validated before it's used to *replace* something, since a silently-empty substitution can cause quiet data loss rather than a loud error.

**Reframed a premise, not just added a feature**: the user turns this host off between coding sessions deliberately (test box, not production) — this is the *normal* start of every session, not a rare accidental-outage edge case. `onboot: 1`, the Docker-fix systemd unit, and the backup timer's `Persistent=true` (which catches up a missed 03:30 run shortly after the host next boots) all needed to be re-examined against that reality rather than "survives an occasional reboot." `CLAUDE.md`'s "suggested first move" now says explicitly: check host reachability first, and once up, verify current state rather than trust prior-session memory notes at face value.

Confirmed separately: `docker.service` is `enabled` on this host, so the whole Docker-fix persistence strategy actually has something to attach to on every boot — the one assumption that, if wrong, would have silently broken everything else in this session.

`known-bugs.md` now twenty entries. Twenty-five commits total.

## 25. Pushed to GitHub, then renamed

Set up `gh` (GitHub CLI, installed via `winget` since it wasn't present), authenticated via device-code flow, and pushed this repo to a **private** GitHub repo — confirmed private via the API response (`visibility: PRIVATE`), and confirmed `.proxmox.env` (the live API token secret) never made it into the pushed tree, matching what `.gitignore` had been enforcing locally all along. Needed a second device-auth pass to add the `workflow` OAuth scope, since the default scope set can't push `.github/workflows/ci.yml`.

Then renamed: `athenaeum-body-poc` → `athenaeum-poc`, both on GitHub and the local folder. Reason: this repo has always contained both Body (`src/athenaeum_body/`) and Brain (`src/athenaeum_brain/`) code — "body" in the name was actively misleading about what the repo covers, not just imprecise. Renamed via the GitHub API directly (`gh api -X PATCH .../name=athenaeum-poc`) rather than the interactive `gh repo rename` flow, updated the local `origin` remote URL, and fixed the two files that referenced the old name as current-state fact (`tech-stack.md`, the systemd unit's own comment) — left `docs/progress.md`'s own historical mentions of the old name alone, since those are an accurate record of what it was actually called at the time, not something to retroactively rewrite.

Local Windows folder also renamed to match (`C:\Users\petsa\Downloads\Claude\athenaeum-poc`) — done carefully from outside the directory itself, since Windows won't let a process rename a directory it's currently working inside.

Note: the copy of `pve-docker-bridge-fix.service` already installed on the Proxmox host (`/etc/systemd/system/`) still has the old name in its comment — cosmetic only (doesn't affect function), not worth a host round-trip just for that; will naturally get the current name next time `04-persist-docker-forward-fix.sh` is re-run for any real reason.

Repo is now `https://github.com/petsan/athenaeum-poc` (private). Twenty-six commits total (pre-rename).

## 26. What's next — maintained checklist, not scattered prose

Earlier sections each ended with their own "suggested next step," repeatedly superseded by whatever came next. This section replaces that pattern: **keep this list current going forward** — check items off (strike through, don't delete, so the history of what was actually open stays visible) and add new ones here rather than starting a new scattered note at the bottom of a new section.

### Infra (Proxmox) — real, not yet drilled
- [x] **Verify the whole stack survives an actual cold boot.** Done for real on 2026-09-22: `shutdown now` on the host, confirmed fully unreachable, powered back on, then verified — `onboot: 1` started both guests (uptime matched boot time), `pve-docker-bridge-fix.service` ran automatically at boot (`0/SUCCESS`, confirmed via `systemctl status` directly, not just inferred), and guest-to-internet reachability worked immediately (104 pinged `8.8.8.8` cleanly right after boot).
- [ ] **Backup timer's `Persistent=true` did NOT catch up on this cold boot — real gap, not a false alarm.** After the reboot, `pve-athenaeum-backup.timer` was `active (waiting)` for the next normal `03:30` slot, 2+ hours out, rather than firing immediately. Root cause: the very first backup was triggered manually (`systemctl start pve-athenaeum-backup.service`) during setup, bypassing the *timer* — so the timer itself has never recorded a trigger of its own, and `Persistent=true` only catches up a run the timer previously missed, not "any backup ever." Given this host is routinely powered off well before 3:30am, **the backup may rarely or never actually fire** under real usage as currently configured — the opposite of "self-updating." **Proposed fix, not yet applied:** add `OnBootSec=10min` alongside the existing `OnCalendar` in `pve-athenaeum-backup.timer`, so it also reliably fires shortly after every boot. Decide and apply next session.
- [ ] Confirm the `local-thin-multi`/`local` storage content-type config is still intact after any future script touches it — `known-bugs.md` #19 was a real, if fixed, near-miss.
- [ ] Off-host/off-site backup remains explicitly not built (`infra/proxmox/README.md`'s stated scope boundary) — only build this if actually needed, don't assume it's implied by "backups exist now."
- [ ] **Decide: auto-update mechanism for deployed code, and where it actually runs.** Raised 2026-09-22, deliberately deferred rather than decided under time pressure. Two real options, architecturally different, needs a real decision together: (a) set up auto `git pull` on LXC guest 104 (`athenaeum-preflight`) from the new private GitHub repo (`github.com/petsan/athenaeum-poc`), replacing the current manual `scp` workflow — no Docker involved; or (b) build and run Athenaeum inside an actual Docker container on the host's *existing*, otherwise-unrelated Docker daemon, with a watchtower-style auto pull+restart — a genuinely new piece of infrastructure sharing that daemon with its other workloads. Neither has been started.

### Body/Brain — real design work, not infra
- [x] **Physics, Philosophy, Theology Master Agents.** Deterministic toy agents added 2026-09-22, matching the existing Mathematics/Logic/Engineering pattern (real, checkable computation, not hand-waved text) — see Section 27 and `docs/brain-session-log.md` for the specific design choices and one real emergent interaction found while testing.
- [x] **Infra topology for brainboxes** — `docs/infra-topology.md` (XSmall/Medium/Large/XLarge tiers, shared-memory architecture) plus the `03-create-project-guest.sh` `GUEST_TIER` flag, both done 2026-09-22. The model-lab guests (Section 35) deliberately used custom `GUEST_CORES`/`GUEST_MEM_MB` overrides instead, since that shape didn't fit any formal tier — see Section 35's own note on why a fifth tier wasn't added speculatively.
- [x] Output Types (`brain-design.md` §5.4, Work Breakdown Phase 7) — `src/athenaeum_brain/output_types.py`: classification (`classify_output_type`) wired into `framing_round`; Research Answer builder wired into `loop.py`'s synthesis round; Forecast and Recommendation builders complete and tested standalone (not yet wired to a producing agent — none exists yet that emits the needed structure); non-collapsing multi-type composition (`compose_answer`). Forecast-resolution-always-material wired into `reevaluation.forecast_is_material`. 13 new tests. See Section 28 and `docs/brain-session-log.md`.
- [x] Human input workflow (`brain-design.md` Section 11, Phase 13) — `human_checkpoint_store.py` (Body) + `human_input.py` (Brain): submission structure with required justification/declared_scope (11.1), low-weight-not-rejected handling of unjustified input, submitter track record reusing `ReputabilityStore`'s existing generic `subject_type` (11.3, no new mechanism needed), `human_input_is_material` (11.5), `pending_human_checkpoint`→`current` lifecycle with Reviewer-role gating and conflict-of-interest enforcement (11.7). 18 new tests. See Section 29 and `docs/brain-session-log.md`. One real, honestly-scoped limitation: today's toy agents' cross-examine methods only pattern-match their own claim formats, so a human_input claim's free-text statement currently survives cross-examination unchallenged by default, not because it was actually evaluated on its merits — flagged, not hidden.
- [x] Engineering agent real specify→implement→execute→verify loop + Model Fitness (Phase 15) — `MasterOfEngineering.verify_code()`/`verify_claim()` (real, unmocked `sandbox.run_sandboxed()` calls, confidence tied directly to actual exit code/stdout); `serving_model` field added to `Claim` and threaded through Engineering's claims; `model_fitness_store.py` (Body) + `model_fitness.py` (Brain) with cold-start Open Question 10 resolved via Laplace smoothing (0.5 at zero evidence). 15 new tests, including real sandbox executions of known-correct and known-buggy code. See Section 30 and `docs/brain-session-log.md`.
- [x] Content Integrity enforcement (Phase 14, §12) — `content_integrity.py` (Brain): §12.1's core rule verified *by construction* via a structural scan (no `eval`/`exec` in any Brain claim-handling module) plus an end-to-end adversarial-submission test through the real pipeline; §12.3's advisory instruction-like-content heuristic, wired to contribute exactly one ordinary reputability "challenged" outcome per detection (Open Question 8's resolution: same weight as any other cross-examination challenge, never an automatic gate). 7 new tests. See Section 31 and `docs/brain-session-log.md`.
- [x] Evaluation Infrastructure (Phase 9b) — `calibration_store.py` (Body) + `evaluation.py` (Brain): `run_ground_truth_benchmark()` (§9.1, real loop runs); `run_adversarial_suite()` covering 6 of §8's 16 named failure modes with real, checkable mechanisms (rest genuinely blocked on a real model backend, stated explicitly, not silently under-covered); `calibration_report()` (§9.3); `b0_retrieval_only()`/`a1_full_workflow()`/two required ablations (§9.7, B1 explicitly flagged blocked); `check_integrity_gates()` (§9.8, pass/fail non-compensatory); §9.9 contamination isolation verified by construction (ingestion.py has no import of evaluation.py). One real, non-obvious finding: the "remove reputability weighting" ablation is currently indistinguishable from A1, because `synthesis_round` doesn't yet numerically reweight confidence by reputability grade — a genuine gap between §6.7's design intent and today's wiring, logged rather than glossed over. 16 new tests. See Section 32 and `docs/brain-session-log.md`.
- [x] **Ingestion pipeline's real network fetch** — `fetch_url()` added to `ingestion.py`: a real stdlib-only (`urllib`) HTTP GET plus a real robots.txt check, no new dependency, never sends credentials/API keys (Section 6.6). `FixtureSource` kept as the shared normalized shape both a real fetch and a hand-authored test fixture produce, rather than renamed. `license`/`is_paid_or_metered` remain caller-supplied, since neither is mechanically derivable from an HTTP response. 6 new tests, including real live fetches from LXC 104 and a real DNS-failure case (`.invalid` TLD, RFC 2606). See Section 33 and `docs/brain-session-log.md`.
- [x] **Task 23 (distributed worker dispatch)** — `distributed_worker.py` (Body, deliberately Brain-agnostic: no import of `athenaeum_brain` anywhere, matching `loop.py`'s own layering): `serve_worker()`/`remote_round_handler()`, stdlib-only HTTP, a drop-in `RoundHandler` so `SingleUnitRunner`/the scheduler need zero changes to run a distributed unit. Tested against a genuinely separate OS process (not a thread), with a real `terminate()` mid-deliberation proving Section 4.2's "loss of a worker mid-task simply requeues the unit" for real, not simulated. 4 new tests. See Section 34 and `docs/brain-session-log.md`.
- [ ] Tasks 21/22 (GPU-vs-CPU output equivalence) remain genuinely blocked — this host has no GPU (confirmed via the node status API, Section 22).
- [x] **Local Model Serving Layer now has a real backend.** `LlamaCppBackend` (`model_serving.py`) talks to the six live model-lab guests over HTTP (stdlib `urllib`); `model_lab_registry.py` wires all six into a `ModelRegistry`. `ModelServingLayer.request()` proven for real (CPU fallback path, `gpu_available=False` — the honest current topology, no GPU pool exists). `evaluation.py`'s B1 baseline (§9.7) is real for the first time — `b1_single_agent_baseline()` — no longer `B1_UNAVAILABLE`. No Master Agent is wired to use this for its own claims yet (still deterministic toy logic) — that's the next real step, not done here. See Section 36.
- [x] **Evidence-weighted synthesis (§4.1).** `synthesis_round` now sets `reputability_factor`/`weighted_confidence` on committed claims from grades at time of use; the Research Answer's leading conclusion follows that weight; the §9.7 "no reputability weighting" ablation is real and provably distinct from A1. See Section 41.

**Remaining Brain gaps (audited 2026-09-25 against `brain-design.md` §13's work breakdown — none are literal stubs, all are specified-but-unbuilt):**
- [x] ~~Dispute resolution procedure (§6.4, task 9) — including Logic's circular-corroboration/independence check. Only `ReputabilityStore.log_dispute()` storage exists.~~ Done 2026-09-25, `dispute_resolution.py` — see Section 42.
- [x] ~~Reputability standard versioning (§6.5, task 10).~~ Done 2026-09-26 — see Section 43.
- [x] ~~Forecast and Recommendation builders wired into `loop.py` (§5.4, tasks 13–14) — builders exist, no producer.~~ Done 2026-09-26 (Phase A) — see Section 44.
- [x] ~~Importance rating (§7.1, task 16) and reopen-with-diff (§7.3, task 18).~~ Done 2026-09-26 (Phase B) — see Section 45.
- [x] ~~Idle-evolution rounds (§3.6).~~ Done 2026-09-26 (Phase C) — see Section 46.
- [x] ~~Cross-agent verification routing, e.g. Mathematics → Engineering sandbox (task 44).~~ Done 2026-09-26 (Phase D) — see Section 47. Off in normal operation because `execution_sandbox.enabled` is false.
- [x] ~~Model admission gate (§6.7, task 47), and applying Model Fitness weight at synthesis.~~ Done 2026-09-26 (Phase E) — see Section 48.
- [x] ~~**Owner action: OLMo 3 7B guest (VMID 116) is swap-thrashing**~~ — **fixed 2026-09-26** once guest changes were permitted: the growth was `llama-server`'s 8 GiB-default RAM prompt cache; `--cache-ram 512` now on all seven model-lab guests and in the setup template (known-bugs.md #24, #27; Section 59).
- [x] ~~Domain Fidelity re-grounding and escalation-to-checkpoint (§2.4.3, task 30).~~ Done 2026-09-26 (Phase F) — see Section 49.
- [x] ~~Re-evaluation and consolidation audit sampling (§9.4–9.5, tasks 22–23).~~ Done 2026-09-26 (Phase G) — see Section 50.
- [x] ~~Adversarial suite: 7 of §8's 15 failure modes covered (task 20; `circular_corroboration` added in Section 42); several remaining ones depend on the items above.~~ **15 of 15** as of 2026-09-26 (Phase H) — see Section 51.

### Next-session plan (written 2026-09-25, end of session)

**State at hand-off:** `master` = `657af14`, pushed, clean. LXC 104's `/root/athenaeum-poc` matches it for `src/`, `tests/`, `docs/` (synced by tar; the LICENSE/README changes don't affect tests). Last full run: **273 passed, 1 skipped** (skip = real-GPU-worker test; the Windows worker was offline). Milestones done this session: evidence-weighted synthesis (§41), dispute resolution + independence check (§42). Also added a proprietary source-available `LICENSE` (Piorun, Inc.; examine-but-don't-take, companies/employers explicitly welcome to download and review; no AI/ML use) and a matching README note — any future README/LICENSE wording change needs the owner's explicit approval, don't "tidy" it.

**Working method the owner asked for — keep it:** one small milestone at a time → new tests → full suite on LXC 104 → update this file (check off + new numbered Section) + `docs/brain-session-log.md` (design Q&A) + CLAUDE.md test count → check in with the owner → commit/push only once approved. Owner calls the default branch "main"; it is actually `master`.

**Mechanics, so nothing is re-derived:**
- Windows dev machine has no Python. Tests run on LXC 104 (`ssh -i ~/.ssh/athenaeum_poc root@192.168.0.150`), which has no git. Sync: `tar cf - src tests docs *.md *.yaml *.py pyproject.toml | ssh … 'cd /root/athenaeum-poc && tar xf -'`, then clear `__pycache__`. Before the first sync of a session, confirm the guest copy matches `origin/master` (compare sha256 of `src/` and `tests/`).
- Windows clone must be `core.autocrlf=false` (LF) or every file hashes differently from the guest's copy.
- Commit identity: repo-local `Athenaeum POC <poc@athenaeum.local>`, matching all history. Scan each staged diff for secrets before pushing (none found so far, in the tree or the history).
- Full suite takes ~4.5 min. Tests that touch the model-backed fallback should stub `model_backed_reasoning.ask_model` if they assert exact claim sets (see `test_evidence_weighted_synthesis.py`), otherwise a live OLMo worker can add claims.
- Host is routinely powered off: `ping 192.168.0.100` first; if down, ask the owner to power it on.

**Ordered milestones (each is one check-in):**
1. ~~**§6.5 Reputability standard versioning**~~ — **done 2026-09-26, Section 43** (next up is item 2). Move `_grade_from_tally` into a versioned policy registry (v0 = today's rule, labelled as the seed standard of §6.1). Every `grade_versions` entry records the `standard_version` that produced it. `ReputabilityStore.adopt_standard(policy, rationale)` makes version N+1 govern new decisions only — never rewrites old grade entries. Extend `reevaluation.is_material` with §7.2's fourth trigger (a change of standard version that would alter the grade of a source the answer relied on). Tests: old grades keep their version tag, new outcomes use the new version, and materiality fires only when the re-grade actually differs.
2. ~~**Forecast/Recommendation producers (§5.4, tasks 13–14).**~~ — **done 2026-09-26 as Phase A, Section 44.** The builders exist in `output_types.py`; nothing produces their inputs. Add an optional structured payload on `Claim` (e.g. `forecast: {statement, probability, resolution_criterion, resolution_date}`) and have `loop.py` build the section when the frame asks for it *and* a committed claim carries one — otherwise the section explicitly says no agent produced one (honest, not silently omitted). Find one agent that can produce a genuine forecast deterministically before reaching for the model fallback.
3. ~~**§7.1 importance rating + §7.3 reopen-with-diff.**~~ — **done 2026-09-26 as Phase B, Section 45.** Importance from framing (domains routed, output types) plus dependency count. Reopen = re-run the loop with the prior answer as context, `QuestionLedger.append_version`, and an explicit diff (committed claims added/removed, leading-conclusion change, weighted-confidence deltas, cause). Uses `consolidation.expand` first if the prior answer was compacted.
4. ~~**§3.6 Idle-evolution round.**~~ — **done 2026-09-26 as Phase C, Section 46.** A work-unit type that samples existing committed claims and re-runs cross-examination against current grades; is the natural caller for `resolve_dispute` (§42), consolidation `record_survival`, and `domain_fidelity.needs_review`. Feeds materiality from item 3.
5. ~~**Task 44 cross-agent verification routing.**~~ — **done 2026-09-26 as Phase D, Section 47.** Mathematics's formalizable claims (primality) routed to `MasterOfEngineering.verify_claim` so a sandbox run corroborates/challenges them. Sandbox stays behind its existing config gate.
6. ~~**§6.7 model admission gate + fitness at synthesis.**~~ — **done 2026-09-26 as Phase E, Section 48.** Provisional status for a newly admitted model; apply `model_fitness.apply_fitness_to_confidence` alongside `reputability_factor` for claims with `serving_model` (keep raw `confidence` untouched, same as §41).
7. ~~**§2.4.3 Domain Fidelity re-grounding/escalation**~~ — **done 2026-09-26 as Phase F, Section 49.** On `needs_review`, re-ground against the agent's baseline cases; escalate to a human checkpoint after repeated failure (reuse `human_checkpoint_store`).
8. ~~**§9.4–9.5 audit sampling** for re-evaluation and consolidation fidelity.~~ — **done 2026-09-26 as Phase G, Section 50.**
9. ~~**Remaining adversarial cases**~~ — **done 2026-09-26 as Phase H, Section 51 (15/15).** Added as their mechanisms land: retroactive history rewriting (after 1), stale framing (after 3/4), silent authority creep (Logic never issues a first-order claim; checkable now), unfalsifiable-claims-as-physics, overconfidence drift (calibration store), lossy compaction, silent style drift, unjustified human-input skew, uncommitted canonical writes (checkable now). Aim to add the two "checkable now" ones opportunistically in milestone 1's session if it's small.

**Infra items above in this section are untouched this session** (backup timer `OnBootSec` decision, auto-update mechanism) — still the owner's call, not Brain work.

### Approved autonomous batch (2026-09-26)

The owner approved this batch to run unattended, in whatever order works best, **committing and pushing to `master` at the end of every phase**. When the batch is done: run an end-to-end test, plan the next batch, and keep going. Keep this file, `known-bugs.md`, and all other docs current as each phase lands.

| Phase | Scope | Status |
|---|---|---|
| A | Forecast/Recommendation producers (§5.4) — plan item 2 | **done** — §44 |
| B | Importance rating + reopen-with-diff (§7.1, §7.3) — plan item 3 | **done** — §45 |
| C | Idle-evolution round (§3.6) — plan item 4; standard amendments only *proposed* to the human checkpoint, never auto-adopted | **done** — §46 |
| D | Cross-agent verification routing (task 44) — plan item 5; respects the existing sandbox gate | **done** — §47 |
| E | Model admission gate + fitness weighting at synthesis (§6.7) — plan item 6 | **done** — §48 (live-OLMo tests unverifiable this run, see §48) |
| F | Domain Fidelity re-grounding/escalation (§2.4.3) — plan item 7 | **done** — §49 (offline-verified) |
| G | Audit sampling (§9.4–9.5) — plan item 8 | **done** — §50 (offline-verified) |
| H | Adversarial suite toward 15/15 (§8, §9.2) — plan item 9 | **done** — §51, 15/15 (offline-verified) |
| I | *(optional)* README body refresh — **draft only; never pushed without the owner's review.** The top notice and LICENSE are never touched. | **drafted, awaiting owner review** — `README.draft.md` in the owner's local clone (`C:\Users\petsa\athenaeum-poc`), deliberately *not* committed (listed in `.git/info/exclude`). It replaces the chronological changelog body (which still said "19 tests", the Brain was unbuilt, and a 50% resource cap) with what the system is, how a question is answered, what's built, how it's verified, running it, layout, and further reading; the top notice is copied verbatim. Every command and figure in it was checked on 2026-09-26 (demo exit 0, API `/api/health` ok, 417 tests collected). To adopt: review, then replace `README.md`'s body with it. |

**Stop-and-wait conditions (from the approval):** a failing test whose root cause is unclear; the design is silent on a hard-to-reverse choice (e.g. persisted-state shape); an existing test's *meaning* (not just shape) would have to change; the Proxmox host goes down. **Never:** alter LICENSE/README notice, create/modify/destroy Proxmox guests (lifted by the owner 2026-09-26, §58), enable `execution_sandbox`, touch credentials or paid services, or write tests that require the GPU worker.

**Batch 1 (A–I) complete 2026-09-26**, end-to-end test passing (Section 52).

### Batch 2 (self-planned 2026-09-26, per the owner's "plan the next batch and continue")

Same rules and stop conditions as batch 1. Ordered so each phase builds on the last.

| Phase | Scope | Status |
|---|---|---|
| J | **Fingerprints for Physics, Philosophy, Theology** (§2.4.1 names them: Physics — explicit defeat condition present; Philosophy — assumption/premise surfacing; Theology — `traditional` typing attached). Closes the §49 gap where those agents' drift could be flagged but never confirmed. | **done** — §53 |
| K | **Mathematics bare-integer parsing** — primality only for integers the question actually asks about (same bug class as known-bugs #21); moves the open limitation into a fixed bug. | **done** — §54, known-bugs #25 |
| L | **Belief Graph store** (schemas.md already specifies node/edge shapes): answers → claims → sources as real edges, written by the loop. `count_dependents` switches from its shared-claim proxy to real edges, and §7.2's second trigger ("a newly corroborated/challenged claim the framing round would route to the same question") becomes implementable. | **done** — §55 |
| M | **Maintenance cadence** — a driver that runs idle cycles as low-priority units on the existing `MultiUnitScheduler` alongside questions, audits every N cycles, feeds re-evaluation, and applies approved amendments; the system then evolves without a human calling each function. | **done** — §56 (+ known-bugs #26 fixed) |
| N | **Async API** — submit → poll over the ledger's `queued/active/completed` lifecycle (api.py's own stated limitation), plus read endpoints for versions and diffs. | **done** — §57 |
| — | End-to-end test extended over J–N, then plan batch 3. | **done** — `test_full_lifecycle_through_the_maintainer` (§58) |

**Owner decisions accumulated so far (not in any batch — each needs a call from the owner):** ~~(1) the OLMo 3 guest's memory problem, known-bugs.md #24~~ (resolved §59 once guest changes were permitted); (2) the flaky `qwen2.5-1.5b` factual assertion; (3) what Engineering's reasoning style is while the sandbox is off (its `executable` rounding claims vs. the fidelity fingerprint); (4) which models to admit before the API passes a fitness store (§48); (5) whether §11.5's importance threshold should narrow when human input triggers a checkpoint (§45); (6) adopting `README.draft.md`; (7) how a reviewer approves a checkpoint in the deployed system. The API has no authentication, so approval stays a Python call until the owner picks an auth approach (batch 5, Phase Z). The same decision covers an ingestion endpoint (Phase Y). (8) How the ledger and graph should be stored long-term. Every write snapshots the whole store, which is still quadratic after Phase AB's 70% cut: roughly 6–7 GB of ledger by 1,000 questions (§76). The options are per-question logs, delta checkpoints, or pruning superseded snapshots, and the last conflicts with append-only as written.

**Batch 2 (J–N) complete 2026-09-26**, end-to-end extended (Section 58).

### Batch 3 (self-planned 2026-09-26)

Same rules and stop conditions. Each item is a real gap found while building batches 1–2, not new scope.

| Phase | Scope | Status |
|---|---|---|
| O | **Whole-word jurisdiction matching** — every agent matches its keywords as *substrings* (`"all"` routes Logic for "does a b**all** fall"; `"if"` matches "d**if**ferent"), which is also the root of the "fall of the Berlin Wall" over-reach limitation. Match whole words; add a physical-context requirement for Physics's motion verbs. | **done** — §60, known-bugs #28 |
| P | **Automatic compaction and de-compaction in idle evolution** — §10.3 says compaction is *performed by* an idle-evolution process, but idle cycles only record survival; §10.5 requires expanding a compacted claim before resolving a challenge to it, which idle disputes don't do yet. | **done** — §61, known-bugs #29 |
| Q | **Maintainer restart recovery** — its queue is in memory (§56's stated limitation), so a restart strands queued or mid-way questions. Persist the unit registry in the Maintainer's own checkpoint and resubmit on start; deliberations resume from their last completed round. | **done** — §62 |
| R | **Refresh the narrated demo** (`demo_brain.py`) to show batches 1–2 end to end; mind known-bugs #16 (the final-print trap). | **done** — §63 |
| — | End-to-end test extended, then plan batch 4. | **done** — §64 |

**Batch 3 (O–R) complete 2026-09-26.**

### Batch 4 (self-planned 2026-09-26)

Same rules and stop conditions. Again, each item is a gap found while building, not new scope.

| Phase | Scope | Status |
|---|---|---|
| S | **Feed calibration (§5.3, §9.3)** — the per-agent calibration store — "the accountability mechanism" — is never written outside tests. Idle re-examination is exactly when a claim's fate becomes known: record survived claims as verified and challenged/unsupported ones as overturned, per agent at the confidence it claimed; the Maintainer's audits then report `calibration_drift` per agent. | **done** — §65 |
| T | **Grade weights into the versioned standard** — synthesis's `GRADE_WEIGHT` (§41) sits outside the reputability standard §43 versioned, so it can't evolve under the same review; move it into the standard's params with v0 = today's values. | **done** — §66 |
| U | **Ingestion feeds the Belief Graph** — ingested sources and their `cites` become `source` nodes and `cites` edges, so dispute resolution and consolidation can read citation data from the graph instead of a hand-passed map. | **done** — §67 |
| V | **Mobile client: async mode and history** — the client only knows the synchronous call; let it submit async, poll status, and show versions/diffs and maintenance activity. | **done** — §68 |
| — | End-to-end test extended; README draft refreshed (local, still unpushed); plan batch 5. | **done** — §69 |

**Batch 4 (S–V) complete 2026-09-26.**

### Batch 5 (self-planned 2026-09-26)

Same rules and stop conditions. Each item is a gap confirmed in the code while building batch 4, not new scope.

| Phase | Scope | Status |
|---|---|---|
| W | **A failing unit is lost silently** — `MultiUnitScheduler.process_one_round` pops a unit before running its round and requeues it only on success, so a round that raises drops the unit. The API worker logs an `error` event, but the question stays `active` forever; after a restart the Maintainer resubmits it and loses it again. Catch per-unit failures in the Maintainer, retry a bounded number of times from the last completed round, then mark the question `suspended` with the error and drop it from the registry. Surface this in the API and the client. | **done** — §70, known-bugs #31 |
| X | **Grade changes reach every dependent answer (§7.2, first trigger)** — re-evaluation candidates come only from the ~20 claims an idle cycle samples, so a source that turns `rejected` leaves unsampled answers relying on it unreopened indefinitely. Each cycle, use the Belief Graph (source ← claim ← answer) to find every question whose latest answer relies on a source whose grade changed since the previous cycle, and hand those questions to re-evaluation as well. | **done** — §71 |
| Y | **Scheduled ingestion (§9)** — `ingestion.py`'s docstring promises "a scheduled work-unit type", and none exists. Make ingestion a checkpointed WorkUnit the Maintainer runs at low priority: per source, fetch, check, normalize, then record in the CAS and graph, with no re-fetch or double record after a kill. Tests use fixtures plus a real localhost HTTP fetch. | **done** — §72 |
| Z | **Human checkpoints visible** — standard-amendment proposals and human-input checkpoints wait for a reviewer, but nothing outside Python can see them. Add a read-only `GET /api/checkpoints` and a client panel. *Approving* over the unauthenticated API is deliberately not built (owner decision 7). | **done** — §73, known-bugs #32 |
| — | End-to-end test extended; README draft refreshed (local); plan batch 6. | **done** — §74 |

**Batch 5 (W–Z) complete 2026-09-26.**

### Batch 6 (self-planned 2026-09-26)

Same rules and stop conditions. Each item was confirmed against the running code while closing batch 5.

| Phase | Scope | Status |
|---|---|---|
| AA | **API input validation and error handling** — reproduced on LXC 104: `POST /api/questions` with a non-string `question` crashes the handler, so the client gets no response. It also leaves a `queued` ledger entry nothing will ever run. An empty question is deliberated, a 200 KB question is accepted, and the request body is read with no size limit. Validate (a non-empty string within a length limit; a bounded body), and answer every failure with a JSON error. If a synchronous deliberation fails, suspend the question with its error instead of leaving it `queued`. | **done** — §75, known-bugs #33 |
| AB | **Measure storage growth** — every store write appends a full-state checkpoint (append-only by design, §5.3), so storage grows with writes × state size. Measure bytes per answered question and per idle cycle on the API wiring, find the dominant writers, and remove only *redundant* writes (a checkpoint of unchanged state). Whether old snapshots may ever be pruned is owner decision 8, not a mechanical fix. | **done** — §76, known-bugs #34 |
| AC | **Refresh the narrated demo** (`demo_brain.py`) for batches 4–5: calibration, ingestion into the graph, a grade change reaching every dependent answer, a failing step set aside visibly. Mind known-bugs #16. | **done** — §77 |
| — | End-to-end test extended; README draft refreshed (local); plan batch 7. | open |

- [ ] `execution_sandbox.enabled` stays `false` — not actionable right now (the CPU-time gap is a confirmed environment limitation on this specific kernel, not a bug to fix), but re-run `scripts/preflight_check.py` if this project is ever deployed to a *different* host, per `security-review-sandbox.md` Section 7.3/7.4.

## 27. Brain backlog resumed: Physics, Philosophy, Theology agents; infra topology plan

Picked up the Brain backlog per the planning conversation of 2026-09-22 (ordered list now tracked as the checklist above, superseding the flat "what's next" prose style). First two items:

**Three new deterministic Master Agents** (`src/athenaeum_brain/agents.py`), matching the existing honesty discipline (real computation, not asserted text): `MasterOfPhysics` (free-fall kinematics, `d = 0.5*g*t^2`, cross-examined via independent re-derivation like Mathematics); `MasterOfPhilosophy` (is-ought category-error detection — flags normative-question framing and any other agent's `empirical`-typed claim smuggling a normative conclusion); `MasterOfTheology` (a small real lookup of three named traditions' documented positions, always `claim_type: traditional`, confidence capped at 0.75, cross-examines any traditional claim asserted at empirical-grade confidence as a §6.4 discipline violation). Wired into `rounds.py`'s `ALL_AGENTS` — routing, cross-examination, and Domain Fidelity Monitoring now cover the full six-agent set for the first time.

Tests added (`tests/test_brain_agents_new.py`), run for real on LXC 104 (`athenaeum-preflight`) after a host cold-boot reachability check per `CLAUDE.md`'s own protocol — host and guest both up, SSH working. One real bug caught during that run: `MasterOfPhysics.explore()` used bare `float(token)` and silently produced zero claims on a height token with a unit suffix (`19.6m`), since `float("19.6m")` raises; fixed with a regex extracting the numeric part. One real *non-bug* emergent interaction, also only found by actually running the suite: adding Philosophy changed the committed-claim count on the pre-existing "how should we round 2.5?" fixture from 2 to 3, because that question contains "should" and now correctly routes to Philosophy alongside the Mathematics/Engineering jurisdictional-conflict pair — the system behaving more correctly, not a regression. Both fixed; full writeup with the reasoning in `docs/brain-session-log.md` (new file, the running decision log requested this session). Two pre-existing tests updated to the new, correct expectation rather than suppressing Philosophy's response.

**Real test run required reinstalling `python3-pytest`/`python3-yaml` on LXC 104** — not present this session (guest was rebuilt clean per Section 23 at some point since they were last installed); reinstalled via `apt-get`, no config change needed.

**`docs/infra-topology.md`** (new) — the XSmall/Medium/Large/XLarge brainbox sizing convention and shared-memory architecture (centralized canonical store, ephemeral per-box working context, shared read-only model-weight store), written per the same planning conversation. Design-only — no guests of this shape exist yet, and the `infra/proxmox/03-create-project-guest.sh` `--tier` extension it calls for is next.

**123/123 tests passing** (113 from Section 22 + 10 new in `tests/test_brain_agents_new.py`), verified for real on LXC 104, not just locally (this Windows dev machine has no local Python interpreter — confirmed, not assumed, matching this project's own "verify empirically" principle).

## 28. Output Types (Phase 7)

`src/athenaeum_brain/output_types.py` (new): `classify_output_type()` (keyword-cue classification, wired into `framing_round` so a question's output-type classification is itself written to the Belief Graph alongside routing, per §3.1's own reasoning for why routing is recorded there); `build_research_answer()` (wired into `loop.py`'s synthesis round -- every deliberation's `answer` dict now also carries `answer["output_answer"]`, structured per §5.2); `build_forecast_answer()`/`resolve_forecast()` and `build_recommendation_answer()` (complete, tested, standalone -- not yet wired to a producing agent, since none of today's toy agents emit the resolution/objective structure either needs as input); `compose_answer()` (non-collapsing multi-type composition, the same principle §4.2 established for jurisdictionally plural answers, applied across output types). `reevaluation.forecast_is_material()` implements §5.4's last bullet: a resolved forecast is always material regardless of importance rating.

Design choices and the one open question left deliberately unresolved (confidence aggregation across multi-type answers, Open Question 4 -- only partially addressed) are logged in `docs/brain-session-log.md`.

**136/136 tests passing**, verified for real on LXC 104 (123 prior + 13 new: 12 in `tests/test_output_types.py` plus one in `test_brain_rounds.py` covering framing-round classification, and additional assertions in `test_brain_integration.py` covering the loop.py wiring).

## 29. Human Input Pipeline and Governance (Phase 13)

Matches the existing Body-storage/Brain-judgment split (`reputability_store.py`/`consolidation_store.py` pattern): `src/athenaeum_body/human_checkpoint_store.py` (new, storage only -- pending_human_checkpoint/current status, full transition history, CheckpointLog-backed like every other store here) and `src/athenaeum_brain/human_input.py` (new, judgment): `submit_human_input()` (§11.1's required justification/declared_scope, unjustified-but-present input capped at low confidence rather than rejected, per 11.1's own stated resolution of "required" vs. "accepted as low-weight testimony"); `record_submitter_outcome()` (§11.3 -- a direct reuse of `ReputabilityStore.record_outcome()`'s existing `subject_type` parameter, not a parallel tracking system, since the store was already generic enough); `human_input_is_material()` (§11.5); `trigger_checkpoint_if_needed()` and `clear_checkpoint()` (§11.5/11.7 -- Reviewer-role gating, and the conflict-of-interest rule that a submitter can't clear their own triggered checkpoint, enforced as a hard `CheckpointConflictError`, not left to caller discipline).

One honestly-scoped limitation, not glossed over: cross-examination of a `human_input` claim currently only gets a real challenge/corroboration if it happens to match one of the existing toy agents' narrow statement-pattern regexes (e.g. Mathematics' primality format). A free-text human claim outside those patterns survives cross-examination *by omission*, not because any agent actually evaluated it -- this is a real gap in "examined, never auto-accepted" until a real reasoning backend exists, not a design flaw in this module. Logged in `docs/brain-session-log.md`.

**154/154 tests passing**, verified for real on LXC 104 (136 prior + 18 new in `tests/test_human_input.py`).

## 30. Engineering Agent real loop and Model Fitness (Phase 15)

`MasterOfEngineering` gains `verify_code()` and `verify_claim()` (`src/athenaeum_brain/agents.py`): the real specify→implement→execute→verify loop (§2.2), calling the actual `sandbox.run_sandboxed()` (no mocking, same convention as `test_sandbox.py`) and tying `claim_type: executable` confidence directly to the real exit code and stdout (1.0/0.0, never a middle value -- a mechanical defeat condition per §2.2, not an inferred one). `verify_claim()` implements the cross-cutting verification routing task (44): another agent's formalizable claim plus an executable check for it, fed back as a corroborating/challenging response against the *original* claim. Both accept an injectable `sandbox_run` for callers that don't need the real OS sandbox spun up per case (unit-testing the pass/fail decision logic itself).

`serving_model` added to the `Claim` structure (§3.5, previously missing from `claims.py` despite being in the design's own schema) and threaded through Engineering's claims (`"deterministic:sandbox_execution"` by default, since there's still no real model backend -- honest, not a placeholder pretending otherwise).

**Model Fitness** (§6.7): `model_fitness_store.py` (Body, mirrors `reputability_store.py`'s shape exactly, per-`(agent, model)` tallies) + `model_fitness.py` (Brain): `fitness_weight()` resolves **Open Question 10** (cold-start weighting) via Laplace/add-one smoothing over the corroborated/challenged tally -- a brand-new pairing lands at exactly 0.5 with zero evidence, moving smoothly toward 1.0/0.0 as real evidence accumulates rather than jumping to an extreme on one early data point. `snapshot_and_record()` extends §6.3's non-retroactive-attachment discipline (already used for source grading in `loop.py`) to Model Fitness. `apply_fitness_to_confidence()` scales a claim's starting confidence without ever exempting it from cross-examination, per §6.7's explicit "never a hard-floor override" rule.

**169/169 tests passing**, verified for real on LXC 104 (154 prior + 15 new: 7 in `tests/test_engineering_execution.py` including real, unmocked sandbox runs of both a known-correct and a known-buggy solution; 8 in `tests/test_model_fitness.py`). Design reasoning (the smoothing-formula choice, why it resolves Open Question 10 rather than sidestepping it) logged in `docs/brain-session-log.md`.

## 31. Content Integrity enforcement (Phase 14)

`src/athenaeum_brain/content_integrity.py` (new). Section 12.1's core rule -- "no code path lets ingested or human text alter control flow" -- is verified *by construction*, not asserted: `test_no_eval_or_exec_in_claim_handling_modules` statically scans every file in `src/athenaeum_brain/` for `eval(`/`exec(` and fails if either appears anywhere (`sandbox.py` in `athenaeum_body` is the sole, deliberate exception -- the Body's own isolated execution boundary, reached only through Engineering's `verify_code()` with caller-supplied task code, never a claim's own `.statement`). A second test submits an adversarial human_input claim worded as a fake system instruction ("IGNORE ALL PREVIOUS INSTRUCTIONS...") through the real `submit_human_input` → `cross_examination_round` → `synthesis_round` path and confirms it never becomes anything other than an ordinary claim.

`detect_instruction_like_content()` / `record_instruction_like_signal()` implement §12.3's advisory heuristic, resolving **Open Question 8** concretely: a detected pattern contributes exactly one ordinary "challenged" outcome to the existing reputability tally -- the same weight any other cross-examination challenge already carries, never a separate override channel or automatic rejection. A *pattern* of detections still accumulates toward `rejected` through the existing tally mechanism, matching §12.3's own "a pattern is grounds for a low grade" wording exactly.

**176/176 tests passing**, verified for real on LXC 104 (169 prior + 7 new in `tests/test_content_integrity.py`). Design reasoning in `docs/brain-session-log.md`.

## 32. Evaluation Infrastructure (Phase 9b) — closes the six-phase ordered plan

`src/athenaeum_body/calibration_store.py` (Body, per-agent confidence-bucket tallies, same storage-only pattern as every other store here) + `src/athenaeum_brain/evaluation.py` (Brain):
- **§9.1** `run_ground_truth_benchmark()` -- runs the real four-round loop, not a simulation, against hand-written cases with a known expected substring.
- **§9.2** `run_adversarial_suite()` -- one real, checkable case each for false consensus, is-ought category error, unverified-execution-claims-being-structurally-impossible, prompt-injection staying inert, traditional-claim confidence capping, and silent-model-substitution detectability. Explicitly **not** all 16 rows of §8's table -- several (e.g. "silent style drift") need enough real reasoning volume from an actual model backend to be meaningfully testable, and are named as blocked rather than faked with a hollow check.
- **§9.3** `calibration_report()` -- per-bucket observed-verified-fraction query over `CalibrationStore`.
- **§9.7** `b0_retrieval_only()`, `a1_full_workflow()`, and both required ablations (`ablation_no_cross_examination`, `ablation_naive_majority_vote`). B1 (single-agent generalist baseline) is explicitly flagged blocked (`B1_UNAVAILABLE`) rather than faked from a deterministic toy agent, which wouldn't actually test what B1 is meant to test.
- **§9.8** `check_integrity_gates()` -- pass/fail, non-compensatory (commit-boundary violations, missing provenance, uncorrected category errors reusing Philosophy's own word list rather than a second copy of it).
- **§9.9** contamination isolation verified by construction, same technique as §12.1's scan: a test confirms `ingestion.py` (the Body's one real ingestion entry point) never imports `evaluation.py`.

**One real, non-obvious finding, surfaced by actually building the ablation rather than assumed:** the "remove reputability weighting" ablation §9.7 calls for turns out to be indistinguishable from A1 in the current codebase, because `synthesis_round` doesn't yet use reputability grades to numerically reweight a claim's confidence at commit time -- `loop.py` snapshots grades onto the answer (§6.3) and reputability informs dispute resolution, but that feedback loop into synthesis's own commit decision was never actually wired. Per §9.7's own closing line ("if the ablations don't show each removed component actually contributing, that is treated as a real finding about the architecture"), this is logged as exactly that -- a genuine gap between §6.7's design intent and today's implementation -- not explained away.

**192/192 tests passing**, verified for real on LXC 104 (176 prior + 16 new in `tests/test_evaluation.py`).

**This closes all six phases of the ordered plan from the 2026-09-22 planning conversation** (agents → infra topology → output types → human input → engineering/model-fitness → content integrity → evaluation). Remaining open work is tracked in the checklist below, most of it explicitly blocked on infrastructure this POC doesn't have yet (a real model backend) rather than unscheduled.

## 33. Ingestion's real network fetch, unblocked

Revisited per Section 26's own note: `ingestion.py`'s `fetch_url()` is real now, not a `FixtureSource` stand-in requiring hand-authored content. Stdlib `urllib` only (matches `api.py`'s own no-new-dependency convention), a real robots.txt check via `urllib.robotparser` (fails open only when robots.txt itself is unreachable, never silently converts a genuinely failed page fetch into a robots disallow), and a distinct `FetchError` from `IngestionRejected` -- a network failure and a license/ToS rejection are different kinds of "didn't ingest," and conflating them would have hidden which one happened.

`license` and `is_paid_or_metered` remain caller-supplied on the returned `FixtureSource`, unchanged from before -- neither is something an HTTP response can mechanically prove, so this doesn't pretend the real fetch closes that gap; a human/curator still asserts them, same as for a hand-authored fixture. `FixtureSource`'s name is kept as-is rather than renamed for the now-dual real/fixture use, to avoid churning every existing caller and test for a naming-only change -- noted as a deliberate, scoped call in `docs/brain-session-log.md`.

**6 new tests**, including two real, unmocked network round-trips from LXC 104 (a real stable public-domain page, and a real DNS failure against an RFC-2606-reserved `.invalid` host) plus deterministic robots.txt edge-case coverage via narrow monkeypatching (a live third-party site's exact robots.txt isn't something this suite should depend on staying unchanged forever).

**198/198 tests passing**, verified for real on LXC 104 (192 prior + 6 new in `tests/test_ingestion_real_fetch.py`).

## 34. Distributed worker dispatch (Task 23), unblocked

Revisited per Section 26's own note. `src/athenaeum_body/distributed_worker.py`: `serve_worker()` (a stdlib `http.server`-based worker, generic over a caller-supplied `round_handler_factory` so this module never imports or hardcodes anything about `athenaeum_brain` -- the same Body/Brain layering discipline `loop.py` already established, just extended to the network boundary) and `remote_round_handler()`, which returns a `RoundHandler` with the exact same `(state, round_index) -> RoundResult` signature as any local handler -- `SingleUnitRunner` and the multi-unit scheduler need **zero changes** to run a distributed unit, since `run_round()` already only checkpoints *after* a round completes, which is precisely the property that makes "worker loss simply requeues the unit" true for free: a failed remote round leaves the checkpoint log untouched, so retrying is just calling `run_round()` again.

Scoped deliberately: tested against a second real OS process (`multiprocessing`, explicit fork context) on the same LXC 104 host, not a second physical guest -- this satisfies Section 26's "needs a second process/host to be meaningful" honestly (it names *process*, not exclusively *host*) without the added cost/risk of standing up new infrastructure for one test. `test_worker_loss_mid_task_leaves_checkpoint_retryable_then_recovers` does a real `proc.terminate()` mid-deliberation, confirms the checkpoint is byte-for-byte unchanged after the failed round, then brings up a fresh worker process and confirms the same unit resumes and completes -- this is Section 4.2's stateless-lease-holder claim demonstrated, not just asserted.

**202/202 tests passing**, verified for real on LXC 104 (198 prior + 4 new in `tests/test_distributed_worker.py`). Design reasoning (why a second process rather than a second guest) in `docs/brain-session-log.md`.

## 35. World News, a seventh Master Agent, and a plumbing refactor for adding future domains

Per explicit request: a new domain for building timelines showing how major world events tie into each other, plus a request that adding future domains not be difficult.

**Registry refactor first, since the second request shapes how the first is built:** `agents.py` previously required a class list hardcoded in `rounds.py` for every new agent. Now `agents.py` exposes a `@master_agent` class decorator that appends to a module-level registry; `rounds.py` builds `ALL_AGENTS` via `all_agents()` instead of a hardcoded list. Adding a new domain is now: write the class in `agents.py`, decorate it, done — no other file needs to change. `domain_fidelity.py`'s per-agent `FINGERPRINT_CHECKS` is a separate, *optional* lookup (a missing entry returns a neutral 0.0 deviation, not an error), so a newly registered agent works correctly before anyone adds it a style marker. Proven, not just asserted: `test_registering_a_brand_new_toy_domain_requires_no_other_file_change` registers a throwaway agent inline and confirms it's picked up with zero edits elsewhere.

**`MasterOfWorldNews`** (`agents.py`, `brain-design.md` Section 2.0b — recorded as a deliberate seventh-agent extension the same way Section 2.0 records Engineering's own addition, not silently added to the taxonomy). Domain: current and historical world events, chronology, and documented causal/contributing relationships between them. Reasoning mode mirrors Physics's defeat-condition discipline, but the falsifiable unit is temporal precedence against a small, real, deliberately narrow dated-event registry (same scoping discipline as Theology's three-tradition lookup) — a claimed causal link is mechanically flagged chronologically POSSIBLE or IMPOSSIBLE by comparing documented dates, exactly the kind of real, checkable computation every other toy agent here is built on. `build_timeline()` is a direct utility for the stated goal, sorting recognized events by date and reporting (never silently dropping) unrecognized ones.

**One real bug caught while building it, worth remembering:** `'world war i'` is a literal substring of `'world war ii'` (`'world war i' + 'i'`), so a naive `in` substring check on event names would have silently matched WWI inside any question that only ever mentions WWII. Fixed with word-boundary regex matching (`_find_events`) instead of plain substring search — verified with a dedicated test (`test_wwii_alone_does_not_falsely_match_wwi_substring`), not just fixed and assumed correct. A second, smaller bug (tense mismatch: the causal-claim keyword list had "caused"/"led to" but not "cause"/"lead to", so present-tense questions like "does X cause Y?" silently produced no causal claim) was caught the same way -- by actually running the tests, not by review.

**219/219 tests passing**, verified for real on LXC 104 (202 prior + 17 new in `tests/test_world_news_agent.py`). Design reasoning in `docs/brain-session-log.md`.

## 36. Real Local Model Serving Layer backend, real B1 baseline

The model-lab candidates (Section 35, `infra/proxmox/model-lab/`) are live: six VMs created, each running a real llama.cpp `llama-server` for one model, verified serving real completions (OLMo 2 correctly named its own founder). Two real bugs caught and fixed during the actual run, not found by review: `pve_wait_task` treated any benign task warning (LXC create's routine "systemd 252 detected" notice) as failure, aborting guest creation after the guest was already created fine (`lib/common.sh` fixed to accept `WARNINGS:*`); hostnames with underscores are invalid DNS names, rejected by the Proxmox API (manifest hostnames fixed to hyphens); `huggingface-cli` has been deprecated and outright removed (not aliased) in current `huggingface_hub` releases — replaced with `hf download` after the first live run against all six guests failed on it.

`model_serving.py` gains `LlamaCppBackend` — a real `Backend` implementation (stdlib `urllib` only) talking to actual running `llama-server` processes, deliberately stateless about load/unload since each guest already holds exactly one model for its systemd-managed process lifetime (the same "stateless lease-holder" pattern `distributed_worker.py` already established). `model_lab_registry.py` (new) is the single source mapping the six live endpoints into `ModelSpec`s/a `ModelRegistry`. `ModelServingLayer.request()` proven for real end-to-end, CPU-fallback path (no GPU pool exists — `gpu_available=False` is the honest topology, not a workaround).

One more real finding while testing: 256 `n_predict` tokens genuinely exceeded a 60s timeout on Phi-3.5-mini's 2-vCPU box under CPU inference — not a bug, a real capacity number. `LlamaCppBackend.n_predict` made configurable, defaulted to 64 (fast for comparison/sanity use; longer real reasoning should raise both `n_predict` and `timeout_seconds` together).

`evaluation.py`'s B1 baseline (§9.7) — previously explicitly blocked (`B1_UNAVAILABLE`, "requires a real generalist reasoning backend") — is now real: `b1_single_agent_baseline()` gets an actual generalist completion from a model-lab candidate, no framing/routing/synthesis, matching B1's own definition exactly.

**No Master Agent uses this backend for its own claims yet** — every agent is still deterministic toy logic; this section closes the infrastructure gap (§4.5), not the reasoning-quality gap. Wiring an agent to actually reason via one of these models is the natural next step, not attempted in this session.

**225/225 tests passing**, verified for real on LXC 104 (219 prior + 5 new in `tests/test_model_serving_real.py`, +1 in `test_evaluation.py` for the real B1 baseline) — including live network calls to all six model-lab guests as part of the test suite itself, not just manual spot-checks.

## 37. First real Master Agent reasoning: OLMo 2 as the shared fallback backend

Per explicit decision ("use Paul Allen's model as the Master Agent," clarified via options to: shared default backend for all seven, a new eighth agent, or one pilot agent — shared default was chosen): `src/athenaeum_brain/model_backed_reasoning.py` (new) gives every eligible Master Agent a real fallback when its own narrow deterministic computation finds nothing for a question it's routed to. **Logic is the one deliberate exception** — §2.2 requires it never assert first-order claims, so it has no fallback call site at all, by construction, not by convention.

Each of the other six agents (Mathematics, Engineering, Physics, Philosophy, Theology, WorldNews) was restructured: existing logic renamed to `_explore_deterministic`, a new thin `explore()` wrapper tries that first and falls back to `model_backed_claim()` only when it's empty *and* the agent is actually in its own declared jurisdiction (guards against a direct `explore()` call on an out-of-domain question producing a claim it has no business making — this is also what kept the fallback from breaking any of the many existing tests that call `explore()` directly on out-of-domain questions expecting `[]`). Fallback claims are typed per-agent to match each agent's own existing discipline, never a generic default: `formal` for Mathematics, `normative` for Philosophy (never `empirical` — that's the exact category error Philosophy's own cross-examination polices in other agents), `traditional` capped at Theology's existing 0.75 confidence ceiling (not the generic fallback confidence), `empirical` for Engineering/Physics/WorldNews — and `claim_type: executable` is never used here, reserved exclusively for `verify_code()`'s actual sandbox runs. Confidence is capped well below the 1.0 reserved for mechanically-verified claims (§5.1: every confidence must be traceable to something) — a raw completion is genuinely unverified until cross-examination.

**Two real findings from actually running this against the live OLMo 2 guest, not assumed:** a 60s timeout intermittently tripped when several real fallback calls landed on the same single-model guest in quick succession (these guests queue rather than reject — fixed with a more generous 120s default); separately, OLMo 2's own sampling occasionally produces a near-empty completion (observed directly: a single space, for an ordinary prompt) — real sampling variance, not a backend fault, now retried internally (`ask_model`'s `max_attempts=3`) rather than left to each of the six call sites to handle individually.

**13 new tests** (`tests/test_model_backed_reasoning.py`), including real fallback calls against the live guest for all six eligible agents, a deterministic test proving Logic never falls back, a deterministic test proving the deterministic path always wins when it finds something, and a monkeypatched test proving the empty-completion retry logic itself without depending on sampling variance actually recurring on demand.

**238/238 tests passing**, verified for real on LXC 104 (225 prior + 13 new). Design reasoning in `docs/brain-session-log.md`.

## 38. Resource cap raised to 80%, and the OLMo generation swap (OLMo 2 → OLMo 3)

**Resource cap:** explicit user decision, 2026-09-23 — the 50% CPU/RAM cap this project used throughout testing is raised to **80%**, per the phasing this project's own memory notes always anticipated ("50% cap is testing-only; user plans to raise it once live"). `CLAUDE.md`'s hard constraints section and `docs/infra-topology.md` §1 updated with the recomputed real budget: 40 threads × 80% = 32 threads, ~503GB RAM × 80% ≈ 402GB. As of this date, nine guests (104, 106, plus seven model-lab guests) allocate ~19 vCPU, leaving **~13 vCPU / ~370GB** real headroom — always check the live number before planning against this, per the doc's own standing advice.

**OLMo generation swap, prompted by a direct question ("is this the biggest/newest AI2 model?"):** verified live against Hugging Face that it wasn't — OLMo 2 (1B/7B/13B/32B) has been superseded by **OLMo 3** (7B, Nov 2025) and **OLMo 3.1** (32B, Dec 2025), both Apache 2.0. Concretely:
- `model_backed_reasoning.py`'s `DEFAULT_MODEL` changed from `olmo2-1b` to **`olmo3-7b`** — the real fallback backend for six of the seven Master Agents is now OLMo 3, not OLMo 2.
- VMID 110 (`olmo2-1b`) destroyed; VMID 116 (`athenaeum-modeltest-olmo3-7b`, `192.168.0.166`, 4 vCPU/10GB) created in its place, same resource footprint as the existing `mistral-7b` guest.
- A separate, one-off **VMID 117** (`athenaeum-modeltest-olmo3-32b`, `192.168.0.167`, 4 vCPU/32GB) was also stood up — AI2's current largest public model, for a direct quality comparison before deciding anything further. **Not** part of `manifest.tsv`'s standard six-way set and **not** wired into `model_backed_reasoning.py` — comparison-only, reachable via `model_lab_registry.OLMO3_32B_ENDPOINT`.
- To fit both new guests inside the (then-50%, now-80%) cap without exceeding it, the four smallest comparison guests (Qwen2.5-Coder-1.5B, Qwen2.5-1.5B, Phi-3.5-mini, Granite-2B) were resized from 2→1 vCPU each — a real, low-risk trade-off made transparently, not silently.
- `manifest.tsv`, `model_lab_registry.py`, and affected tests updated to match; full reasoning in `docs/brain-session-log.md`.

**Three more real bugs found getting both guests actually working, none guessable in advance:**
1. OLMo 3's GGUF chat template uses a Jinja `tojson` filter llama.cpp's built-in minimal parser doesn't support — `llama-server` parses/validates the chat template at *startup* even though every caller here only ever uses the raw `/completion` endpoint, so the server crash-looped indefinitely (systemd restarting it every ~5s, hidden behind a generic 503 "Loading model" unless `journalctl -u llama-server` was actually checked). Fixed by adding `--no-jinja` to every guest's `ExecStart` (not just OLMo 3's) — root-cause, not a one-off patch, since any future model's template could hit the same gap.
2. Restoring the four resized guests from 1→2 vCPU (now that the 80% cap gave room) cut full-suite runtime from 311s to 179s and eliminated most, but not all, of a batch of real timeout failures.
3. `model_backed_reasoning.ask_model()`'s own retry loop had a real bug: on a timeout (`BackendUnavailable`) it returned `None` immediately, silently burning zero of its `max_attempts` — only an empty-string response was ever actually retried. Fixed to retry on both failure modes.
4. The real, decisive one: OLMo 3 (unlike OLMo 2) reliably — not occasionally — returns an **empty completion for a bare, unframed question**; it needs explicit `Q: ...\nA:` continuation framing to know a response is expected at all. Confirmed directly (4/4 real calls empty on the bare prompt, 2/2 real calls succeeded once framed) before fixing, not assumed. `ask_model()` now wraps every question in that frame before it reaches the backend.

**240/240 tests passing**, verified for real on LXC 104 against both new guests. Full reasoning for all of the above in `docs/brain-session-log.md`.

## 39. Elastic GPU worker pool: opportunistic compute that can go offline without crashing anything

Per explicit request ("pipe [my 3070 Ti] through, so that proxmox-01... use the GPU"), then a critical follow-up clarification that reshaped the whole design: "I don't want to make this Windows machine a permanent dependency, nor any specific machine... I want to be able to bring it online and offline as I wish, while the system doesn't crash... the scalability to be fully elastic." This is body-design.md §4.3's "opportunistic compute, never a dependency" principle, implemented for real for the first time, not just stated.

**Why not Proxmox-hosted GPU passthrough:** PCIe passthrough only works within one physical machine — it can't be tunneled over the network to a guest on a different physical host. Clarified to the user directly rather than attempted; the actual approach is running inference locally on the GPU-owning machine and exposing it over the LAN as an HTTP service, same shape as the existing model-lab guests.

**`src/athenaeum_body/elastic_workers.py`** (new): `WorkerSpec`/`load_workers()` (parses `elastic_workers.yaml`, a hand-edited manifest — not push-based self-registration, matching this project's "no speculative infrastructure" discipline; a registration protocol is unneeded complexity until a second or third worker actually needs one) and `ElasticGPUBackend` — the actual elastic mechanism. Critically, health is checked **fresh on every single call** (`_is_healthy()`, a real HTTP `/health` request with a short timeout), never cached: a worker that was up a second ago and just went dark is caught immediately, not on some stale interval. `infer()` raises `BackendUnavailable` (the same exception `LlamaCppBackend`/`distributed_worker.py` already use) whenever no configured worker for a model is currently reachable — "zero workers up" and "no workers configured" produce the identical, already-handled outcome.

**`ModelServingLayer.request()`** (`model_serving.py`) wraps its GPU-backend attempt in try/except `BackendUnavailable`, falling through to the existing CPU backend transparently — the GPU worker going offline mid-session degrades to CPU, it never raises out to the caller. **`model_backed_reasoning.ask_model()`** tries the elastic GPU backend first, then CPU, on every one of its retry attempts (not just the first), so a worker flickering online/offline mid-retry-loop is handled correctly too.

**`infra/elastic-workers/windows-gpu-worker/`** (new): a manual, foreground PowerShell launcher (`start.ps1`) plus a README — deliberately not a Windows service or auto-start mechanism, matching the user's own stated intent ("bring it online and offline as I wish"). Configurable via environment variables (model file, port, GPU-layer count) rather than hardcoded, since "multiple such machines with various configurations" was explicitly named as a near-term expectation.

**Real, not just designed:** downloaded a CUDA-enabled `llama-server` build plus a matching `cudart` package, started a real GPU-backed OLMo 3 7B server on this Windows machine's RTX 3070 Ti (confirmed 7848MiB/8192MiB VRAM used, ~84 tok/s vs. ~5.5 tok/s on the CPU guests), confirmed LXC 104 reaches it over the LAN, and ran the real fallback path against it end-to-end.

**One real bug, caught only by running the full suite with the real worker actually online:** three unit tests in `test_model_backed_reasoning.py` (`test_ask_model_retries_on_empty_or_whitespace_completion` and two neighbors) monkeypatch `LlamaCppBackend` to test `ask_model()`'s CPU-path retry logic in isolation — but since `ask_model()` now tries the GPU backend first, and the real Windows worker was genuinely running at the time, it answered for real and bypassed the very mocked logic these tests exist to exercise (assertions like `result == "a real answer"` failed against genuine OLMo 3 completions instead). This is not a bug in the elasticity mechanism — it is exactly what "opportunistic, checked live" is supposed to do — but it is a real test-isolation gap. Fixed with a `_stub_gpu_unavailable(monkeypatch)` helper that forces `build_elastic_gpu_backend()` to always raise `BackendUnavailable`, making these three tests correct regardless of whether a real worker happens to be up when they run.

**`tests/test_elastic_workers.py`** (new): deterministic unit coverage needing no real machine (config parsing, health-filter-by-model-name, graceful `BackendUnavailable` on zero/unreachable workers, and the actual point of the module — `ModelServingLayer` transparently falls back to CPU when the configured GPU worker is unreachable, proven with a deliberately-unroutable ghost endpoint plus the real CPU `olmo3-7b` guest) plus one real/skippable test (`test_real_elastic_worker_gets_a_real_gpu_backed_completion`) that only runs when a real worker is actually reachable right now, and skips cleanly — not a failure — when it isn't, matching the module's own "offline is routine" premise.

**248/248 tests passing**, verified for real on LXC 104 (240 prior + 8 new in `tests/test_elastic_workers.py`). Full design reasoning in `docs/brain-session-log.md`.

## 40. First live side-by-side comparison across every model-lab candidate, including the elastic GPU worker

Per explicit request to run one adversarial prompt (an object-tracking scenario plus a letter-avoidance constraint) across "every LLM" and report output/tokens/time per model — the first time all eight live candidates (six standard model-lab guests, the one-off OLMo 3 32B comparison guest, and the elastic Windows GPU worker from Section 39) were queried side by side in one exercise. Ad hoc, not a permanent addition to the test suite or evaluation harness — run directly against each `llama-server`'s `/completion` endpoint via `curl`, timed with curl's own `%{time_total}`, token counts read from llama.cpp's real `timings` response block (`tokens_predicted`, `predicted_ms`), not estimated.

**One real, reproducible finding, not a fluke:** all three OLMo 3 variants (7B CPU, 7B GPU, 32B) returned a **genuinely empty completion** on the raw, unframed prompt — the exact same failure mode already root-caused and fixed inside `ask_model()` (Section 38: OLMo 3 needs explicit continuation framing, unlike the other five model families). This ad hoc `curl` harness talks to the endpoints directly, bypassing `ask_model()`'s framing fix entirely, so the bug was still there to hit — confirms the earlier fix is real and necessary, not incidental. Re-ran all three with a `\n\n1.` continuation cue appended to the prompt; all three then answered normally (concise, and the only three of the eight to actually honor the "no letter e" constraint). No code changed — this was a live demonstration of an already-fixed, already-documented bug recurring in a context that doesn't go through the fix, not a new defect.

**Secondary finding:** of the eight, `qwen-coder-1.5b` degenerated into verbatim repetition until it hit the token cap (400) rather than stopping — a real model-quality/stopping-criteria issue on that specific guest, not a harness bug (other guests on the same harness, same `n_predict`, stopped normally well under the cap).

Not committed as a permanent fixture: no new file, no wiring into `evaluation.py`'s adversarial suite. If this kind of multi-model comparison becomes a recurring need, the natural next step is a small script wrapping this exact pattern (`curl` + `timings` block) rather than hand-typing it each time — not built here since it was a one-off request, matching this project's own "don't build speculative infrastructure" discipline.

## 41. Evidence-weighted synthesis (§4.1), and the reputability ablation made real

First item from a 2026-09-25 audit of remaining Brain work (now listed in §26). `synthesis_round` accepts an optional `grade_lookup` and, for every committed claim, sets `reputability_factor` (weakest-link `GRADE_WEIGHT` across its `supporting_provenance`; 0.0 for a claim citing nothing) and `weighted_confidence` (= `confidence` × factor). The agent's own `confidence` is never modified. Weighting never changes commit/dissent — only ordering. `loop.py` passes grades read *before* `_attach_grades_and_record_outcomes` records this deliberation's own outcomes, so the weight and `source_grades_at_use` come from the same time-of-use snapshot (tested with a source that crosses into `foundational` on this very deliberation).

`build_research_answer` now picks the highest-weighted committed claim as `leading_conclusion` (raw confidence when unweighted) and keeps the rest in a new `supporting_conclusions` field — previously any answer with two compatible committed claims had no leading conclusion at all. Plural answers are unchanged.

`evaluation.py`: `ABLATION_NO_REPUTABILITY_WEIGHTING_FINDING` (Section 32's "indistinguishable from A1") replaced by a real `ablation_no_reputability_weighting()`; `a1_full_workflow()` takes a `grade_lookup` and both return a `research` section. Proven distinct on a real question: with `computed:trial_division` rejected, A1 leads "should we believe 17 is prime?" with Philosophy, the ablation with Mathematics.

**257 passed, 1 skipped** on LXC 104 (247 prior + 10 new in `tests/test_evidence_weighted_synthesis.py`; the skip is the real-GPU-worker test, worker offline). Design reasoning in `docs/brain-session-log.md`.

## 42. Dispute resolution (§6.4) and the independence check that catches circular corroboration

`src/athenaeum_brain/dispute_resolution.py` (new) implements §6.4's four steps as real computation. `check_independence(sources, cites)` groups sources into independent lines of evidence — two sources collapse into one if either reaches the other through citations, or both derive from a common upstream source (even one not itself cited on the claim), transitively; any source on a citation cycle is reported as `circular`. `resolve_dispute(subject_id, sides, reputability=, cites=)` restates each side, grades its sources, routes the category-error check to **Philosophy and Theology's own `cross_examine`** (never decided by Logic, §6.4.3), and rules for a side only if it has strictly more independent, non-rejected lines of evidence after excluding category-error claims — otherwise "unresolved", never a manufactured winner. The ruling and rationale are logged permanently via `ReputabilityStore.log_dispute`, marked reversible, and **never edit a grade** (no unilateral blacklist authority — grades still move only through §6.2 outcomes, tested).

Citation data: `FixtureSource` gains an optional curator-supplied `cites` list (same status as `license` — not mechanically derivable from content), carried into `ProvenanceEntry.metadata["cites"]` only when non-empty so existing entries are unchanged; `citation_map(entries)` builds the lookup from ingested entries.

**Real instance of the failure mode fixed:** `consolidation.should_promote_to_c` counted "independent sources" as `len(entry["sources"])`, so two sources that just cite each other satisfied a 2-source Tier C promotion threshold. It now takes `cites` and counts independent groups, naming circularity in its reasons. With no citation data the count is unchanged, so existing callers behave identically. New adversarial case `circular_corroboration` (suite now 7 of §8's 15 modes).

**273 passed, 1 skipped** on LXC 104 (257 prior + 16 new in `tests/test_dispute_resolution.py`; `test_evaluation.py`'s pinned case list updated to include the new case). Design reasoning in `docs/brain-session-log.md`.

## 43. Reputability standard versioning (§6.5), and §7.2's standard-change materiality trigger

The placeholder grading rule is now a **parameterized, versioned standard** in `ReputabilityStore` (`reputability_store.py`). Version 0 is the seed standard (§6.1) with exactly the thresholds the rule always had (`rejected_min_challenges=3`, `foundational_min_corroborations=5`), so every grade decided before this change is correctly a v0 decision. `adopt_standard(params, rationale)` requires a non-empty rationale and exactly the known parameter keys (positive ints), appends version N+1, and regrades non-retroactively: each source whose grade differs under the new standard gets a **new appended** grade entry (`decided_under: N+1, cause: "standard_amendment"`) while all earlier entries stay untouched; it returns which sources moved. `standards()` is the full, never-shrinking history; `grade_history(source)` shows every decision with its standard and cause (`evidence` or `standard_amendment`); `grade_under(source, v)` is a pure read of what a source's grade would be today under any past standard.

`current_grade()` now returns `{grade, version, standard_version}` (the standard in force), a clean projection rather than the raw entry — so `loop.py`'s time-of-use snapshot automatically records the standard in force too. Checkpoints written before this change (no `standards` key, no `decided_under`/`cause` on entries) read back as v0, tested directly.

**§7.2's fourth trigger:** `reevaluation.is_material` takes an optional `prior_standard_grades` — the grade each cited source would have *now* under the standard in force *at time of use*, computed by the new `materiality_inputs(answer, store)`. If that differs from the current grade, the standard change moved it: material regardless of the evidence threshold, with a reason naming the amendment (`standard amended (v0 -> v1)`). If the old standard would still give today's grade, the change is evidence-driven and the existing threshold/severity rules apply unchanged. Without the new argument, `is_material` behaves exactly as before.

One existing expectation changed: `test_content_integrity.py` pinned `current_grade()`'s exact return for an ungraded source and now includes `standard_version: 0`.

**Not done here:** nothing yet *proposes* amendments — §6.5's "idle-evolution review re-examines the standard for internal consistency" needs the idle-evolution round (next-session plan item 4). `GRADE_WEIGHT` (synthesis, §41) is not part of the versioned standard; if it should be, that's a small follow-up.

**286 passed, 1 skipped** on LXC 104 (273 prior + 13 new in `tests/test_standard_versioning.py`). Design reasoning in `docs/brain-session-log.md`.

## 44. Forecast and Recommendation producers (§5.4) — Phase A, plus a real Physics parsing bug

**Forecast producer (Physics).** For a forecast question ("will …") that states a time bound ("within 3 seconds", "in under 2.5 s", "more than 4 seconds"), `MasterOfPhysics` now issues, alongside its research claim, a forecast claim carrying a full `forecast` payload: statement, probability, resolution criterion (`measured time from release to ground contact <= 3s`), resolution source, deadline, the computed sensitivity (e.g. "resolves NO if air resistance adds more than 0.98s to the 2.02s vacuum fall time"), and its assumptions. The probability comes from how much room the vacuum fall time leaves for air resistance — which can only lengthen a fall — through an explicitly-labelled placeholder band table (`_SLACK_BANDS`). It lives only in the payload; the claim's `confidence` stays Physics's confidence in its own computation (§5.4's category error, tested).

**Recommendation producer (Mathematics/Engineering).** Their rounding claims now carry `recommendation_option` — the option, the objective it serves (schoolbook convention vs. no systematic bias in sums), and its reversibility. `output_types.recommendation_section_from_claims` builds the section: when the options serve different objectives it chooses **none**, stating that which objective takes priority is the decision-maker's value judgment (§4.3, no manufactured winner); when there's one objective, every option it covers is chosen.

**Loop wiring.** `loop.py` now emits a section for *every* output type the frame asks for. Forecast/Recommendation sections are built only from committed claims (a challenged forecast is dissent, not a forecast — tested); when nothing carries the structure, the section is an explicit `{"available": false, "reason": ...}` (e.g. "will it rain tomorrow?") instead of being silently dropped, which is what happened before.

**Real bug found and fixed (known-bugs.md #21):** Physics took every bare number as a drop height — "did the berlin wall fall in 1989?" committed a 1989 m free-fall claim, and a forecast's "within 3 seconds" became a 3 m drop. Heights now need a length unit or a "from N" role. Three related weaknesses were reproduced but deliberately not fixed here and are now in known-bugs.md's new "Open known limitations" list: keyword routing over-reach (Physics is still *routed* Berlin Wall questions), Mathematics checking primality of any bare integer, and Engineering typing its in-process rounding as `executable` (deferred to Phase D).

`schemas.md` brought current (it had drifted): Claim table gains `argument`, `output_type_relevance`, `reputability_factor`, `weighted_confidence`, `forecast`, `recommendation_option`, and an accurate `serving_model` note; Provenance `metadata.cites`; Reputability Grade's stored `decided_under`/`cause` and `current_grade()` projection; new Reputability Standard table.

**310 passed, 1 skipped** on LXC 104 (286 prior + 24 new in `tests/test_output_producers.py`, parametrized). Design reasoning in `docs/brain-session-log.md`.

## 45. Importance rating (§7.1) and reopen-with-diff (§7.3) — Phase B

`src/athenaeum_brain/reopening.py` (new):
- **`importance_rating(frame, dependents=, requested_priority=)`** returns an explained 0–1 rating: breadth of domains (Logic excluded — it chairs everything, so it says nothing about breadth; saturates at three), multiple output types, dependents (saturating, 2 → 0.5), and an explicit requester priority. Weights are an explicitly-labelled placeholder (`IMPORTANCE_WEIGHTS`). **`count_dependents`** counts other questions whose latest answer commits one of the same claims — a stated proxy, since no Belief Graph dependency edges exist yet. **`rate_and_store_importance`** stores it via the new `QuestionLedger.update_importance` (bounds-checked; §7.1 "revisable"). The HTTP API now stores this computed rating instead of its hardcoded `0.5`.
- **`reopen_question`** re-runs the full four-round deliberation with the prior answer attached as input context only (every round still re-derives from scratch), first expanding any of the prior answer's Tier C claims from cold archive (§10.5), then appends a new ledger version carrying an explicit **`diff`**: claims added/removed, evidence-weight changes with direction, what happened to the leading conclusion (unchanged + confidence direction / changed / appeared / disappeared), plural-answer counts, and the cause. The prior version is never touched (tested byte-equal); reopen context never nests.
- **`reopen_if_material`** is the trigger policy: materiality (§7.2, including milestone 3's standard-change rule) *and* importance at or above a threshold — except a **resolved forecast, which reopens regardless of importance** (§5.4/§7.2), with the outcome passed in explicitly rather than looked up (§9.9).

Supporting changes: every answer now records its own `question` and `frame` (answers written before this can't be reopened, and say so); `make_deliberation_unit` accepts `reopen_context` and a distinct `unit_id`; `consolidation.claim_key(claim)` (agent + statement) is the one canonical key for "the same claim again", used by reopening and, next, by idle evolution; `output_types.evidence_weight` made public. `schemas.md` gains a Deliberation Answer table.

**Real bug found and fixed (known-bugs.md #22):** Philosophy's is-ought claim began "this question asks…", so its claims about *different* questions had identical text — `count_dependents` linked unrelated questions, and consolidation would have counted every normative question as the same claim surviving again. The statement now names its question; a scan found no other deictic statement templates.

**Follow-up noted, not done:** `human_input.trigger_checkpoint_if_needed` still checkpoints on *any* material human input because importance didn't exist when it was written; §11.5's "importance-thresholded question" clause can now use `importance_rating`, but changing that alters an existing, tested governance behaviour, so it's left for an explicit decision.

**327 passed, 1 skipped** on LXC 104 (310 prior + 17 new in `tests/test_reopening.py`). Design reasoning in `docs/brain-session-log.md`.

## 46. Idle-evolution rounds (§3.6) — Phase C

`src/athenaeum_brain/idle_evolution.py` (new): an idle cycle is an ordinary `WorkUnit` (default priority −1, so real questions are served first) with four rounds — **sample** (committed claims from the ledger, highest-importance questions first, seeded-random within ties, so a cycle is reproducible), **re-examine** (fresh cross-examination by today's agents plus re-weighing under today's grades; each claim ends `survived`, `weakened` — evidence weight fell since commit, `unsupported` — weakest source now rejected, or `challenged`), **review** (pure analysis), and **commit** (the only round with side effects). It is the missing caller for everything periodic:
- **Consolidation (§10):** `survived`/`weakened` claims record a survival cycle under the canonical `claim_key`, with the *current evidence weight* as the confidence recorded — so a weakening claim's declining trend blocks Tier C promotion by §10.2's own rule.
- **Dispute resolution (§6.4, §42):** each newly challenged claim goes to `resolve_dispute` with the challenges as the other side, logged under a cycle-scoped `dispute_id`.
- **Domain Fidelity (§2.4):** each agent in the sample is scored and recorded (tagged with the cycle id); `needs_review` flags are reported.
- **Standard review (§6.5, §43):** if ≥2 claims resting only on `foundational` sources are challenged, the cycle *proposes* raising the foundational bar by one — sent to the human checkpoint (`standard-amendment:<cycle>`), never adopted automatically. `apply_amendment_if_approved` adopts it only once a Reviewer has approved it through `human_input.clear_checkpoint`, and only once.
- **Re-evaluation (§7):** challenged/unsupported findings become `reevaluation_candidates`; `feed_reevaluation` passes them to `reopen_if_material` as additional material reasons (§7.2's "newly challenged claim" trigger — new `additional_reasons` parameter), still under the importance gate.

**Deliberate restraint:** an idle cycle records *no* reputability outcomes — surviving re-examination is not new evidence about a source, and counting it would let a claim promote its own sources every cycle (tested: tallies unchanged across three cycles).

**Kill/resume safety:** every commit-round write is idempotent under the cycle id — `record_survival(cycle_id=)`, `ReputabilityStore.log_dispute(dispute_id=)` / `resolve_dispute(dispute_id=)`, fidelity records checked by `cycle_id`, and the amendment checkpoint created only if absent — so a cycle killed after writing but before checkpointing can re-run its last round without double-counting (tested directly, plus a real kill-between-rounds resume).

**Real bug found and fixed (known-bugs.md #23):** claim ids were a per-process counter (`claim-0`, `claim-1`, …), so claims from different processes — past ledger answers, `distributed_worker.py` rounds — could share ids, and cross-examination attributes challenges by id. Ids are now uuid-based; re-examined claims also get fresh ids for their pass.

Two open limitations logged in `known-bugs.md`: idle re-examination can only re-challenge claim shapes today's cross-examiners recognise; and one full-suite run hit a **flaky live-model assertion** — `qwen2.5-1.5b` answered "Saturn is the largest planet" once (5/5 re-runs passed); the test's factual assertion is left for the owner's decision, not loosened.

**340 passed, 1 skipped** on LXC 104 (327 prior + 13 new in `tests/test_idle_evolution.py`), confirmed on a re-run after the one sampling-variance failure described above. Design reasoning in `docs/brain-session-log.md`.

## 47. Cross-agent verification routing (task 44) — Phase D

`src/athenaeum_brain/verification_routing.py` (new) routes another agent's formalizable claim to Engineering, which checks it by executing an **independent** method in the Body's sandbox; `MasterOfEngineering.verify_claim` (which already existed, unused) turns the run into a corroborating or challenging round-2 response against the original claim, so synthesis treats it exactly like any cross-examination (a challenged claim lands in dissent — tested). Two verifiers, registered with `@verifier` so more can be added without touching the router:
- **Primality** (`N is prime` / `N is not prime`): a sieve of Eratosthenes, not Mathematics's trial division.
- **Free fall** (Physics's fall-time statement): semi-implicit Euler integration at 0.1 ms steps, not the closed form — the design's own "a Physics simulation" example.
Each has a size cap (n ≤ 10⁷, h ≤ 10 km) so a sandbox job is decided by the maths, not by the wall-clock limit; larger claims are left to ordinary cross-examination. Engineering's own claims are never routed back to it.

**Gate:** routing happens only when the caller passes `verification={"enabled": True, ...}`. `sandbox_enabled()` reads `execution_sandbox.enabled` from config and accepts only a literal `True`; the shipped config is `false` (tested as a hard constraint), and the HTTP API passes exactly that, so **nothing is routed or executed in normal operation.** When skipped, the answer's new `verification` field says how many verifiable claims went unverified and why, rather than skipping silently. Tests exercise routing with a small local runner that executes the generated check code in a plain subprocess, plus one test through the real `run_sandboxed` (same convention as `test_engineering_execution.py`); the config setting itself was not changed.

**Open limitation re-examined, still open:** Engineering types its in-process `decimal` rounding as `executable`. Retyping it collides with Domain Fidelity's Engineering fingerprint (`claim_type == "executable"`); resolving it needs a decision about what Engineering's reasoning style is while the sandbox is disabled. Recorded in `known-bugs.md` for the owner rather than decided here.

**362 passed, 1 skipped** on LXC 104 (340 prior + 22 new in `tests/test_verification_routing.py`). Design reasoning in `docs/brain-session-log.md`.

## 48. Model admission gate and fitness weighting at synthesis (§6.7) — Phase E

**Admission (§6.7, task 47):** `ModelFitnessStore` gains a per-model admission record (`admit` — once, never rewritten; `admission`; `outcomes_for_model`), and `model_fitness.admit_model` is the gate: a written rationale is required, and admission grants no weight — an admitted model sits at the cold-start fitness of 0.5 for every agent and moves only with outcomes. `model_standing` reports `not_admitted` / `provisional` / `established` (after `ESTABLISHED_AFTER` = 10 outcomes, placeholder). `rank_models_for(agent, candidates)` orders admitted models by fitness — §6.7's "informs which model is asked for next".

**Fitness at synthesis:** `synthesis_round(fitness_lookup=)` multiplies each committed claim's evidence weight by `fitness_factor(agent, serving_model)` — 1.0 for deterministic claims (`serving_model` None or `deterministic:…`), **0.0 for a model never admitted**, otherwise the (agent, model) weight — stored on the claim as the new `fitness_factor` field, alongside `reputability_factor`; raw `confidence` is untouched. As with §41, weighting never decides commitment: an unadmitted model's claim is committed if it survives, just never able to lead, and the answer lists it under `unadmitted_models`.

**Loop:** `make_deliberation_unit(model_fitness=)` snapshots factors during synthesis and records outcomes only afterwards (`_attach_fitness_and_record_outcomes`, attaching `fitness_at_use`) — tested non-retroactive across two deliberations. Outcomes are recorded **only for admitted models**, so a model can't accumulate a track record before admission. The pre-existing `snapshot_and_record` helper is unused by the loop and now documents why (it would leak one claim's outcome into the next claim's snapshot within a deliberation).

**Not wired, deliberately:** the HTTP API passes no fitness store — with no models admitted yet, every model-backed claim would weigh zero, so turning it on is an admission decision for the owner. The agents' fallback still asks `DEFAULT_MODEL`.

**Verification — stated exactly, because it was partial.** During this phase the OLMo 3 7B guest (VMID 116) degraded badly (known-bugs.md #24: `llama-server` at 98% of its 10 GB limit, swap full, ~45× slower). The normal full suite could not complete in reasonable time. Added an opt-in `ATHENAEUM_OFFLINE_MODELS=1` mode in `tests/conftest.py` (model fallback behaves as "backend unreachable"; default behaviour unchanged) and ran: **354 passed, 1 skipped, 3 failed** with `test_model_backed_reasoning.py` (15 tests, all live-OLMo) set aside — the 3 failures are all `BackendUnavailable: 'olmo3-7b' … timed out` (`test_elastic_workers` CPU-fallback test and two in `test_model_serving_real.py`). None of those 18 tests exercise code this phase changed. 373 tests collected in total (363 prior + 10 new in `tests/test_model_admission.py`). The live-OLMo tests must be re-run once the guest is fixed.

## 49. Domain Fidelity remediation: flagged review, re-grounding, escalation (§2.4.3) — Phase F

`src/athenaeum_brain/fidelity_remediation.py` (new) turns a Domain Fidelity drop into a staged, recorded path instead of a silent behaviour change. `remediate(store, agent, recent_claims=, cycle_id=, checkpoints=)` advances an agent by at most one step per call:
- **Flagged review** — when `needs_review` fires, the agent's recently re-examined claims are checked for *style* (fingerprint deviation ≥ `STYLE_CONFIRM_THRESHOLD`, placeholder 0.25), not correctness. Not confirmed → `cleared`.
- **Re-grounding** — confirmed → for `REGROUNDING_CYCLES` (3) further fidelity readings, the agent's **model-backed fallback is suppressed**, so it can only assert what its own grounded, deterministic computation produces: the POC's mechanical form of "increase weight toward the foundational corpus", with model completions as the newer, less-disciplined material. Suppression is a `contextvars`-scoped block (`model_backed_reasoning.fallback_suppressed`) applied by the loop around its exploration round only (new `fidelity=` parameter; the answer lists `regrounding_agents`), so it can't leak across the API's threads.
- **Escalation** — still drifting when the period ends → `escalated`, a `domain-fidelity:<agent>` human checkpoint is (re-)armed, and suppression stays on until a Reviewer approves it; then `cleared`. A second escalation always re-arms the checkpoint, so an earlier approval can't clear it (tested).
Every transition is appended to the agent's remediation history (new `DomainFidelityStore.remediation/set_remediation/agents_in_stage`) with its reason; a repeated call for the same cycle id is a no-op. Idle evolution (§46) now calls `remediate` for every agent it scores, and reports `remediation` stages in its result — tested end to end with a drifting (model-written) Mathematics claim.

"Time" here is fidelity readings about the agent (normally one per idle cycle that sampled it), not wall-clock — re-grounding ends when there is enough new evidence about the agent, not after an arbitrary duration.

**Known gap:** only Mathematics, Engineering, Logic and WorldNews have fingerprint checks (`domain_fidelity.FINGERPRINT_CHECKS`), so drift in Physics, Philosophy or Theology can be flagged by overreach but never *confirmed* on style — those agents always clear at review. Adding their markers (§2.4.1 names them: defeat-condition rate for Physics, assumption-surfacing for Philosophy, `traditional` typing for Theology) is logged as a follow-up.

**Verified offline** (OLMo 3 guest still degraded, known-bugs.md #24 — probed again: ~65 s for a 4-token completion): `ATHENAEUM_OFFLINE_MODELS=1`, `test_model_backed_reasoning.py` set aside → **366 passed, 1 skipped, 3 failed**, the same three `olmo3-7b` timeouts as §48. 385 collected (373 prior + 12 new in `tests/test_fidelity_remediation.py`).

## 50. Re-evaluation and consolidation audits (§9.4, §9.5) — Phase G

`src/athenaeum_brain/audits.py` (new) plus a small append-only `AuditStore` (Body, idempotent per `audit_id`) and `ConsolidationStore.entries()`. Both audits are seeded samples, so any audit can be reproduced exactly; both narrow rather than replace human judgment where the design asks for it (§9.4 says "manually check").

- **`reevaluation_audit`** (§9.4 — does the materiality test thrash or stagnate?). Each sampled reopened version is classified from its own diff: `no_change` (nothing moved at all — a **thrash suspect**), `weights_only` (support shifted, conclusions didn't — consistent with a grade-driven trigger), or `leading_changed` (routed to `for_human_review`: only a person can say whether it's better reasoning or just different). The report gives the thrash-suspect rate. Separately it scans the whole ledger for **stagnation**: every answer that is material *right now* (§7.2, including the standard-change rule) but hasn't been reopened — tested going away once the question is reopened.
- **`consolidation_audit`** (§9.5 — is compaction losing meaning?). Each sampled Tier C node is expanded from the cold archive and checked against it: statement, confidence, sources and cycle count must match, and §10.2's promotion criteria must actually hold for the archived trace (enough cycles, enough *independent* sources — with citation data, circular sources fail — and no declining confidence trend). `compact()` itself doesn't gate on those criteria, so this is where a premature or unjustified promotion gets caught. A trace that fails its content-hash check is reported as `archive_corrupt`, never trusted.

Neither audit is scheduled yet — they're callable functions; running them from an idle cycle every N cycles is a small follow-up once there's a cadence policy.

**Verified offline** (OLMo 3 guest still degraded — ~69 s per 4-token call): **383 passed, 1 skipped, 3 failed**, the same three `olmo3-7b` timeouts. 402 collected (385 prior + 17 new in `tests/test_audits.py`).

## 51. Adversarial suite: all 15 of §8's failure modes (§9.2) — Phase H

`evaluation.ADVERSARIAL_CASES` grows from 7 to 16 cases, and a new `SECTION_8_COVERAGE` maps every row of brain-design.md's §8 table to the case(s) that exercise it. `tests/test_adversarial_coverage.py` **parses that table out of the design doc** and fails if any row lacks a real check — so adding a failure mode to the design without a check breaks the build (it already caught one naming mismatch while being written). Every case exercises the real mechanism on constructed input, in throwaway stores, same bar as the original seven:

| §8 failure mode | Case | Mechanism exercised |
|---|---|---|
| Overconfidence drift | `overconfidence_drift` | new `calibration_drift()` — flags a confidence bucket whose observed verified rate sits > 0.2 below its midpoint (n ≥ 5); underconfidence reported separately, not called drift |
| Silent authority creep | `silent_authority_creep` | Logic proposes nothing and responds only procedurally across questions from every domain; Logic isn't a category-error reviewer (§6.4.3) |
| Retroactive history rewriting | `retroactive_history_rewriting` | after later evidence **and** a standard amendment regrade the cited source, the recorded ledger answer and every earlier grade decision are byte-identical |
| Stale framing | `stale_framing` | **new mechanism** (below) |
| Unfalsifiable claims presented as empirical | `unfalsifiable_as_empirical` | **new mechanism** (below) |
| Silent style drift | `silent_style_drift` | Domain Fidelity drop → flagged → confirmed on style → re-grounding (§49) |
| Lossy compaction | `lossy_compaction` | the §9.5 audit (§50) catches a compact node whose qualification was quietly dropped |
| Unjustified human-input skew | `unjustified_human_input_skew` | an unjustified submission asking for 1.0 is capped at 0.3; a justified one isn't |
| Uncommitted canonical writes | `uncommitted_canonical_writes` | exploration output is all `proposed`; the integrity gate rejects an answer listing a proposed claim as committed |

**Two mechanisms the design names were missing and are now built:**
- **Stale framing (§7.2's third trigger):** `reevaluation.frame_staleness(answer)` re-frames the answer's own question today and reports if it would now route to different agents (added or dropped) or classify different output types. `reopen_if_material` includes it as a material reason, and the §9.4 audit's stagnation scan counts it. Frames are compared, not answers — adding a Master Agent that claims jurisdiction over old questions makes those frames stale, as intended (still gated by importance).
- **Falsifiability (§2.2, §8):** Physics now challenges any *empirical* claim from another agent whose defeat condition is vacuous (`""`, `none`, `n/a`, `cannot be falsified`, …): unfalsifiable as stated, belongs with Philosophy.

What this does and doesn't prove is stated in `evaluation.py`'s section header: each case proves the mechanism that guards its failure mode, on constructed input — not that the failure can never occur with real models at scale (brain-design.md §9.6). Two pinned expectations updated accordingly (`test_evaluation.py`'s case set, `test_dispute_resolution.py`'s suite total 7 → 16).

**Verified offline** (OLMo 3 guest still degraded): **398 passed, 1 skipped, 3 failed**, the same three `olmo3-7b` timeouts. 417 collected (402 prior + 15 new in `tests/test_adversarial_coverage.py`).

## 52. End-to-end test over batch 1

`tests/test_end_to_end.py` runs one realistic lifecycle through every mechanism together, on real stores and the real scheduler (only the model fallback is stubbed, so it never depends on the model-lab guests): five questions deliberated with reputability, model fitness (one admitted model), fidelity and verification routing all on — one of them killed after two rounds and resumed from its checkpoint files; importance rated; five idle cycles until "17 is prime" earns Tier C and is compacted; the trial-division source contested, triggering a grade-driven reopen that expands the compacted trace first and records a decreasing weight in its diff while leaving version 0 byte-identical; a forecast resolved and reopened regardless of importance; then both audits, the integrity gates on every latest answer, and the adversarial suite (16/16).

**One real gap found by it and fixed:** the §9.4 audit classified a forecast-resolution reopen whose answer didn't change as `no_change` — a thrash suspect — although §7.2 makes that reopen mandatory whether or not anything changes. `classify_reopen` now returns `forecast_resolution` for those.

**Verified offline** (OLMo 3 guest still degraded — ~61 s per 4-token call): **400 passed, 1 skipped, 3 failed**, the same three `olmo3-7b` timeouts. 419 collected.

## 53. Style fingerprints for Physics, Philosophy and Theology (§2.4.1) — Phase J

`domain_fidelity.FINGERPRINT_CHECKS` now covers all seven agents, using §2.4.1's own markers, each chosen so that it passes the agent's own method and fails a general-purpose model answering in its place (which is what drift looks like in this system):
- **Physics — explicit defeat condition:** not vacuous and not the boilerplate every raw model completion carries (now the named constant `model_backed_reasoning.GENERIC_DEFEAT_CONDITION`). The vacuous-defeat test moved to `claims.is_vacuous_defeat`, shared with Physics's §51 falsifiability challenge so the two can't drift apart.
- **Philosophy — assumption-surfacing:** the claim cites the reasoning principle it rests on (`reasoning:` provenance, e.g. the is-ought gap), not a bare verdict.
- **Theology — `traditional` typing attached:** the marker is the typing itself. Its model fallback is typed `traditional` too, so for Theology the fingerprint measures typing discipline, not method — exactly what §2.4.1 specifies.

Verified against the agents' **real** claims, including Physics's forecast claims: own method → deviation 0.0, model fallback → 1.0. With this, the §49 gap is closed: a Physics drift can now be flagged, *confirmed* on style, and re-grounded (tested end to end through `remediate`). A new test pins that every registered agent has a fingerprint.

One test-authoring slip on the way, a recurrence of known-bugs.md #11 (a test question that no keyword routes to Philosophy); recorded there.

**Verified offline** (OLMo 3 guest still degraded): **410 passed, 1 skipped, 3 failed**, the same three `olmo3-7b` timeouts. 429 collected (419 prior + 10 new in `tests/test_fingerprints.py`).

## 54. Mathematics number parsing (known-bugs.md #25) — Phase K

Mathematics used to claim "N is (not) prime" for every bare integer in any question it was routed to ("is 4 even?" committed "4 is not prime"; the 1 in "…in 1 second" became a primality claim). Now primality — the only property it computes — is claimed only when the question asks about primality, and only for whole numbers that aren't decimals or unit-bearing quantities (`4.9m`, `1 second`, `20 kg`), each once. Questions about other properties fall through to the model fallback instead of receiving an irrelevant confidence-1.0 claim. Moved from known-bugs.md's open-limitations list to fixed bug #25; `tests/test_math_parsing.py` pins eleven shapes.

**Verified offline** (OLMo 3 guest still degraded): **421 passed, 1 skipped, 3 failed**, the same three `olmo3-7b` timeouts. 440 collected (429 prior + 11 new).

## 55. The Belief Graph, graph-based dependents, and §7.2's second trigger — Phase L

`BeliefGraphStore` (Body, new) stores `BeliefGraphNode`/`BeliefGraphEdge` exactly as `schemas.py` already defined them: write-once, with a store-wide `seq` on every node and edge so "added after X" never trusts wall-clock time. `athenaeum_brain/belief_graph.py` (new) decides what's recorded: each deliberation, when the loop is given a graph, writes `question → answer(vN) → claim → source` with `relies_on` / `dissents` / `cites` edges. Claim nodes are keyed by the canonical `claim_key`, so the same claim reached from two questions is literally one node — that is what makes dependency visible. A reopened answer is recorded as the next version.

- **Dependents (§7.1)** — `belief_graph.dependents()` walks real `relies_on` edges; `count_dependents` / `rate_and_store_importance` use it when given a graph and fall back to the ledger scan otherwise (tested to agree).
- **§7.2's second trigger, read narrowly** — `newly_relevant_claims()`: since this question's latest answer, another question committed a claim about the *same normalized subject* (so `2.5` and `2.50` match) that this answer doesn't rely on. `reopen_if_material(belief_graph=)` adds these as material reasons; once the question is reopened, those claims are no longer new (tested). Broader semantic relevance needs a model, as `rounds._normalize_subject` already states — this is the mechanical subset the existing `subject` field supports.

Graph writes happen in the loop's final round and are idempotent by id, so a resumed round can't duplicate anything. Not yet wired into the API or idle evolution (the API has no graph store yet; batch 2's Phase M, the maintenance cadence, is the natural place).

**Verified offline** (OLMo 3 guest still degraded — 64–85 s per 4-token call): **431 passed, 1 skipped, 2 failed** — two of the usual three `olmo3-7b` timeouts; the third (the elastic-worker CPU-fallback test) happened to complete within its timeout this run, which is luck, not recovery. 449 collected (440 prior + 9 new in `tests/test_belief_graph.py`).

## 56. The maintenance cadence, and a concurrency bug it exposed — Phase M

**Real bug first (known-bugs.md #26):** `MultiUnitScheduler` runs every unit through one runner and one `shared_state` — by design, for committed results — but the deliberation handler kept its *working* state under fixed top-level keys. Two deliberations time-sliced together overwrote each other's `frame`: reproduced with "is 17 prime?" coming back with the rounding-2.5 answer, silently. Every earlier test ran one deliberation per runner, so nothing had caught it. Fixed by giving each deliberation (`deliberation:<unit_id>`) and idle cycle (`idle:<cycle_id>`) its own namespace for reads, with writes mirrored at the top level so single-unit callers, existing tests and pre-fix checkpoints keep working. Regression test: two deliberations and an idle cycle strictly interleaved at equal priority, each with the right answer.

**`athenaeum_brain/maintenance.py` (new) — `Maintainer`:** one `MultiUnitScheduler` fed two kinds of unit — questions (priority 0, every store wired in: reputability, model fitness, domain fidelity, Belief Graph, verification) and idle cycles (priority −1, so questions are always served first — tested with an idle cycle queued while a question was still mid-deliberation). Cadence (`MaintenancePolicy`, placeholders): an idle cycle after every N answered questions, plus one when the queue runs dry — but **only one per dry spell**, and a cadence cycle already counts as it, so an idle system never spins re-examining unchanged claims (the test for this caught exactly that flaw in the first version). On completion: a question is appended to the ledger, recorded in the Belief Graph and importance-rated (graph-based dependents); an idle cycle's findings feed re-evaluation (reopened versions recorded in the graph too), any Reviewer-approved amendment is adopted, and every K cycles both audits run into the `AuditStore`. Harvested unit namespaces are removed from the shared state, keeping checkpoints bounded.

**Known limitation, stated:** `MultiUnitScheduler`'s queue lives in memory. Everything completed is durable, but queued or mid-way units must be resubmitted after a restart (a resubmitted deliberation resumes from its last completed round). Not wired into the HTTP API yet — Phase N.

**Verified offline** (OLMo 3 guest still degraded): **437 passed, 1 skipped, 3 failed**, the usual three `olmo3-7b` timeouts. 456 collected (449 prior + 7 new in `tests/test_maintenance.py`).

## 57. Asynchronous API: submit → poll, driven by the Maintainer — Phase N

`api.py` stated its own limitation — every request deliberated synchronously, fine only while agents finish in milliseconds. Now there are two paths over one set of stores (ledger, reputability, Belief Graph, consolidation, fidelity, checkpoints, audits), with every ledger access under one lock:
- **Synchronous, unchanged:** `POST /api/questions` → 200 with the answer. The mobile client and all existing tests use this and are untouched; it now also records into the Belief Graph and rates importance with graph dependents.
- **Asynchronous:** `POST /api/questions` with `{"async": true}` → **202** `{id, status: "queued"}` immediately. A single background worker drives a `Maintainer` (§56) one round at a time, taking the lock per round, so the question moves through the Question Ledger's `queued → active → completed` lifecycle (new `QuestionLedger.set_status`, validated against the schema's states) interleaved with idle cycles. Poll `GET /api/questions/<id>`.
- **New reads:** `GET /api/questions/<id>/versions/<n>` (one ledger version, 404 out of range) and `GET /api/maintenance` (idle cycles run, queued units, pending amendments, recent events).

The worker starts **lazily on the first async submission**, so a purely synchronous user never gets background idle cycles running over their questions (tested). A round that raises is recorded as an `error` event and the worker carries on, rather than dying silently and leaving every later async question queued forever. `build_app` keeps returning the same 4-tuple callers unpack, with the async functions attached as attributes.

Tested against a real running server: async submit returns 202 without an answer and completes in the background; three async questions interleaved on the Maintainer each get their own correct answer (known-bugs #26 through the public API); versions fetch individually; an idle cycle runs once the queue goes quiet, with no error events.

**Verified offline** (OLMo 3 guest still degraded): **442 passed, 1 skipped, 3 failed**, the usual three `olmo3-7b` timeouts. 461 collected (456 prior + 5 new in `tests/test_api_async.py`).

## 58. End-to-end test over batch 2

`tests/test_end_to_end.py::test_full_lifecycle_through_the_maintainer` drives the system the way the async API does — through a `Maintainer` — with the Belief Graph, model fitness (one admitted model), verification routing and every store wired in. Five questions interleaved on one scheduler each get their own answer (known-bugs #26); "is 4 even?" gets no primality claim (#25) and "did the berlin wall fall in 1989?" no 1989 m drop (#21); one idle cycle follows. The Belief Graph links the two primality questions as dependents; a later question about 2.50 makes a claim newly relevant to the 2.5 question and reopens it (§7.2 trigger 2); fingerprints and fidelity records exist for every agent the idle cycle scored; audits ran on their cadence; no unit namespace is left in the scheduler's state; integrity gates pass on every latest answer; adversarial suite 16/16.

**Verified offline** (OLMo 3 guest still degraded — ~73 s per 4-token call): **443 passed, 1 skipped, 3 failed**, the usual three `olmo3-7b` timeouts. 462 collected.

**Permission change, 2026-09-26 (owner):** Proxmox guests may now be created, modified or destroyed as needed during this development phase. This lifts the batch rule "never create/modify/destroy Proxmox guests" and unblocks the OLMo 3 guest fix (known-bugs.md #24, owner decision 1).

## 59. Model-lab guests fixed; first full live run since the degradation

With guest changes permitted, the OLMo 3 7B guest's memory growth was traced to its actual cause: recent `llama-server` builds keep a **prompt cache in RAM whose default ceiling is 8192 MiB** (`--cache-ram`). A 4.4 GB model plus an 8 GB cache can't fit a 10 GB container, so the process grew with every distinct prompt until it swap-thrashed — a function of *use* (a day of full-suite runs), not uptime. All seven model-lab guests were exposed, not just 116.

**Fixed on all seven guests** (VMIDs 111–117) and in `infra/proxmox/model-lab/setup-llama-and-download.sh`: `ExecStart` now ends `--no-jinja --cache-ram 512` (template variable `LLAMA_CACHE_RAM_MIB`), applied idempotently and verified in each running process's arguments, each guest healthy within 2–7 s of restart. 116's swap drained; a 4-token completion went from ~65 s to **1.3 s**.

**Second finding (known-bugs.md #27):** §38 and the setup script said `--no-jinja` had been added to *every* guest; in fact only 116 had it — the other six were never re-provisioned from the updated template. The first `sed`, keyed on `--no-jinja`, silently changed only 116; checking the live units caught it. All seven now match the template exactly.

**Full live suite, no offline mode, nothing ignored: 461 passed, 1 skipped** (the skip is the real-GPU-worker test, worker offline) in 4 m 56 s — the first fully green live run since the guest degraded, including all 15 live-OLMo tests in `test_model_backed_reasoning.py` and every live model-serving test. This retroactively confirms phases E–N, which had only been verified offline.

## 60. Whole-word jurisdiction matching (known-bugs.md #28) — Phase O

All seven agents matched their jurisdiction keywords as substrings, and several internal gates did the same: Logic was routed "does a b**all** fall?", Mathematics/Engineering "a**round**", Mathematics "s**even**", World News "be**cause**" and "to**war**d", Engineering "la**test**", and Philosophy's is-ought check (plus the §9.8 integrity gate reusing its words) fired on "**must**ard". A single `agents.mentions(text, keywords)` — whole words with common inflections, phrases as phrases — now backs every agent's `in_jurisdiction`, every "does the question mention X" gate, Philosophy's normative-word checks and the integrity gate; keyword lists gained the irregular inflections the suffix rule can't reach (`dropped`, `implementation`, `religious`, …).

Physics's everyday motion verbs ("fall", "drop") now route only with physical context — a stated height or a physical object — while its unambiguous terms (gravity, force, momentum, …) route alone. That **closes the open "keyword routing over-reaches" limitation**: "did the fall of the berlin wall lead to the collapse of the soviet union?" routes to World News only (tested).

One existing expectation changed, and it was the right one to change: the batch-2 end-to-end test expected a Physics fidelity record that existed only because the Berlin Wall question wrongly routed Physics. It now asserts the opposite (Physics not routed) and checks that every agent the idle cycle *actually* scored has a fingerprint.

**Full live suite: 487 passed, 1 skipped** (GPU worker offline). 488 collected (462 prior + 26 new in `tests/test_jurisdiction_matching.py`).

## 61. Idle evolution compacts and de-compacts on its own (§10.3, §10.5) — Phase P

§10.3 says compaction is *performed by* an idle-evolution process; until now idle cycles only recorded survival and compaction happened only when someone called `compact()`. Now the idle commit round compacts a claim the moment its entry meets §10.2's criteria (N cycles, M independent sources, no declining trend — N and M on `IdleContext`, placeholders per Open Question 7), and **de-compacts** any Tier C claim that is now challenged or unsupported *before* its dispute is resolved (§10.5) — new `consolidation.decompact()` restores the full archived trace as the active Tier B entry, recording `decompacted_from` and why; the archive itself is untouched (§10.4). Results report `compacted` and `decompacted`.

**Real bug on the way (known-bugs.md #29):** a compacted node has no `confidence_history`, so the first survival recorded after compaction — or a second `compact()` — raised `KeyError`. Latent until now because nothing had compacted and then kept going. Fixed so a Tier C node stays compact and keeps matching its archive: post-compaction survival goes into `cycles_since_compaction` / `current_confidence` (a first attempt overwrote `confidence`, and the §9.5 audit correctly flagged the mismatch); `compact()` is idempotent and preserves `cycle_ids`. `schemas.md` gains the Consolidation Entry table, which had never been written down.

One existing expectation changed: the batch-1 end-to-end test now also sees idle evolution compact the World News claim on its own — it cites two independent dated events, so it meets the default two-source bar — and its consolidation audit covers both compacted claims.

**Full live suite: 493 passed, 1 skipped.** 494 collected (488 prior + 6 new in `tests/test_auto_consolidation.py`).

## 62. The Maintainer survives a restart — Phase Q

`MultiUnitScheduler`'s queue is in memory, so §56 had to state that a killed Maintainer strands queued or mid-way work. Now the Maintainer keeps its own **registry** — every in-flight unit (a question's text, an idle cycle's seed and sample size), the cadence counters, and pending amendments — inside the scheduler's checkpointed shared state, written the moment it changes rather than only at the next round boundary. A new `Maintainer` built over the same checkpoint log reads it back and, for each registered unit, either resubmits it at its last completed round (from the runner's own checkpoint) or, if it had finished but was never recorded, records it now; `recovered` lists what it picked up.

Delivery semantics are deliberate and stated in `_complete`: **question answers are at-least-once and idempotent** — recorded before the unit leaves the registry, and a replay skips a question the ledger already has as completed, so an answer can be neither lost nor duplicated (both crash points tested). **Idle-cycle follow-ups are at-most-once** — the cycle leaves the registry before its reopens/amendments/audits run, because a replayed reopen would append a duplicate version, whereas a lost one is simply found again by the next cycle.

Tested by throwing a Maintainer away mid-run (the crash) and building a new one over the same files: interleaved questions resume and each is answered exactly once; a finished-but-unrecorded question is recorded on restart; an answer recorded just before the crash isn't recorded again; a half-run idle cycle resumes without starting a second one; counters and pending amendments survive.

**Full live suite: 498 passed, 1 skipped, 1 failed** — the failure is the known-flaky `qwen2.5-1.5b` factual assertion (known-bugs.md open limitations, owner decision 2), which then failed 1 in 6 immediate re-runs; nothing else failed. 500 collected (494 prior + 6 new in `tests/test_maintenance_recovery.py`).

## 63. The narrated demo shows batches 1–3 — Phase R

`demo_brain.py` gains five steps after its original seven, each on deterministic questions so it never depends on the model guests: **(8)** evidence weighting flipping the leading conclusion when a source's track record is rejected, against the no-weighting ablation; **(9)** a real Forecast (probability 0.9, with its air-resistance sensitivity) and a Recommendation that lists both rounding conventions with the objective each serves and chooses neither; **(10)** a dispute where circular citation leaves one side with a single line of evidence; **(11)** the Maintainer answering three interleaved questions, being thrown away mid-way, and a new one recovering all three, answering each once, running an idle cycle, and linking two questions through the Belief Graph; **(12)** the adversarial suite, 16/16 across all 15 §8 failure modes. Run it with `python demo_brain.py`.

Known-bugs #16 (the final-banner trap, hit twice before) was respected — the existing banner was moved after the new steps, not left in place — and is now **guarded by a test**: `tests/test_demo_brain.py` runs the whole demo and asserts a clean exit, exactly one final banner at the very end, and 16/16.

**Full live suite: 500 passed, 1 skipped** (GPU worker offline) — fully green, the flaky assertion passing this time. 501 collected.

## 64. End-to-end test over batch 3

`tests/test_end_to_end.py::test_lifecycle_across_a_restart_with_self_compaction`: a physical question routes to Physics alone (whole-word matching); a Maintainer is thrown away with two questions in flight and a new one recovers both, answering each exactly once; three more questions each bring an idle cycle, by the third of which idle evolution has compacted the surviving claims on its own; the consolidation audit passes over everything it compacted; audits ran every cycle. With the batch-1 and batch-2 scenarios, the end-to-end file now exercises all 22 phases together.

**Full live suite: 501 passed, 1 skipped.** 502 collected.

## 65. Calibration is finally fed (§5.3, §9.3) — Phase S

The per-agent calibration store — §5.3's "accountability mechanism" — had never been written anywhere outside its own adversarial check. Idle re-examination is exactly when a claim's fate becomes known, so the idle commit round now records every re-examined claim's outcome at the confidence its agent originally claimed: `survived`/`weakened` count as verified (both withstood cross-examination), `challenged`/`unsupported` as overturned.

**One claim, one data point:** the new `CalibrationStore.set_outcome(claim_key, …)` keeps each claim's *latest* fate and overwrites it if the fate changes; per-agent tallies are computed from those plus any explicit `record` calls. Tallying every re-examination instead would let a single long-lived claim swamp its agent's record — the same self-reinforcement trap §46 avoided for reputability (tested: three cycles over one surviving claim → one verified outcome; a claim whose source is later rejected flips to overturned).

The Maintainer now computes `calibration_drift` for every agent after each idle cycle, reports `calibration_drifting` on its event, and records a `calibration` audit (tested: five 0.95-confidence claims that all fail re-examination flag Physics with an observed rate of 0.0). The API's Maintainer gets a calibration store too.

**Full live suite: 506 passed, 1 skipped.** 507 collected (502 prior + 5 new in `tests/test_calibration_feeding.py`).

## 66. Grade weights are part of the versioned standard — Phase T

Synthesis's per-grade evidence weights (§41, `GRADE_WEIGHT`) sat outside the reputability standard §43 versioned, so they couldn't change under the same reviewed, non-retroactive process. Each standard version now carries `grade_weights`; v0's are exactly the values synthesis always used (`reputability_store.SEED_GRADE_WEIGHTS`, with `rounds.GRADE_WEIGHT` kept as that seed for callers with no store), and standards saved before this read back as seed. `adopt_standard(..., grade_weights=)` validates them — all four grades, each in [0, 1], non-decreasing as grades improve — and a version that doesn't set them inherits the current ones. Both the deliberation loop and idle re-examination use the weights of the standard in force at time of use.

Stated explicitly: a **weights-only amendment regrades nothing and is not material** under §7.2's fourth trigger, whose wording is about a change that "would alter the grade of a source the answer relied on" (tested). If weight changes should reopen answers too, that's a design extension, not something to infer.

**Full live suite: 515 passed, 1 skipped.** 516 collected (507 prior + 9 new in `tests/test_grade_weights_standard.py`).

## 67. Ingestion feeds the Belief Graph — Phase U

Source-to-source citations (§42's independence check, §10.2's *independent* sources) only ever reached the Brain as a `cites` dict a caller passed by hand. Given a Belief Graph, `ingest`/`seed_load` now record each accepted source as a `source:<id>` node (license, content hash) with a `cites` edge to every source it cites; a cited source not yet ingested gets a bare node, filled in by its own ingest. It is write-once, so re-ingesting is a no-op, and a rejected source leaves no trace. `belief_graph.citations(graph)` reads the map back and deliberately excludes claim→source `cites` edges: those are provenance, not citation between sources.

`IdleContext` has a new `belief_graph` field and a new `citation_map()`: the hand-supplied `cites` merged with the graph's, deduplicated. Consolidation's promotion check, Logic-chaired dispute resolution and the Maintainer's consolidation audit all read it. The Maintainer hands its own graph to the idle context unless one was set explicitly. Tested end to end: two ingested sources promote a claim to Tier C after three cycles, but when the graph says one cites the other, the same claim stays in Tier B, with only one independent line of evidence.

**Full live suite: 524 passed, 1 skipped.** 525 collected (516 prior + 9 new in `tests/test_ingestion_graph.py`).

## 68. The mobile client goes asynchronous, with history — Phase V

`client/index.html` only knew the synchronous call, which is the wrong one for LLM-backed deliberations that take minutes. It now:
- submits asynchronously by default (a "wait for the answer" box keeps the synchronous call for quick questions);
- lists the ledger's history on load, newest first;
- polls every 2 s while anything is queued or active, and every 15 s otherwise, so versions that idle evolution's reopens add later still show up;
- shows every version of an answer, with a reopened version's §7.3 diff (why, added/removed claims, weight changes, what happened to the leading conclusion);
- adds a maintenance panel with idle cycles, queued units, amendments awaiting review and recent events.

A card is only redrawn when its status, version count, chosen version or importance changes, so a reader's chosen version survives polling.

**API:** `GET /api/questions` and `/api/questions/<id>` now include `question`, so a question still in the queue (no version yet) can be listed. The text comes from the Maintainer's registry, then from the latest version once answered.

**Security fix — known-bugs.md #30:** the old client interpolated question and claim text straight into `innerHTML`. That was a stored-XSS hole once questions became listable to every viewer. Every interpolation is now escaped, and so is `standalone-demo.html`'s (self-XSS only there, since its text never leaves the page).

**Testing without a browser:** `tests/client/client_smoke.mjs` runs the page's script under node against a minimal fake DOM, `fetch` and timer. It checks:
- history order and pending display;
- versions and the diff, and a chosen version surviving a refresh;
- the maintenance panel and the poll cadence;
- async vs. synchronous submit;
- that a hostile statement is rendered escaped. A mutation that disables escaping makes it fail.

`tests/test_client.py` runs the smoke test and skips when node is absent; nodejs 18 is now installed on LXC 104. Along the way, the guest sync script turned out never to have copied `client/` — the guest had been serving a stale page. Fixed.

**Full live suite: 526 passed, 1 skipped.** 527 collected (525 prior + `tests/test_client.py` + one new test in `tests/test_api_async.py`).

## 69. End-to-end test over batch 4

`test_lifecycle_with_calibration_weights_and_ingested_citations` runs S–U through one Maintainer:
- sources seed-loaded into the Maintainer's own graph show up in idle evolution's citation map, and a rejected source doesn't;
- answering a question brings idle cycles that feed calibration and record a `calibration` audit with no drift;
- a weights-only standard amendment lowers the next answer's reputability factor (0.8 → 0.6 for an ungraded source). It leaves the earlier answer untouched and unreopened (not material under §7.2), while idle re-examination reports that earlier claim as `weakened`, which still counts as verified for calibration.

V has its own tests (§68). `README.draft.md` is refreshed to cover batch 4, still local and unpushed (owner decision 6). Batch 5 is planned above, and its first phase fixes a bug found while planning: a unit whose round raises is silently dropped by the scheduler.

**Full live suite: 527 passed, 1 skipped.** 528 collected (527 prior + 1 new end-to-end test).

## 70. A failing round no longer loses its unit — Phase W

known-bugs.md #31: a round that raised was silently dropped by the scheduler, and its question stayed `active` forever. The Maintainer now catches it per unit:
1. The unit's namespace in the shared state is rolled back to the last checkpoint, since a handler may have changed it before raising.
2. The unit is retried from its last completed round, which re-runs only the round that failed.
3. After `MaintenancePolicy.max_round_failures` attempts (3, a placeholder) it is given up. It leaves the registry, its record including `last_error` moves to `failed`, and a question is marked `suspended`.

The failure count lives in the persisted registry, so a crash-and-restart loop can't grant endless fresh attempts. Events: `unit_error` (with `retrying: true`) per failed attempt, and `unit_failed` when given up. A failing idle cycle is given up the same way without touching any question, and later cycles still run.

**API and client:** a suspended question carries its `error` (`GET /api/questions[/<id>]`), `GET /api/maintenance` lists `failed_units`, and the client shows the error on the card and both event kinds in the maintenance panel, escaped like everything else.

Tests (`tests/test_maintenance_failures.py`, fault injection by wrapping the unit factories):
- a transient failure is retried to the same answer as a clean run;
- a failing round's partial writes are rolled back;
- a persistent failure suspends only its own question;
- the count survives a restart;
- a failing idle cycle is given up without touching questions;
- the API reports the error.

The client smoke test gained the suspended/failed display.

**Full live suite: 533 passed, 1 skipped.** 534 collected (528 prior + 6 new in `tests/test_maintenance_failures.py`).

## 71. Grade changes reach every dependent answer — Phase X

§7.2's first trigger (a source an answer relied on changed grade) only ever fired for claims an idle cycle happened to sample, 20 by default. It was weaker than that, too: a source falling to `contested` leaves the sampled claim `weakened`, which isn't a re-evaluation candidate, so such a change reached no answer at all (tested as the control case).

Now idle round 2 also runs `grade_change_candidates`. For every graded source (`ReputabilityStore.graded_subjects()`), `belief_graph.questions_relying_on_source` walks source ← claim ← answer to every question whose **latest** answer commits a claim citing it. Superseded versions, dissent-only claims and source→source citations don't count. A question becomes a candidate when its answer's snapshot grade for that source differs from today's. `feed_reevaluation` hands those questions to `reopen_if_material` with no added reasons, since its own grade-materiality check states the change, and the importance gate applies as always.

It is idempotent without a watermark: a reopened answer snapshots the new grade, so it stops being a candidate. The idle result reports `grade_change_candidates`.

Tested:
- three prime answers citing one source are all reopened in the cycle after it is downgraded, with only one claim sampled, and the question answered after the change is not;
- the next cycle reopens nothing;
- without the graph, the same change reopens nothing.

One behaviour surfaced while writing the test is correct but worth knowing: every deliberation citing a source records a corroboration, so a borderline downgrade can be undone by the next question's use. The answers then correctly match again, and the new answer, whose snapshot was taken under the brief downgrade, is the one reopened.

**Full live suite: 537 passed, 1 skipped.** 538 collected (534 prior + 4 new in `tests/test_grade_change_reach.py`).

## 72. Scheduled ingestion — Phase Y

`ingestion.py` promised "a scheduled work-unit type" from the start; now there is one. `make_ingestion_unit(batch_id, specs, cas, graph)` processes one source per round: fetch, the license/ToS/paid-access check, normalize into the CAS, then record in the Belief Graph (§67). Each source's outcome, with a reason for every rejection, lands under the unit's own `ingestion:<batch_id>` namespace.

Specs are JSON-safe dicts (`ingestion.source_from_spec`), so a batch can live in the Maintainer's persisted registry:
- `url` and a curator-asserted `license`, optionally `cites`, `is_paid_or_metered`, and `content` for a hand-authored fixture;
- anything without `content` is fetched for real with `fetch_url`;
- a paid or metered source is never requested at all;
- a failed fetch is an outcome, not an exception, so one dead URL doesn't stop, or with Phase W's retries suspend, the batch.

**Kill-safety:** every write in a round (the CAS put, graph nodes and edges) is idempotent, and a round is checkpointed once done. A kill between rounds re-fetches nothing. A kill inside a round re-fetches that one source and records nothing twice. Both are tested, the latter by running a round's side effects without its checkpoint.

**Maintainer:** `submit_ingestion(batch_id, specs)` runs a batch at priority −1, behind questions. It is persisted in the registry, resumed after a restart and retried like any unit (Phase W). It reports an `ingestion` event with what was accepted and rejected, and the harvested namespace is dropped. The Maintainer takes `ingestion_cas`, which the API sets to its store, and `fetch`, a test seam. The client's maintenance panel describes ingestion events. **Deliberately not built:** an HTTP endpoint to submit URLs. An unauthenticated API that fetches caller-chosen URLs from inside the network is a server-side request forgery risk, so it waits on the same auth decision as owner decision 7.

Tested:
- a batch mixing accepted, cited, closed-license, paid, unreachable and fixture sources;
- both kill points;
- an empty batch;
- a **real HTTP fetch over localhost** (a served file is accepted and stored byte-for-byte, and a 404 is rejected with its reason);
- questions served before ingestion;
- a restart mid-batch;
- the configuration errors.

**Full live suite: 545 passed, 1 skipped.** 546 collected (538 prior + 8 new in `tests/test_scheduled_ingestion.py`).

## 73. Human checkpoints visible; a path traversal fixed — Phase Z

§11.5's checkpoints hold everything that waits for a human: standard-amendment proposals from idle evolution (§46), domain-fidelity escalations (§49) and human-input checkpoints. Until now nothing outside Python could see them. Now:
- **`HumanCheckpointStore.all()`** returns every checkpoint;
- **`GET /api/checkpoints`** lists them pending first, each with its `kind` (`standard-amendment`, `domain-fidelity`, or `question` for human input) and `ref`, plus reason, submitter, reviewer, note and status history. A pending amendment also carries the **proposal itself**, so a reviewer sees what would change;
- the client has an "Awaiting human review" panel listing only what is still pending, escaped like everything else.

**Approving is deliberately not an endpoint:** the API has no authentication, so a reviewer still approves through `human_input.clear_checkpoint` in Python. Tested: a POST to `/api/checkpoints` is a 404. Owner decision 7 covers how that should change.

**Security fix — known-bugs.md #32:** while adding the route, the static file handler turned out to serve `CLIENT_DIR / <request path>` unchecked. A raw `GET /../pyproject.toml` returned the file, reproduced against a real server. Paths are now resolved and must stay under `client/`. The tests send raw request lines covering plain, percent-encoded and mixed traversals, including `/etc/hostname`.

**Full live suite: 554 passed, 1 skipped.** 555 collected (546 prior + 9 new in `tests/test_api_review.py`).

## 74. End-to-end test over batch 5

`test_lifecycle_on_the_api_wiring` runs W–Z on `build_app`'s own stores and Maintainer, reading results back through the same functions the HTTP handlers call:
- **Y:** a scheduled ingestion batch stores two fixture sources, rejects a paid one unrequested, and its citation reaches idle evolution;
- **W:** a question whose deliberation always raises is suspended with its error and listed under `failed_units`, while the others are answered;
- **X:** once the primality source is downgraded, the next cycle reopens all three prime answers with a one-claim sample, each with a diff;
- **Z:** a pending human-input checkpoint shows up in the review listing;
- and the synchronous path still answers alongside, on the same stores.

`README.draft.md` is refreshed for batch 5, still local and unpushed. Batch 6 is planned above. Its first phase comes from a reproduced API crash on a non-string question.

**Full live suite: 554 passed, 1 skipped, 1 failed.** The failure is the known-flaky `qwen2.5-1.5b` factual assertion (known-bugs.md open limitations, owner decision 2): the model answered "Saturn". It passed 3 of 3 immediate re-runs, and nothing else failed. 556 collected (555 prior + 1 new end-to-end test).

## 75. API input validation and error handling — Phase AA

known-bugs.md #33: a non-string question crashed the request handler (connection dropped, no response) and stranded a `queued` ledger entry. Empty and 200 KB questions were accepted, and the body size was unbounded. Now:
- **Validation first:** `parse_question_request` accepts only a non-empty string, stripped of surrounding whitespace, of at most `MAX_QUESTION_CHARS` (2000, a placeholder). Each refusal names the problem (400), and nothing is written for it, on the sync and async paths alike.
- **Bounded body:** over `MAX_BODY_BYTES` (64 KiB, a placeholder) is a 413 answered without reading the body. A missing, invalid or negative `Content-Length` is a 400.
- **A failed synchronous deliberation** is `suspended` with its error in the Maintainer's `failed` registry (new `Maintainer.record_failure`, shared with Phase W). It answers a JSON 500 carrying the question id, and the server carries on.
- **A last-resort guard** on every handler turns an unexpected exception into a JSON 500, never a dropped connection.
- The client's input has `maxlength=2000` to match.

Tested with raw requests, including a `Content-Length` promising more than is ever sent: a server that tried to read it would hang, and this one answers 413 at once.

**Full live suite: 569 passed, 1 skipped.** 570 collected (556 prior + 14 new in `tests/test_api_validation.py`).

## 76. Storage growth measured, and cut by 70% — Phase AB

`scripts/measure_storage.py` drives the production path: `build_app`'s Maintainer with idle cycles at the default cadence, over deterministic questions. It reports total size and, per log, entries, redundant entries and payload bytes. Baseline, 60 questions and 60 idle cycles: **161.4 MB**, with the per-question cost rising from 1.3 MB to 3.9 MB, i.e. quadratic. No write was literally redundant (an identical state). The waste was elsewhere:

| Cause | Fix | Log before → after |
|---|---|---|
| The Belief Graph wrote its **whole state once per node and once per edge** | `CheckpointLog.batch()`: one logical operation, one checkpoint. `record_answer` and `record_source` are each one batch | graph 47.4 → 6.1 MB (510 → 65 entries) |
| Consolidation wrote **once per claim per idle cycle**; fidelity and calibration likewise | the idle commit batches each store | consolidation 24.9 → 1.3 MB; fidelity 2.6 → 0.8; calibration 0.44 → 0.17 |
| The Maintainer's checkpoints carried the **last unit's scratch mirror and a runner record for every unit ever run**, although §56 claimed they stay bounded (known-bugs #34) | `mirror=False` for Maintainer units; runner records dropped with the registry entry | maintainer 46.1 → 10.4 MB; state at rest 48 KB → 0.1 KB |
| The ledger wrote an answer and then its rating as two full-ledger checkpoints | batched, in both paths | index 36.4 → 27.3 MB |

**After: 49.2 MB (−70%).** `batch()` keeps §5.3's rule, since every checkpoint is still a new entry and never an overwrite, and the design already treats checkpoint cadence as configurable. Batching also makes each operation **atomic**: a failure inside a batch writes nothing, instead of leaving half an answer in the graph. Reads inside a batch see its pending writes and return copies, as reads always have. A batch is scoped to one log object.

**What remains is a design question (owner decision 8).** The ledger is now 55% of the total, because every write snapshots the entire ledger (every question, every version), so it still grows quadratically. At the measured rate, roughly 3 writes per question at ~4.4 KB of ledger per question, 1,000 questions would put the ledger alone in the region of 6–7 GB. The Belief Graph is the same shape at a smaller scale. The options change the storage layout or the retention rule, so they're not mine to pick:
- one log per question, so a write costs one question's size;
- delta checkpoints;
- pruning or compacting superseded snapshots, which conflicts with append-only as currently written.

Tests (`tests/test_checkpoint_batching.py`):
- batch semantics: one entry, reads its own writes, invisible to other readers until written, atomic on failure, nests, copies on read, empty batch writes nothing;
- one graph checkpoint per answer and per source;
- an idle cycle writes each of consolidation, fidelity and calibration exactly once while still recording every claim;
- an answered question costs exactly three ledger checkpoints;
- the Maintainer's state at rest is exactly `{"maintenance": …}` with no runner records;
- the measurement script runs.

**Full live suite: 578 passed, 1 skipped.** 579 collected (570 prior + 9 new in `tests/test_checkpoint_batching.py`).

## 77. The narrated demo covers batches 4–5 — Phase AC

`demo_brain.py` gains four steps, run on one Maintainer with calibration, a graph and ingestion; the adversarial suite moves to step 16 as the finale:
- **12:** scheduled ingestion accepts two fixture sources and refuses a paid one without requesting it, and idle evolution now reads the textbook→survey citation from the graph;
- **13:** an idle cycle feeds calibration and reports no drift;
- **14:** the primality source is downgraded; the next cycle samples one claim yet reopens all three prime answers, each saying why;
- **15:** a fault injected into one question's deliberation (restored afterwards) produces two `unit_error` retries and a `unit_failed`, and the question is `suspended` with its error recorded.

The final banner was moved, not duplicated (known-bugs #16). `tests/test_demo_brain.py` still asserts it prints exactly once, at the very end, and now also pins each new step's key outcome.

**Full live suite: 578 passed, 1 skipped** with the new demo, and the demo test re-run on its own after gaining the new assertions: 1 passed. 579 collected, no new tests.

### Explicitly not on this list
Any application-level work beyond what `deployment-playbook.md` promises to deliver (verified SSH access to a correctly-networked guest, not a deployed application).

~~Production sizing/90%+ resource cap~~ — **decided, 2026-09-23, see Section 38**: raised to 80% by explicit user request, not the full 90%+ once floated but a real, stated increase nonetheless.
