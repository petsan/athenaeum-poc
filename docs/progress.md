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
- [ ] **Infra topology for brainboxes** — `docs/infra-topology.md` written (XSmall/Medium/Large/XLarge tiers, shared-memory architecture). Template script (`infra/proxmox/03-create-project-guest.sh` extended with a `--tier` flag) not yet built — next up.
- [x] Output Types (`brain-design.md` §5.4, Work Breakdown Phase 7) — `src/athenaeum_brain/output_types.py`: classification (`classify_output_type`) wired into `framing_round`; Research Answer builder wired into `loop.py`'s synthesis round; Forecast and Recommendation builders complete and tested standalone (not yet wired to a producing agent — none exists yet that emits the needed structure); non-collapsing multi-type composition (`compose_answer`). Forecast-resolution-always-material wired into `reevaluation.forecast_is_material`. 13 new tests. See Section 28 and `docs/brain-session-log.md`.
- [x] Human input workflow (`brain-design.md` Section 11, Phase 13) — `human_checkpoint_store.py` (Body) + `human_input.py` (Brain): submission structure with required justification/declared_scope (11.1), low-weight-not-rejected handling of unjustified input, submitter track record reusing `ReputabilityStore`'s existing generic `subject_type` (11.3, no new mechanism needed), `human_input_is_material` (11.5), `pending_human_checkpoint`→`current` lifecycle with Reviewer-role gating and conflict-of-interest enforcement (11.7). 18 new tests. See Section 29 and `docs/brain-session-log.md`. One real, honestly-scoped limitation: today's toy agents' cross-examine methods only pattern-match their own claim formats, so a human_input claim's free-text statement currently survives cross-examination unchallenged by default, not because it was actually evaluated on its merits — flagged, not hidden.
- [x] Engineering agent real specify→implement→execute→verify loop + Model Fitness (Phase 15) — `MasterOfEngineering.verify_code()`/`verify_claim()` (real, unmocked `sandbox.run_sandboxed()` calls, confidence tied directly to actual exit code/stdout); `serving_model` field added to `Claim` and threaded through Engineering's claims; `model_fitness_store.py` (Body) + `model_fitness.py` (Brain) with cold-start Open Question 10 resolved via Laplace smoothing (0.5 at zero evidence). 15 new tests, including real sandbox executions of known-correct and known-buggy code. See Section 30 and `docs/brain-session-log.md`.
- [x] Content Integrity enforcement (Phase 14, §12) — `content_integrity.py` (Brain): §12.1's core rule verified *by construction* via a structural scan (no `eval`/`exec` in any Brain claim-handling module) plus an end-to-end adversarial-submission test through the real pipeline; §12.3's advisory instruction-like-content heuristic, wired to contribute exactly one ordinary reputability "challenged" outcome per detection (Open Question 8's resolution: same weight as any other cross-examination challenge, never an automatic gate). 7 new tests. See Section 31 and `docs/brain-session-log.md`.
- [x] Evaluation Infrastructure (Phase 9b) — `calibration_store.py` (Body) + `evaluation.py` (Brain): `run_ground_truth_benchmark()` (§9.1, real loop runs); `run_adversarial_suite()` covering 6 of §8's 16 named failure modes with real, checkable mechanisms (rest genuinely blocked on a real model backend, stated explicitly, not silently under-covered); `calibration_report()` (§9.3); `b0_retrieval_only()`/`a1_full_workflow()`/two required ablations (§9.7, B1 explicitly flagged blocked); `check_integrity_gates()` (§9.8, pass/fail non-compensatory); §9.9 contamination isolation verified by construction (ingestion.py has no import of evaluation.py). One real, non-obvious finding: the "remove reputability weighting" ablation is currently indistinguishable from A1, because `synthesis_round` doesn't yet numerically reweight confidence by reputability grade — a genuine gap between §6.7's design intent and today's wiring, logged rather than glossed over. 16 new tests. See Section 32 and `docs/brain-session-log.md`.
- [x] **Ingestion pipeline's real network fetch** — `fetch_url()` added to `ingestion.py`: a real stdlib-only (`urllib`) HTTP GET plus a real robots.txt check, no new dependency, never sends credentials/API keys (Section 6.6). `FixtureSource` kept as the shared normalized shape both a real fetch and a hand-authored test fixture produce, rather than renamed. `license`/`is_paid_or_metered` remain caller-supplied, since neither is mechanically derivable from an HTTP response. 6 new tests, including real live fetches from LXC 104 and a real DNS-failure case (`.invalid` TLD, RFC 2606). See Section 33 and `docs/brain-session-log.md`.
- [x] **Task 23 (distributed worker dispatch)** — `distributed_worker.py` (Body, deliberately Brain-agnostic: no import of `athenaeum_brain` anywhere, matching `loop.py`'s own layering): `serve_worker()`/`remote_round_handler()`, stdlib-only HTTP, a drop-in `RoundHandler` so `SingleUnitRunner`/the scheduler need zero changes to run a distributed unit. Tested against a genuinely separate OS process (not a thread), with a real `terminate()` mid-deliberation proving Section 4.2's "loss of a worker mid-task simply requeues the unit" for real, not simulated. 4 new tests. See Section 34 and `docs/brain-session-log.md`.
- [ ] Tasks 21/22 (GPU-vs-CPU output equivalence) remain genuinely blocked — this host has no GPU (confirmed via the node status API, Section 22).
- [x] **Local Model Serving Layer now has a real backend.** `LlamaCppBackend` (`model_serving.py`) talks to the six live model-lab guests over HTTP (stdlib `urllib`); `model_lab_registry.py` wires all six into a `ModelRegistry`. `ModelServingLayer.request()` proven for real (CPU fallback path, `gpu_available=False` — the honest current topology, no GPU pool exists). `evaluation.py`'s B1 baseline (§9.7) is real for the first time — `b1_single_agent_baseline()` — no longer `B1_UNAVAILABLE`. No Master Agent is wired to use this for its own claims yet (still deterministic toy logic) — that's the next real step, not done here. See Section 36.
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

### Explicitly not on this list
Production sizing/90%+ resource cap — the user's own stated plan is to raise the 50% cap once this project goes live, but that's a "when going live" decision to make explicitly at the time, not a current task. Also not on this list: any application-level work beyond what `deployment-playbook.md` promises to deliver (verified SSH access to a correctly-networked guest, not a deployed application).
