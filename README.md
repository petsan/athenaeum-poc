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
