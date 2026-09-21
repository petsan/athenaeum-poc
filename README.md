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
