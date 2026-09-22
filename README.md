# Athenaeum Body -- Proof-of-Work Slice

A minimal, runnable, tested implementation of the highest-risk structural
guarantees from `body-design.md`: not a full build of the Body, but enough
working code to validate the core ideas and poke at them directly.

## What's actually implemented

- **Content-addressed, tamper-evident storage** (`storage/content_addressed.py`)
  -- objects are keyed by a hash of their own content; corruption/tampering
  is detected on read, not silently served.
- **Append-only, hash-chained checkpoint log** (`storage/checkpoint.py`) --
  every checkpoint is a new entry, never an overwrite; the chain's own
  integrity is independently verifiable.
- **Tiered storage with automatic Tier2 fallback** (`storage/tiered.py`) --
  simulates the NVMe-unreachable -> HDD-fallback -> auto-recovery behavior
  from Section 3.3, without needing real network hardware to test it.
- **Question Ledger** (`ledger.py`) -- submit / get / list, with permanent,
  append-only version history (answers are never overwritten).
- **Single-unit runner with kill-safe resume** (`scheduler/runner.py`) --
  round-boundary checkpointing means a killed process resumes from its last
  completed round, not from scratch.
- **Time-sliced multi-unit scheduler** (`scheduler/multi_unit.py`) --
  priority-ordered round-robin across many concurrent work units, with
  demonstrated cross-unit visibility (one unit's committed write is visible
  to the next unit's round).
- **Optimistic concurrency control** (`concurrency.py`) -- expected-version
  conflict detection plus idempotency-key deduplication, the two mechanisms
  Section 7.5 specifies for the shared-store write path.
- **Config loader with enforced hard invariants** (`config.py`) -- e.g.
  `disallow_paid_apis` cannot be set to `false`, `working_set_floor_gb` must
  be below `local_dram_gb`.

## What's deliberately NOT here yet

Real hardware polling (the resource monitor is a settable stub), the actual
elastic GPU/distributed-core paths, the ingestion pipeline, and everything
in `brain-design.md` (round *content* -- this only runs no-op/demo round
handlers). See `body-design.md` Section 11 for the full task backlog this
slice draws from (roughly Phase 0-3, plus pieces of 3.4/7.5).

No license is included yet -- add one before treating this as anything
other than a private proof of concept.

## Running it

```bash
pip install -e ".[dev]"
python demo.py        # narrated end-to-end walkthrough
pytest -q             # 19 tests covering every guarantee above
```

## Layout

```
src/athenaeum_body/
  config.py              config schema + loader, hard-invariant checks
  schemas.py              core data shapes (Section 5.1)
  concurrency.py           expected-version + idempotency (Section 7.5)
  resource_monitor.py      settable stub + pure scale-down rules (Section 6)
  ledger.py                Question Ledger CRUD
  storage/
    content_addressed.py   CAS with tamper detection (Section 3.4)
    checkpoint.py           append-only hash-chained log (Section 5.3)
    tiered.py                Tier2/Tier3 fallback (Section 3.3)
  scheduler/
    work_unit.py             work-unit / round-handler interfaces (Section 7)
    runner.py                 single-unit runner, checkpoint/resume
    multi_unit.py              time-sliced priority scheduler
tests/                      19 tests, one file per module above
demo.py                     narrated end-to-end walkthrough
```

## Design source

Built against `body-design.md` and `brain-design.md` in the parent project.
This slice intentionally targets the tasks flagged as highest-risk in the
original work breakdown (checkpoint/resume, concurrency, storage integrity)
first, since those are the ones worth validating before investing further.

## Brain slice: the deliberation loop (added after the Body slice)

`src/athenaeum_brain/` implements Section 3's four rounds (framing,
exploration, cross-examination, synthesis) and Section 4.4's proposal-only
commit boundary, running as a real `round_handler` on the **same**
`SingleUnitRunner`/checkpointing engine proven in the Body slice above --
not a separate toy runner. This is deliberate: it proves the Brain/Body
interface contract actually works, not just that deliberation logic exists
in isolation.

Because the Local Model Serving Layer isn't built yet, the two Master
Agents here (`Mathematics`, `Logic`) are deterministic and independently
checkable -- real primality computation and real jurisdiction-validity
checks -- rather than LLM-backed. This validates the *mechanics*
(claim structure, cross-examination, the commit boundary, jurisdictional
dissent instead of false consensus) honestly, without pretending to
validate reasoning quality, which needs the model-serving layer first.

