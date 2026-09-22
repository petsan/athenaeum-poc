# Athenaeum — Progress Snapshot

**Purpose of this file:** a resumable checkpoint of where the project stands. Read this first in any new session before touching the design docs or the repo.

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

**109/109 tests passing** (Body storage/scheduling/API/sandbox + Brain deliberation/agents/reputability/consolidation/domain-fidelity), verified by actually running the suite before each delivery, not just writing it.

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

`known-bugs.md` — sixteen real bugs from across this project's development, catalogued by category with root cause, fix, and generalizable lesson: shell/OS gotchas (dash vs. bash, `PATH` scrubbing at the wrong layer, `subprocess`'s signal-return convention), namespace-isolation findings (`RLIMIT_NPROC` silent non-enforcement, `RLIMIT_CPU`/`SIGXCPU` crashing `unshare --fork`, a real cgroup-join race condition), storage correctness (checkpoint hash-before-field-attached, `verify_chain` not checking payload content), one API data-shape bug, four test-authoring mistakes, one corrected documentation claim, and one recurring workflow mistake (the duplicate final-print bug, which happened twice — flagged explicitly since catching it once didn't prevent the repeat). Linked from the README, meant to be read before similar work, not just consulted after something breaks.

Eighteen commits total.

## 20. Suggested next step

Still waiting on the Proxmox server. Once it's up: run `preflight_check.py` there first, before deploying anything else. If `RLIMIT_CPU` turns out to work on that kernel, `sandbox.py` gets a small, well-defined change (switch it back to primary CPU-time enforcement, keep wall-clock as a backstop) — otherwise, no code change needed, current behavior already matches. Either way, that single run resolves the last open question in Task 23g.
