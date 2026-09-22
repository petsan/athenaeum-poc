# Effort Estimate: Athenaeum — The Body

**Status:** Estimate for planning purposes only
**Scope:** The 26-task Body work breakdown (Phases 0, 1, 2, 3, 6, 7, 9, 10) from `body-design.md`. Does not cover the Brain.
**Assumed execution model:** Tasks are executed one at a time, non-concurrently, by an AI agent, each producing one reviewable artifact (code + tests) per the rules in the original task-breakdown proposal. A human reviews and merges each task before the next begins.

---

## 1. Methodology & units

Because this work is AI-executed rather than done by a human team typing code, "person-months" is the wrong unit. Instead each task is rated on three axes:

- **Complexity (S / M / L):** how much design reasoning and how many edge cases the task involves, independent of who's typing.
- **AI sessions (est.):** the number of distinct AI working sessions realistically needed to reach a passing, reviewable state — includes the AI's own iteration (write → test → fix), not just a first draft. One session ≈ one focused attempt at one task with room to course-correct once or twice.
- **Human review effort:** rough hours a competent reviewer needs to actually verify the artifact does what it claims — this is the real bottleneck in an AI-driven pipeline, not generation speed.
- **Risk:** likelihood the task reveals a design gap that sends work backward (into a prior task or into `body-design.md` itself), rated Low/Medium/High.

Elapsed calendar time is **not** estimated per task, because it depends entirely on reviewer availability and how much rework risk materializes — that's called out separately in Section 4.

---

## 2. Per-task estimate

### Phase 0 — Scaffolding & Contracts
| # | Task | Complexity | AI sessions | Human review (hrs) | Risk |
|---|---|---|---|---|---|
| 1 | Repo structure, config schema + loader/validator | S | 1 | 0.5–1 | Low |
| 2 | Core data schemas (Belief Graph, Provenance, Question Ledger, Reputability grade) + serialization tests | M | 1–2 | 1–2 | Low |
| 3 | Work-unit / round-handler interface + no-op implementations | S | 1 | 0.5–1 | Low |
**Phase 0 subtotal:** 3–4 sessions, 2–4 review hours

### Phase 1 — Storage Layer
| # | Task | Complexity | AI sessions | Human review (hrs) | Risk |
|---|---|---|---|---|---|
| 4 | Tier 1 boot-load (config from local path) | S | 1 | 0.5 | Low |
| 5 | Single-tier local KV store + test corpus | M | 1–2 | 1–2 | Low |
| 6 | Tiered read/write (Tier 2 preferred, Tier 3 fallback) + mocked unreachability harness | M–L | 2–3 | 2–3 | Medium — fallback/failback logic is easy to get subtly wrong |
| 7 | Append-only checkpoint writer + snapshot IDs for all five stores | L | 2–3 | 2–3 | Medium — this underlies everything downstream; worth extra review time |
**Phase 1 subtotal:** 6–9 sessions, 6–8.5 review hours

### Phase 2 — Resource Monitor & Elasticity
| # | Task | Complexity | AI sessions | Human review (hrs) | Risk |
|---|---|---|---|---|---|
| 8 | Resource monitor (polling + state API) | M | 1–2 | 1 | Low |
| 9 | Scale-down reaction rules (pure functions, synthetic inputs) | M | 1–2 | 1–2 | Low |
| 10 | Checkpoint-and-suspend on simulated DRAM-floor breach + resume verification | L | 2–3 | 2–3 | Medium — "verify identical state" is the actual hard part, not the trigger |
**Phase 2 subtotal:** 4–7 sessions, 4–6 review hours

### Phase 3 — Question Ledger & Single-Unit Scheduler
| # | Task | Complexity | AI sessions | Human review (hrs) | Risk |
|---|---|---|---|---|---|
| 11 | Question Ledger CRUD | S–M | 1 | 1 | Low |
| 12 | Single-work-unit runner against no-op handlers | M | 1–2 | 1 | Low |
| 13 | Round-boundary checkpointing + kill/resume verification | L | 2–3 | 2 | Medium |
**Phase 3 subtotal:** 4–6 sessions, 4 review hours

### Phase 6 — Ingestion Pipeline (mechanical)
| # | Task | Complexity | AI sessions | Human review (hrs) | Risk |
|---|---|---|---|---|---|
| 14 | Fetch + license/ToS check module | M | 1–2 | 1–2 | Medium — legal/ToS edge cases benefit from human eyes regardless of who wrote the code |
| 15 | Parse/normalize into Provenance schema | S–M | 1 | 1 | Low |
| 16 | Wire ingestion as scheduled background work-unit type | S | 1 | 0.5–1 | Low |
| 17 | One-time foundational corpus seed-load task | S | 1 | 0.5–1 | Low — mechanical once 14–15 exist |
**Phase 6 subtotal:** 4–5 sessions, 3–5 review hours