```bash
python demo_brain.py   # narrated walkthrough, including a kill/resume
                        # of an in-progress deliberation
pytest -q               # 28 tests total (19 Body + 9 Brain)
```

Not yet implemented: real Master Agents (Physics/Philosophy/Theology), the
Reputability Engine, re-evaluation, knowledge consolidation, human input,
and everything requiring an actual local model.

### Jurisdictional conflict -> plural answers (Section 4.2)

A third toy agent, `MasterOfEngineering`, was added specifically to
exercise the case `synthesis_round` hadn't tested yet: two agents that
each genuinely, correctly claim jurisdiction over the same question and
reach *different* conclusions (Mathematics's classical round-half-up vs.
Engineering's IEEE-754 round-half-to-even, both real `decimal` module
computations). Synthesis no longer forces a single winner in this case --
it commits both conclusions as a labeled, Logic-chaired plural answer
(Section 4.3: never manufacture false consensus). Claims sharing a demo-only
`topic` field are what triggers conflict detection; production would need a
richer mechanism (an open question, not resolved here). See step 4 of
`demo_brain.py` for the full example.

## (a) Conflict detection: subject-based, not topic-string coordination

Agents no longer share a hardcoded label to detect conflicts -- each
independently sets `subject` (the specific value/entity it's reasoning
about), and `synthesis_round` groups by *normalized* subject (numeric
equality via `decimal`), so differently-formatted references to the same
thing ("2.5" vs "2.50") still correctly conflict-group. This is still a
simplification -- general semantic "same underlying question" detection
needs the model-serving layer below -- but it's a real step away from
agents needing to coordinate on exact strings in advance.

## (b) Local Model Serving Layer stub (`src/athenaeum_body/model_serving.py`)

No GPU/network here to validate real backends against, so this proves the
*mechanics* of Section 4.5: a content-addressed model registry (tamper
detection reused from 3.4), a router that never lets callers address a
backend directly, VRAM-budget-aware LRU eviction, and transparent
GPU-unavailable -> CPU-fallback redirection. A real vLLM/llama.cpp adapter
just needs to satisfy the same `Backend` protocol (`load`/`unload`/`infer`)
that `MockBackend` implements here.

## (c) Hardening docs

`tech-stack.md`, `schemas.md`, `config.defaults.yaml`, and
`acceptance-criteria.md` close out the gaps flagged in the last
architecture-readiness review -- a committed stack, field-level schemas,
filled config defaults, and checkable pass/fail criteria for the
highest-risk tasks specifically (not yet all ~47).

Tests: 40 total (19 Body storage/scheduling + 8 Brain rounds/agents +
6 Brain integration + 6 model-serving + 1 misc).

## Wrap-up: acceptance criteria extended, remaining gaps closed

`acceptance-criteria.md` now covers essentially the full backlog, not just
the highest-risk subset. Doing this surfaced two real gaps that had no
tests at all -- `schemas.py` (Task 2) and `resource_monitor.py` (Tasks
8-10) -- both closed, including a genuine end-to-end test that a DRAM-
floor breach actually stops a running unit's rounds (not just flags a
state), and resumes it cleanly once headroom returns.

Also closed: the ingestion pipeline's mechanics (Tasks 14-17,
`ingestion.py`) -- license/ToS/paid-access checks, parse/normalize into
the Provenance schema, and running as an ordinary scheduled work unit, no
special-casing. Real network access isn't available here, so `fetch()`
takes a `FixtureSource` standing in for a real HTTP fetch -- the same
substitution pattern already used for `MockBackend` and
`simulate_tier2_outage()`.

**What's left is now genuinely blocked on infrastructure this sandbox
doesn't have**, not just unscheduled: GPU-vs-CPU output-equivalence
testing (needs real GPU access) and distributed worker dispatch (needs a
second process/host). Everything else backend-independent in the original
~47-task backlog is implemented and tested.

Tests: 56 total.

## Remote access: API server + mobile web client

`src/athenaeum_body/api.py` is a stdlib-only HTTP server (no new
dependencies) exposing the deliberation engine, and serving `client/`
(a single-file, mobile-responsive web page) on the same origin:

```bash
python -m athenaeum_body.api          # from src/, or add src/ to PYTHONPATH
# -> http://0.0.0.0:8080
```

