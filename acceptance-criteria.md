# Acceptance Criteria — Highest-Risk Tasks

`body-design.md` Section 11's ~47 tasks mostly describe intent ("verify identical state reconstruction on resume") without a checkable pass/fail line. Full coverage of every task is future work; this covers the tasks flagged highest-risk in the original backlog, since those are the ones worth pinning down precisely before further implementation.

| Task | Acceptance criterion |
|---|---|
| 7a — content-addressed storage | `get()` on unmodified content returns identical bytes; `get()` on content modified after write raises `IntegrityError`; two `put()` calls with identical bytes return the same key and do not create a second stored object. *(All three — implemented and passing in `test_content_addressed.py`.)* |
| 7 — checkpoint log | `verify_chain()` returns `True` on an untouched chain of N>1 entries; raises on a chain with any entry's metadata OR payload corrupted; `last_good_snapshot_id()` returns the entry immediately before a corrupted one. *(Implemented and passing in `test_checkpoint.py`.)* |
| 12/13 — single-unit runner, resume | A unit killed after round K and resumed via a **freshly constructed** runner/log pair (no shared in-memory state) continues at round K, not round 0; the final committed state is identical to an uninterrupted run. *(Implemented and passing in `test_runner_resume.py`, `test_brain_integration.py`.)* |
| 18 — time-sliced scheduler | Given units of equal priority, `process_one_round()` processes them in FIFO submission order; given unequal priority, always pops the highest-priority queued unit first, verified even when a lower-priority unit was submitted earlier. *(Implemented and passing in `test_multi_unit.py`.)* |
| 19 — cross-unit visibility | A write committed by unit A's round N is present in the shared state passed to unit B's round N+1 (not merely "eventually" — the very next round). *(Implemented and passing.)* |
| 20a — expected-version + idempotency | A write with a stale `expected_version` raises `ConflictError` and does not mutate state; a write retried with the same `idempotency_key` returns the original result and does not increment the version a second time. *(Implemented and passing in `test_concurrency.py`.)* |
| 23d — VRAM LRU eviction | Requesting a model that doesn't fit in remaining VRAM evicts the least-recently-*requested* (not least-recently-loaded) model first; a model touched by a request is protected from eviction ahead of one that wasn't. *(Implemented and passing in `test_model_serving.py`.)* |
| 23g — sandbox isolation *(not yet implemented)* | An execution attempting network access fails closed with no partial success; an execution exceeding `cpu_time_limit_seconds`/`memory_limit_mb` is terminated and produces no `executable`-typed claim; state does not persist between two separate invocations. **Blocked on the dedicated security review flagged in `body-design.md` Section 4.6 — do not implement against this criterion alone without that review.** |

**Not yet covered:** the remaining ~40 tasks in the full backlog. Extend this table before implementing each, rather than writing code first and inferring criteria after.