### Phase 7 — Concurrency
| # | Task | Complexity | AI sessions | Human review (hrs) | Risk |
|---|---|---|---|---|---|
| 18 | Time-sliced priority scheduler (single-writer, round-robin) | L | 3–4 | 3–4 | **High** — flagged in the design doc as the highest-risk task; build and review in isolation |
| 19 | Cross-unit visibility test | M | 1–2 | 1–2 | Medium — depends entirely on 18 being right |
| 20 | True parallel execution + conflict-safe write path | L | 3–5 | 3–5 | **High** — concurrency bugs here are the kind that pass tests and fail in production |
**Phase 7 subtotal:** 7–11 sessions, 7–11 review hours — **budget extra review time here regardless of task count**

### Phase 9 — Acceleration & Distributed Compute
| # | Task | Complexity | AI sessions | Human review (hrs) | Risk |
|---|---|---|---|---|---|
| 21 | CPU-only baseline for embedding/retrieval | M | 1–2 | 1 | Low |
| 22 | GPU-accelerated path + output-agreement test | M–L | 2–3 | 1–2 | Medium — depends on actual GPU hardware access during dev, not just code review |
| 23 | Distributed worker dispatch + simulated-failure requeue test | M–L | 2–3 | 2 | Medium |
**Phase 9 subtotal:** 5–8 sessions, 4–5 review hours

### Phase 10 — Integration & Fault Injection
| # | Task | Complexity | AI sessions | Human review (hrs) | Risk |
|---|---|---|---|---|---|
| 24 | End-to-end cold-boot → seed → N concurrent units → completed test | M | 2 | 1–2 | Medium — first real integration point, likely surfaces issues from earlier phases |
| 25 | Fault-injection suite (Tier 2 loss, 1-core, DRAM floor, mid-round kill) | L | 3–4 (roughly one per scenario) | 3–4 | Medium–High — this is where earlier "Low risk" tasks get their real test |
| 26 | Long-run soak test | M | 1–2 to build, plus real elapsed run time (not AI session time) | 1–2 to interpret results | Medium — outcome depends on wall-clock soak duration, not effort |
**Phase 10 subtotal:** 6–8 sessions (+ soak run time), 5–8 review hours

---

## 3. Totals

| Phase | AI sessions | Human review hours |
|---|---|---|
| 0 — Scaffolding | 3–4 | 2–4 |
| 1 — Storage | 6–9 | 6–8.5 |
| 2 — Elasticity | 4–7 | 4–6 |
| 3 — Ledger/Scheduler | 4–6 | 4 |
| 6 — Ingestion | 4–5 | 3–5 |
| 7 — Concurrency | 7–11 | 7–11 |
| 9 — Acceleration | 5–8 | 4–5 |
| 10 — Integration | 6–8 | 5–8 |
| **Total** | **39–58 AI sessions** | **35–51.5 review hours** |

---

## 4. What this doesn't tell you: calendar time

Session counts and review hours don't translate directly into a delivery date, for three reasons specific to this execution model:

1. **Strict sequencing.** Per the non-concurrency rule, task N+1 shouldn't start until task N is merged. If review turnaround is the bottleneck (e.g., one reviewer, a few hours a day), 39–58 sequential review cycles at even 1 per day is **8–12 weeks minimum**, independent of how fast the AI itself generates code.
2. **Rework risk is concentrated, not evenly spread.** Phases 1, 7, and 10 carry Medium–High risk ratings; a design gap surfaced there can bounce work back into `body-design.md` itself or into earlier tasks (e.g., a Phase 7 concurrency bug might reveal that the Phase 1 checkpoint schema doesn't actually support atomic multi-store writes). Budget 20–30% schedule contingency concentrated around those phases, not spread evenly across all 26 tasks.
3. **Phase 10, task 26 has a real-world clock, not an effort clock.** A soak test's value comes from elapsed idle time, not work done — plan its calendar duration separately from its (small) effort cost.

**Rough planning range, one reviewer, no parallelism, normal availability:** **8–14 weeks** from a standing start to a fully integrated, fault-tested Body, assuming no major rework cycles. Add 2–4 weeks of contingency if Phase 7 or Phase 1 surfaces a real design revision.

---

## 5. Key assumptions

- One human reviewer is the bottleneck resource; no parallel review streams.
- "AI session" assumes a capable coding agent with test-running ability, not just code generation — sessions without test execution should be assumed to need more of them.
- GPU/distributed-hardware tasks (22–23) assume the actual hardware described in the infrastructure inventory is reachable during development; if it isn't yet provisioned, those tasks block on procurement/access, not on effort.
- This estimate excludes any Brain-side work entirely, including the interfaces the Brain will eventually need to satisfy — those are assumed stable as defined in `body-design.md` Section 7 and unlikely to need Body-side rework once the Brain begins, though that assumption itself carries some risk.

---

*End of estimate. This document is a planning aid only and will not be revisited until Body work resumes.*