Open that address from your phone on the same LAN, or forward/tunnel the
port (e.g. `ssh -R`, Tailscale, a reverse proxy on the Proxmox host) for
access from anywhere. The client has no build step and no external
dependencies -- open `client/index.html` directly if you just want to look
at it, though it needs the API reachable at the same origin to actually work.

**Known limitation, stated plainly:** every request is handled
synchronously, which only works because the toy deliberation loop
finishes in milliseconds. Once real LLM-backed agents exist (Section 4.5),
this needs to become async (submit -> poll `/api/questions/<id>`) to match
the Question Ledger's `queued/active/completed` lifecycle that's already
modeled in `ledger.py` but not yet exposed that way over HTTP.

Tests: 61 total (5 new, hitting a real running server, not mocks).

## The recommended trio: real Logic, Reputability storage, materiality

**Real Logic validity-checking** (`logic_engine.py`): Logic finally does
what Section 2.2 says it does -- checks argument FORM via brute-force
propositional truth-table enumeration (general, not a fixed fallacy
lookup table), returning a real counterexample when invalid. Wired into
`MasterOfLogic.cross_examine` via an optional `Claim.argument` field.

**Reputability Engine storage mechanics** (`reputability_store.py`,
Body-owned): versioned grading, evidence accumulation from cross-
examination outcomes, an append-only dispute log. The grading *policy*
(`_grade_from_tally`) is an explicitly-labeled placeholder -- real
judgment needs a model. Wired into `loop.py`'s synthesis round with the
actual non-retroactive-attachment sequencing: snapshot each cited
source's grade BEFORE recording this deliberation's own outcome, so a
later grade change can never rewrite what an earlier answer said it
relied on. Proven with two real deliberations in
`test_reputability_integration.py`, not just asserted.

**Re-evaluation materiality** (`reevaluation.py`): a pure function over
synthetic Belief Graph deltas, exactly as Section 7.2 specifies. "Newly
contested/rejected" is material regardless of magnitude; smaller shifts
are material only past a configurable ordinal threshold; no live grade
available is correctly NOT treated as a change.

`demo_brain.py` step 5 walks the full connected arc: a fallacious
argument gets caught by real Logic, which downgrades a source's
reputability, which the materiality test then correctly flags as grounds
to reopen a *different*, earlier answer that cited the same source.

13 new tests (82 total).

## Knowledge consolidation and domain fidelity (4 and 5)

**Knowledge consolidation** (`consolidation_store.py` Body-owned,
`consolidation.py` Brain judgment): the Tier B -> Tier C promotion
criteria from Section 10.2, implemented exactly, including the specific
rule the design calls out -- a claim can meet the survival-cycle and
independent-source thresholds and STILL be excluded from promotion if
its confidence trend is declining, even though it hasn't been overturned
yet (`test_declining_confidence_blocks_promotion_even_if_counts_met`).
Compaction archives the full trace content-addressed (reusing 3.4's
tamper detection) and never deletes it; de-compaction recovers it intact.
Proven against 5 REAL repeated deliberations, not synthetic data.

**Domain fidelity monitoring** (`domain_fidelity_store.py` Body-owned,
`domain_fidelity.py` Brain judgment): the two independent drift signals
from Section 2.4.1 -- jurisdictional overreach rate (reusing the exact
challenge pattern `MasterOfLogic` already produces) and reasoning-
fingerprint deviation (a per-agent style marker: does Mathematics still
cite `computed:` provenance, does Logic still stay procedural-only) --
combined into one tracked score, with a rolling-baseline drop detector
that flags review rather than silently correcting anything (Section
2.4.3). `demo_brain.py` step 7 shows a real, healthy Mathematics score
(1.0) against a simulated drifted one (0.5), correctly triggering review.

18 new tests (99 total), including two integration tests running the
real deliberation engine repeatedly and feeding its actual claim logs
into both modules.

## Sandbox security review (6)

`security-review-sandbox.md` — the review `body-design.md` Section 4.6
said had to happen before Task 23g could be responsibly implemented.
Design-only, no code: a threat model (five ranked failure modes, from
host compromise down to the easy-to-miss "false-positive containment"
case), six required properties with the reasoning behind each (not just
a checklist), and eight concrete fault-injection scenarios that must
each have a passing automated test before `execution_sandbox.enabled`
can move from its current default of `false`. Linked from
`acceptance-criteria.md`'s existing Task 23g entry.

## Task 23g: sandboxed execution -- started, honestly scored, still disabled

`src/athenaeum_body/sandbox.py`: real OS-level isolation (`unshare` +
`chroot` into a minimal, freshly-built root -- not a restricted
interpreter), built and tested against every scenario in
`security-review-sandbox.md`. This environment turned out to have real
privilege (root, `CAP_SYS_ADMIN`, working namespaces), so the reference
implementation is genuine, not a stub.

**6 of 8 scenarios pass exactly as specified.** Network egress,
filesystem containment, memory limits, environment scrubbing, and
scratch-directory freshness are all real, structural, OS-enforced
guarantees -- verified by actually running each attack, not asserting it
would fail. **2 gaps, stated plainly, not hidden:** CPU-time and
fork-count containment both rely on an external wall-clock `timeout -s
KILL` rather than the in-process `RLIMIT_CPU`/`RLIMIT_NPROC` originally
specified, because those specific rlimits' signal delivery (`SIGXCPU`)
reliably breaks `unshare --fork`'s own signal handling in this specific
container environment -- a reproducible, documented finding, not a
guess. Full scorecard and reasoning: `security-review-sandbox.md`
Section 7.

**`execution_sandbox.enabled` stays `false`.** Passing these tests
doesn't authorize enabling real execution against untrusted input on its
own -- that was true before this implementation existed and remains true
now, exactly as the review's own Section 5 says it should.

Three real bugs caught before delivery, each a genuine "looked right,
wasn't" moment worth knowing about: (1) `env={}` passed to the *outer*
orchestration command wiped `PATH`, breaking `unshare`'s own ability to
find `chroot` -- fixed by scrubbing environment from *inside* the
bootstrap instead, exactly where the guarantee needs to hold, not at the
orchestration layer; (2) `chroot` lives in `/usr/sbin`, not `/usr/bin` --
a minimal `PATH` had the wrong directory; (3) Python's `subprocess`
reports a signal-killed process as a *negative* returncode (`-9` for
SIGKILL), not the shell's `128+signal` convention (`137`) -- the
timeout-detection logic was checking for the wrong number entirely.

8 new tests (108 total). **Needs `CAP_SYS_ADMIN` to run** -- will not
pass in an unprivileged CI runner without extra setup; noted here rather
than discovered by a confusing CI failure later.

## Continuing 23g: closing the fork-containment gap for real

Didn't leave the two gaps from the last session as permanent -- went
back and investigated further. **Fork containment is now closed**: a
real cgroups `pids` controller does work in this environment (confirmed
by a minimal test outside any of this module's code), but wiring it into
`sandbox.py` initially had a genuine race condition -- the sandboxed
process was joined to the cgroup *after* `Popen()` returned, by which
point a tight `fork()` loop can complete entirely before the controlling
code gets around to it. Fixed by joining from `preexec_fn`, which runs
synchronously in the child before it execs into anything. Verified
stable across repeated runs, not just a single lucky pass.

**CPU-time enforcement remains genuinely open** -- confirmed, via a
minimal reproduction with no chroot or other namespaces at all, that
`unshare --fork` itself crashes on `SIGXCPU` delivery in this container
environment. That rules out this module's own composition as the cause;
it's an environment limitation. The external wall-clock `timeout -s
KILL` mitigation stands as the real enforcement mechanism for CPU-bound
code. Full corrected scorecard: `security-review-sandbox.md` Section 7.

**7 of 8 scenarios now pass exactly as originally specified.**
`execution_sandbox.enabled` still stays `false`.

1 new test (109 total).

## Before deploying to real hardware: run the preflight check

`scripts/preflight_check.py` -- standalone (stdlib only, no repo import
needed) re-validation of every scenario in `security-review-sandbox.md`,
including the isolated `RLIMIT_CPU`-under-`unshare --fork` reproduction
that determined this environment's one open finding. Run it on any new
deployment target -- a fresh Proxmox VM or LXC, bare metal -- before
trusting the scorecard in `security-review-sandbox.md` Section 7 to
carry over:

```bash
sudo python3 scripts/preflight_check.py
```

If `RLIMIT_CPU` turns out to work correctly on that kernel (unlike the
reference environment this was developed against), that's a genuine
capability upgrade -- update `security-review-sandbox.md` Section 7
accordingly rather than assuming the limitation is universal. Exit code
0 means every scenario passed as specified; exit 1 means read the
summary (a non-zero exit isn't automatically "unsafe," since the CPU
finding has a known-good fallback already built into `sandbox.py`).
