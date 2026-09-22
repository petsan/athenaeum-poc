# Design Document: "Athenaeum" — A Slow, Deep-Reasoning, Memory-Resident Knowledge System

**Status:** Draft for architectural review (rev. 2 — resolves reputability governance and adds concurrency model)
**Scope:** Infrastructure, resource elasticity, cognitive architecture, and operational policy. No implementation in this document.

---

## 1. Purpose and Design Philosophy

Athenaeum is not designed to be fast. It is designed to be *right, eventually*. Its founding premise is that some questions — in physics, mathematics, logic, philosophy, and theology — deserve a reasoning process that resembles a scholar working for a day in a well-stocked library, not a chatbot answering in two seconds.

Core design tenets:

1. **Depth over latency.** The system's default posture is deliberation measured in hours, not milliseconds. Speed is never optimized for; correctness, completeness of consideration, and epistemic honesty are.
2. **All-in-memory, state-persistent.** The model's working knowledge, its evolving conclusions, and its reasoning traces live in RAM while active, and are checkpointed to durable storage so the "mind" can be suspended and resumed without loss of continuity — more like hibernating an organism than restarting a process.
3. **Elastic, not brittle.** Compute, memory, and storage available to the system are expected to change unpredictably (Proxmox host contention, network storage going away, GPUs being reclaimed by other workloads). The system must degrade gracefully rather than fail, all the way down to a single CPU core, provided its full memory allocation remains available.
4. **Evolving over static.** The system continues to refine its own knowledge graph and belief state between queries, using idle cycles to re-derive, cross-check, and reconcile what it "knows."
5. **Bounded by law and license, not by budget.** It draws only on freely available, reputable sources. It does not call paid, metered APIs of any kind. Its constraint on token usage is *never* an artificial cap — the constraint is time, hardware, and legality.
6. **Domain-specialized cognition.** Rather than one monolithic reasoning process, Athenaeum organizes its thinking under a small number of "Master Agents," each rooted in a classical discipline, who collaborate and adjudicate disagreements.
7. **Self-governing reputability.** The system is responsible for building, applying, and continuously revising its own standard of what counts as a reputable source — this authority is not delegated externally (Section 8.4).
8. **Perpetually concurrent and never forgetful.** Many questions may be in flight at once, they cross-pollinate through shared state, none is ever discarded, and important answers are allowed to change as the system's understanding evolves (Section 9).

---

## 2. Hardware & Infrastructure Inventory

The system must be designed against a *baseline* footprint and an *elastic ceiling*. Nothing in the design may assume the ceiling is available; everything must degrade to the baseline.

| Resource | Baseline (guaranteed) | Elastic ceiling (opportunistic) | Notes |
|---|---|---|---|
| Compute (local) | 1 core | 40 cores | Proxmox VM/LXC on local hypervisor |
| Compute (distributed) | 0 cores | ~200 cores | Remote pool, network-dependent, may vanish |
| Memory (local, DDR3) | 512 GiB (must be guaranteed at all times) | 512 GiB fixed | This is the one resource treated as non-negotiable |
| Memory (distributed DRAM pool) | 0 | ~1 TiB | Network-attached, used for overflow/cache, not authoritative state |
| GPU | 0 | 10 GPUs / 240 GB VRAM combined | Opportunistic acceleration only, never load-bearing |
| Local bulk storage | 500 TiB spinning HDD | fixed | Cold archive, corpora, checkpoints |
| Local boot storage | SSD array | fixed | OS + database image, loaded at boot |
| Network high-speed storage | 50 TiB NVMe (via LAN) | fixed, but *availability* is not guaranteed | Hot working set, indices |
| Virtualization layer | Proxmox VE | — | Host for the primary VM/LXC and any orchestrated worker nodes |

**Design consequence:** The 512 GiB local DRAM is the *only* resource the system is allowed to treat as a hard dependency. Every other resource — cores beyond 1, the NVMe tier, the distributed pool, the GPUs — must be modeled as *optional accelerators* that can appear or disappear at runtime without corrupting or losing state.

---

## 3. Storage Tier Architecture

Athenaeum uses a four-tier storage model, ordered by speed and volatility:

```
Tier 0 — DRAM (local, 512 GiB)         : live working memory, active reasoning state
Tier 1 — Boot SSD array                : OS image, database engine, hot config, fast restart
Tier 2 — NVMe over LAN (50 TiB)        : hot corpus shards, embedding indices, recent checkpoints
Tier 3 — Local spinning HDD (500 TiB)  : cold archive — full corpus, full checkpoint history, logs
```

### 3.1 Boot behavior
- On boot, a minimal OS + the persistence/database engine is loaded from the local SSD array. This SSD array is treated purely as a *bootstrap and system* volume — not as long-term knowledge storage.
- After boot, the database engine reconstructs the most recent in-memory state (Section 5) by streaming the latest checkpoint from Tier 2 (preferred, fast) or Tier 3 (fallback, slow) into DRAM.
- Boot is itself a "resume from hibernation," not a cold start: the system always attempts to reload its evolved knowledge state rather than beginning from an untrained baseline, unless an explicit "genesis" flag is set (see Section 10, `bootstrap_mode`).

### 3.2 Tier roles
- **Tier 0 (DRAM):** the only tier in which active reasoning happens. All Master Agents' working sets, the active belief graph, and in-flight deliberation traces live here.
- **Tier 1 (SSD):** immutable-ish system image; also used as an emergency local checkpoint target if network storage (Tier 2) is unreachable and Tier 3 write bandwidth is saturated.
- **Tier 2 (NVMe/LAN):** the primary read/write cache for corpus shards being actively consulted, and the primary checkpoint destination during normal operation, due to its speed advantage over Tier 3.
- **Tier 3 (HDD):** the system of record. Every checkpoint that lands on Tier 2 is asynchronously replicated to Tier 3. The full historical corpus and the full history of the belief graph's evolution (an append-only log, not just latest-state) lives here. Tier 3 is assumed reliable but slow; it is never on the critical path for a single reasoning step, only for durability.

### 3.3 Availability assumptions
- Tier 2 (network NVMe) is explicitly *not* guaranteed available. The system must detect its absence and fall back to Tier 3 reads/writes with degraded (but functioning) performance, and must resume preferring Tier 2 automatically when it reappears (no manual failback).
- Tier 0 is the only tier assumed always available for the life of a "waking" session; if Tier 0 memory itself is reduced below the working-set floor (Section 7), the system must checkpoint and suspend rather than corrupt state.

---

## 4. Compute Topology

### 4.1 Local compute (Proxmox, up to 40 cores)
The primary reasoning host runs as one or more Proxmox guests (VM or LXC — LXC preferred for lower overhead given the "can run on a single core" requirement). Local cores handle:
- Orchestration of the Master Agents and their deliberation loop
- Symbolic/logical reasoning, proof search, and cross-checking (workloads that don't parallelize well onto GPUs)
- Corpus ingestion, parsing, and indexing
- Checkpointing and state serialization

### 4.2 Distributed compute (opportunistic, up to ~200 cores)
Used only for **embarrassingly parallel, checkpoint-safe** work:
- Parallel hypothesis exploration (fan-out of candidate reasoning branches)
- Bulk re-embedding or re-indexing of corpus material during idle "evolution" cycles
- Batch verification/cross-referencing of citations against source archives
- Parallel evaluation of the concurrent question queue (Section 9)

Distributed workers are treated as **stateless lease-holders**: they receive a unit of work plus the minimal context needed, and return a result plus provenance. They never hold authoritative state. If a distributed worker disappears mid-task, the work unit is simply requeued; no state is lost because none was uniquely held there.

### 4.3 GPU pool (opportunistic, up to 10 GPUs / 240 GB VRAM)
GPUs are **accelerators, never dependencies**:
- Embedding generation for retrieval
- Any local neural inference components (if the design incorporates learned components alongside symbolic ones)
- Large-scale similarity search over the knowledge graph

Every GPU-accelerated code path must have a CPU-only fallback path, even if that fallback is orders of magnitude slower. The system must never block on GPU availability — it degrades quality-of-service (accepts a longer reasoning cycle) rather than failing.

### 4.4 The "single core, full memory" floor
This is the system's stated minimum viable operating point and deserves explicit design treatment:
- All Master Agents' processing must be expressible as **cooperatively scheduled, single-threaded-capable** work — i.e., the architecture cannot assume true parallel execution for correctness, only for speed.
- The deliberation loop (Section 6) is designed as a serializable sequence of discrete reasoning steps, each of which can be executed one at a time on one core, at whatever pace that allows, without losing correctness or needing to restart.
- Time-to-answer is expected to scale up (potentially far beyond the "about a day" target) as available compute shrinks toward this floor. This is acceptable by design; correctness and eventual completion are not sacrificed.
- Under the single-core floor, the concurrent question queue (Section 9) does not stop growing or accepting new questions — it simply processes more slowly, using time-slicing (Section 9.4) rather than true parallelism.

---

## 5. Memory-Resident State Model

### 5.1 What lives in memory
1. **The Belief Graph** — a persistent, versioned knowledge graph of propositions, their sources, confidence levels, and inter-dependencies (what supports or contradicts what).
2. **Active Working Sets** — per-Master-Agent scratch space for the current deliberation (partial proofs, candidate hypotheses, retrieved passages under consideration).
3. **Provenance Ledger** — an in-memory index mapping every claim to its originating freely-available source(s), required both for citation integrity and for the "reputable sources only" constraint to be auditable.
4. **Reputability Engine State** — the current standard(s) of reputability, their version history, and the evidence trail behind every promotion/demotion decision (Section 8.4).
5. **Question Ledger** — every question ever submitted, its status, its full answer history, and its links into the Belief Graph (Section 9.1).
6. **Session/Query Context** — the current question(s) being deliberated, and the deliberation trace(s) so far, for however many questions are concurrently active.

### 5.2 Why all-in-memory
DDR3 latency and bandwidth, while modest by modern standards, are still orders of magnitude faster than spinning disk and materially faster than most network storage. Given that the reasoning process is expected to make an extremely large number of small, cross-referencing accesses into the belief graph over the course of a day-long deliberation — and given that many such deliberations may now be running concurrently and sharing that same graph (Section 9) — keeping the working graph resident in DRAM is what makes "slow but thorough, at scale" feasible rather than "slow and thrashing."

### 5.3 Persistence discipline
Even though reasoning happens in memory, the system is **state-persistent**, not memory-only:
- **Checkpointing:** the Belief Graph, Provenance Ledger, Reputability Engine State, and Question Ledger are checkpointed to Tier 2/3 storage on a configurable cadence (Section 10), and always before any planned resource step-down or shutdown.
- **Append-only evolution log:** rather than overwriting prior belief states, each checkpoint is an entry in an append-only log, so the system's evolving "mind" can be audited or rolled back — important for a system whose stated purpose is the *development* of knowledge over time, and essential for the "answers can change later" behavior in Section 9.3.
- **Crash/eviction recovery:** if the process is killed or the VM is reclaimed without a clean shutdown, the system reloads the last full checkpoint plus any replayable log segments, and resumes deliberation from the most recent safely-recoverable point rather than from scratch. No question in the Question Ledger is ever dropped by a crash — it is simply resumed.

### 5.4 Memory pressure handling
If DRAM pressure approaches the working-set floor (e.g., due to reduced allocation), the system:
1. Sheds the least-recently-used corpus shards from the in-memory cache first (these are always re-fetchable from Tier 2/3).
2. Compresses or summarizes low-confidence/low-relevance branches of the current working set, and pages the least-active concurrent questions' contexts out to Tier 2/3 (Section 9.4), keeping only the most active threads fully resident.
3. As a last resort, checkpoints and suspends, rather than allowing an out-of-memory condition to corrupt the Belief Graph or the Question Ledger.

---

## 6. Cognitive Architecture

### 6.1 Master Agents
Athenaeum organizes reasoning under a small set of domain-rooted Master Agents, each trained on and responsible for a classical foundation:

- **Master of Physics** — natural philosophy through modern physics; responsible for empirical/causal reasoning and consistency with observed law.
- **Master of Mathematics** — formal systems, proof, quantitative reasoning; responsible for internal consistency and rigor of any formal claim.
- **Master of Logic** — argument structure, validity, fallacy detection; arbitrates the *form* of reasoning used by the other agents.
- **Master of Philosophy** — epistemology, ethics, metaphysics; responsible for framing questions correctly and surfacing unstated assumptions.
- **Master of Theology** — the history and structure of religious and metaphysical thought; responsible for representing traditions accurately and distinguishing empirical claims from claims of faith.

Each Master Agent is trained on a foundation of primary classical texts in its domain (freely available public-domain editions and reputable open scholarly commentary — see Section 8), and maintains its own sub-graph within the shared Belief Graph.

### 6.2 Deliberation loop
For a given question, the system runs a structured, multi-round process rather than a single pass:

1. **Framing round** — Philosophy and Logic agents jointly decompose the question, surface ambiguity, and identify which Master Agents are relevant.
2. **Parallel exploration round** — relevant Master Agents independently retrieve, reason, and propose candidate partial answers, each annotated with confidence and provenance.
3. **Cross-examination round** — agents review each other's candidate answers, flag contradictions, and request clarification or additional evidence. This may trigger further retrieval (from Tier 2/3, or the "freely available sources" ingestion pipeline).
4. **Synthesis round** — a coordinating process integrates surviving, cross-checked claims into a single most-likely-outcome answer, explicitly stating remaining uncertainty and dissent.
5. **Idle/evolution rounds** — between queries, and interleaved with active deliberation when resources allow, the system re-runs cross-examination over *existing* Belief Graph content, looking for claims that no longer hold up, sources that have been superseded, or new connections across domains. These rounds are also what drive the re-evaluation of previously answered questions (Section 9.3).

This loop is designed to be **checkpointable between every round**, so a day-long deliberation can be paused and resumed across resource fluctuations or reboots without loss of progress, and so that a large number of such deliberations can be time-sliced against limited compute (Section 9.4).

### 6.3 "Most likely outcome" as an explicit output contract
Because the system's stated purpose is to consider all possibilities and converge on the most likely outcome, every final answer is structured as:
- The leading conclusion,
- Its estimated confidence,
- The principal alternative(s) considered and why they were weighted lower,
- The provenance chain supporting the leading conclusion, including the reputability grade of each source at the time it was used (Section 8.4),
- Explicit flags for anything that rests on contested or faith-based premises (a distinction the Theology and Philosophy agents are specifically responsible for maintaining),
- A Belief Graph snapshot ID, so the answer is always traceable to the exact state of the system's knowledge at the moment it was produced (see Section 9.3).

---

## 7. Elastic Resource Management

### 7.1 Guiding rule
> Anything except the DRAM allocation may be added or removed at any time. The system must never lose correctness because of this — only speed.

### 7.2 Resource monitor
A lightweight resource monitor (itself pinned to run correctly even on the single-core floor) continuously tracks:
- Cores currently available (local + distributed)
- GPU/VRAM currently available
- Reachability and latency of Tier 2 (NVMe/LAN) and the distributed DRAM pool
- Remaining local DRAM headroom
- Size and priority mix of the current concurrent question queue (Section 9)

### 7.3 Response to scale-down
- **Cores reduced:** the scheduler reduces the number of concurrently active reasoning branches, and the number of questions time-sliced in parallel (Section 9.4); the deliberation loop continues serially rather than in parallel. No branch and no question is dropped, only deferred.
- **Distributed pool lost:** any in-flight distributed work units are requeued for later (when the pool returns) or, if urgent, pulled back to local execution at reduced parallelism.
- **GPUs lost:** falls back to CPU-only embedding/inference paths; retrieval quality is unaffected, retrieval *speed* is not.
- **NVMe (Tier 2) unreachable:** falls back to Tier 3 for both reads and checkpoint writes; checkpoint cadence may be automatically lengthened to avoid saturating HDD write bandwidth (configurable minimum/maximum cadence).
- **DRAM reduced below floor:** triggers checkpoint-and-suspend (Section 5.4), not a crash.

### 7.4 Response to scale-up
- Newly available cores, GPUs, or distributed nodes are picked up opportunistically at the start of the next deliberation round (not mid-round, to avoid re-synchronization overhead) and used to widen parallel exploration, accelerate the idle evolution cycles, or advance more questions from the queue simultaneously.

---

## 8. Knowledge Acquisition Policy

### 8.1 Foundational corpus
The initial training foundation is the classical canon in the five domains (public-domain primary texts: e.g., Euclid, Aristotle, the pre-Socratics, classical mathematical and scientific treatises, foundational texts of major theological/philosophical traditions), sourced from open, reputable digital archives (e.g., public-domain text archives, university open-access repositories, standard open scholarly editions).

### 8.2 Ongoing ingestion
The system may continue to ingest new material during idle/evolution cycles, subject to hard constraints:
- **Source policy:** only freely and legally accessible sources — no paywalled content, no circumvention of access controls, no scraping in violation of a source's terms of service or robots directives.
- **Legality policy:** the ingestion pipeline performs a license/terms-of-service check before retaining any material, and the system as a whole is designed to refuse any action (ingestion or otherwise) that would violate applicable law.
- **No metered access:** the ingestion and reasoning pipelines are explicitly forbidden from calling any paid, per-token, or otherwise metered external service. All external calls are to free, public resources only.

### 8.3 Token/compute usage policy
Because the system runs entirely on owned/local (or opportunistically borrowed internal) infrastructure rather than metered external APIs, there is no per-token cost function to optimize against. The design therefore deliberately does **not** impose an artificial token budget on any reasoning step. The only real constraints are:
- Wall-clock time budget (configurable, default ~24 hours per question — Section 10),
- Physical memory and compute actually available at the time,
- The hard prohibition on paid/metered services.

This is a meaningful architectural stance: components must be designed for *unbounded* intermediate reasoning length, with memory management (Section 5.4) as the actual limiting mechanism rather than a token cap.

### 8.4 The Reputability Arbitration Engine (self-governing, evolving)
Rather than delegate the question of "what counts as a reputable source" to a fixed external list or a one-time human ruling, Athenaeum treats reputability itself as a first-class object of its own reasoning — owned, applied, and revised by the system, following a defined and auditable procedure rather than ad-hoc judgment.

**8.4.1 Seed criteria (bootstrap, not final authority).**
At genesis, the Reputability Engine is seeded with a small set of transparent, revisable starting heuristics rather than a permanent rulebook, e.g.: primary texts and their standard critical editions; peer-reviewed venues; recognized academic, scientific, and archival institutions; official government/standards-body publications; internal consistency and citation density of a source relative to other already-trusted material. These seed criteria are stored as version 0 of the reputability standard and are explicitly labeled as a starting point to be refined, not a fixed doctrine.

**8.4.2 Continuous evidence accumulation.**
Every time a source is used in a deliberation, the outcome is recorded against it in the Provenance Ledger: did its claims survive cross-examination (Section 6.2, round 3)? Were they corroborated by independent sources? Did later evidence overturn them? This gives every source a running, evidence-based track record, rather than a single static label.

**8.4.3 Grading, not binary admission.**
Sources are not simply "in" or "out." Each is assigned a graded, versioned reputability score with an explicit rationale and evidence trail, on a scale defined by the current version of the standard (e.g., foundational / strongly corroborated / provisionally accepted / contested / rejected). Grades can move in either direction as evidence accumulates. A source's grade at the *time it was used* is preserved permanently in any answer that cites it (Section 6.3), even if its grade later changes — the historical record of "what we believed and why, and how confident we were, at time T" is never rewritten.

**8.4.4 Dispute resolution procedure.**
When two Master Agents disagree about a source's reputability, or a source is flagged as contested (e.g., contradicted by a higher-graded source, or of unclear provenance), the Logic Master runs a structured adjudication:
1. Restate the specific claim(s) in dispute and the sources on each side.
2. Compare the track records (8.4.2) and independence of corroboration of each side.
3. Check for conflicts of interest, circularity (e.g., two sources citing each other only), or category errors (e.g., treating a claim of faith as if it were an empirical claim — referred to the Theology/Philosophy Masters).
4. Issue a ruling with a written rationale, recorded in the Reputability Engine's own append-only decision log, itself part of the Belief Graph and therefore auditable, revisable, and reversible on new evidence.
No single Master Agent has unilateral authority to blacklist or whitelist a source; a ruling is only final once logged with rationale, and remains open to a later, better-evidenced reversal.

**8.4.5 The standard evolves; nothing is destroyed.**
The reputability standard itself (the criteria in 8.4.1, as amended) is versioned exactly like the Belief Graph: version N+1 supersedes version N for new decisions, but the full history of prior standards, and which decisions were made under which version, is retained permanently. This lets the system explain not just *what* it currently considers reputable, but *how its judgment of reputability has itself changed over time* — which is itself a piece of the "development of knowledge" the system exists to produce. Periodic idle-cycle reviews (Section 6.2, round 5) re-examine the standard itself for internal consistency, exactly as they re-examine ordinary claims.

**8.4.6 Hard floor, regardless of version.**
Whatever the current version of the standard says, three constraints never change and are not themselves subject to revision by the Engine: sources must be freely and legally accessible (8.2), the system will not use paid/metered services (8.3), and the system will not take or recommend any unlawful action. These are treated as constitutional constraints on the Reputability Engine rather than tunable heuristics.

---

## 9. Concurrency & Multi-Query Model

### 9.1 The Question Ledger
Every question submitted to the system — at any time, from any number of requesters — becomes a permanent entry in the **Question Ledger**, part of the resident, checkpointed state described in Section 5.1. A question is never deleted and never simply "expires": its status moves through a lifecycle (`queued → active → answered → dormant → [re-opened] → re-answered → dormant → ...`) but it always remains retrievable, along with its full history.

### 9.2 Concurrent processing and shared findings
Multiple questions may be queued and worked simultaneously, subject to available compute (Section 7). Critically, the questions are **not siloed**:
- All active deliberations read from and write to the *same* shared Belief Graph (Section 5.1) and the same Provenance Ledger and Reputability Engine state.
- When one deliberation thread establishes, corroborates, or overturns a claim, that update is immediately visible to every other in-flight thread, and to the idle-evolution process.
- This means questions submitted later can benefit from — and questions in progress can be interrupted and improved by — findings made in service of a completely different question. A discovery made while answering a physics question can immediately sharpen a philosophy question running concurrently, if the Belief Graph connects them.
- Cross-thread updates are applied at well-defined synchronization points (the end of each deliberation round, Section 6.2) rather than through uncontrolled mid-round mutation, so that any single thread's reasoning stays internally consistent within a round even while the shared graph is being updated by others.

### 9.3 Answers can change: versioned, not overwritten
Because the Belief Graph keeps evolving after an answer is given, an answer is never treated as eternally fixed:
- Every answer produced is stamped with the Belief Graph snapshot ID it was derived from (Section 6.3) and stored as a new version under that question's entry in the Question Ledger — prior answers to the same question are archived, never overwritten or deleted.
- **Importance-weighted re-evaluation:** questions are assigned an importance/impact rating (based on factors such as breadth of domains touched, how many other questions or claims depend on it, and any explicit priority given at submission). During idle-evolution cycles (Section 6.2, round 5), and whenever a relevant claim in the Belief Graph is materially revised (e.g., a source's reputability grade changes, Section 8.4.3, or new corroborating/contradicting evidence is ingested), higher-importance dormant questions are automatically re-opened and re-run against the current graph.
- If a re-run produces a materially different leading conclusion, the new answer is appended as the current version, with an explicit note comparing it to the prior version and explaining what changed and why (which sources, which reasoning step, which reputability shift). The old answer is preserved, not hidden — the system can always show "what we thought, and when, and why it changed."
- Lower-importance questions remain dormant indefinitely unless explicitly re-submitted, but are never purged; they can always be pulled back into active re-evaluation on request or if a sufficiently significant graph change touches them.

### 9.4 Scheduling under shared, elastic resources
The same elastic resource pool (Section 7) is shared across all concurrent questions, so scheduling must be fair and interruption-safe:
- A priority queue orders active/queued questions by a combination of submission order, stated urgency, and importance rating.
- Because the deliberation loop is checkpointable at round boundaries (Section 6.2), the scheduler can **time-slice** across many questions even on very limited compute (down to the single-core floor, Section 4.4): a question runs for one round, checkpoints its per-question working state, and yields to the next question in the queue, rather than requiring one question to run to completion before another can start.
- On scale-up, more questions can be advanced genuinely in parallel (subject to Belief Graph write synchronization, Section 9.2); on scale-down, the same logical process continues, just serialized more coarsely. No question loses progress due to being paused for another's turn — this is the same checkpoint/resume mechanism used for resource elasticity generally (Section 5.3), applied per-question.

---

## 10. Configuration Surface

All of the following must be externally configurable (e.g., via the boot-time database configuration loaded from the SSD array), without requiring a code change:

```yaml
compute:
  local_cores_min: 1
  local_cores_max: 40
  distributed_cores_max: 200
  gpu_count_max: 10
  gpu_vram_pool_max_gb: 240

memory:
  local_dram_gb: 512          # treated as fixed/guaranteed
  distributed_dram_pool_max_gb: 1024
  working_set_floor_gb: <configurable, must be < local_dram_gb>

storage:
  boot_ssd_path: /mnt/boot-db
  nvme_lan_path: <network mount, optional>
  hdd_archive_path: /mnt/archive
  checkpoint_cadence_min_minutes: <config>
  checkpoint_cadence_max_minutes: <config>
  tier2_health_check_interval_seconds: <config>

deliberation:
  target_answer_latency_hours: 24     # soft target, not a hard cap
  max_answer_latency_hours: <config or "unbounded">
  min_answer_latency_hours: <config, e.g. for simple queries>
  max_deliberation_rounds: <config or "unbounded">
  idle_evolution_enabled: true

concurrency:
  max_concurrent_active_questions: <config, scales with available cores>
  time_slice_rounds_per_question: <config>
  importance_reevaluation_enabled: true
  reevaluation_trigger_threshold: <config, min belief-graph delta to trigger re-open>
  question_ledger_retention: permanent   # hard invariant — never purge

reputability:
  standard_version: <auto-incrementing, read-only field>
  seed_criteria_path: <path, used only at genesis>
  dispute_log_path: <path>
  allow_grade_reversal: true
  hard_floor_free_legal_sources_only: true   # hard invariant, not tunable
  hard_floor_no_paid_apis: true              # hard invariant, not tunable

knowledge_acquisition:
  ingestion_enabled: true
  license_check_strict: true
  disallow_paid_apis: true            # hard invariant, not meant to be disabled

environment:
  bootstrap_mode: resume | genesis
  proxmox_node_id: <config>
  network_dependency_tolerance: strict | lenient
  degraded_mode_notifications: true
```

The `target_answer_latency_hours` and related fields are the primary "waiting time" knobs referenced in the requirements — they set the *soft* target the deliberation loop aims for when scaling parallelism, but never force premature termination of an unfinished chain of reasoning; they only affect how aggressively the system tries to parallelize (spending more opportunistic cores/GPUs to hit the target) versus running lean. The `concurrency` block governs how many questions are advanced at once and how re-evaluation is triggered, without ever permitting a question to be dropped from the Ledger.

---

## 11. Resilience & Failure Modes Summary

| Failure/Change | System Response |
|---|---|
| Proxmox host reduces allocated cores to 1 | Continue serially; time-slice across queued questions; no data loss; slower deliberation |
| Distributed compute pool vanishes | Requeue in-flight work; continue locally at reduced parallelism |
| GPU pool vanishes | Fall back to CPU inference paths |
| NVMe (Tier 2) network storage unreachable | Fall back to Tier 3 HDD for reads/writes; widen checkpoint interval |
| HDD array degraded (partial) | Prioritize checkpoint writes; alert; continue read-mostly from Tier 2/DRAM |
| Unclean shutdown / VM eviction | Resume from last checkpoint + replay log on next boot; Question Ledger fully intact |
| DRAM allocation cut below working-set floor | Checkpoint-and-suspend (including per-question states); resume when restored |
| Untrusted/unreputable source encountered | Reject or grade-down at ingestion per current Reputability Engine standard; logged with rationale |
| Ingestion target requires payment or violates ToS | Hard refusal; never attempted |
| Two Master Agents dispute a source's reputability | Logic Master runs the structured dispute-resolution procedure (Section 8.4.4); ruling logged |
| A previously answered, high-importance question's supporting claims change | Question automatically re-opened, re-run, new versioned answer appended, prior answer preserved |
| Question queue grows faster than compute can process it | Priority ordering (Section 9.4) governs order; nothing is dropped, only delayed |

---

## 12. Open Questions for Review

1. **Synthesis authority:** Section 6.2's "synthesis round" needs a fully concrete adjudication procedure when Master Agents disagree irreconcilably in ways the Logic Master's dispute-resolution process (8.4.4) doesn't cleanly resolve (e.g., a claim with theological support but no empirical support, where the disagreement is not about source reputability but about the applicable domain of judgment itself).
2. **Reputability registry governance — resolved (see Section 8.4), with one residual question:** the Engine's own seed criteria (8.4.1) and any amendments to the standard itself are proposed and reviewed through idle-cycle self-review; whether an external human checkpoint should ever be required before a *standard* (as opposed to an individual source grading) is amended is left open for policy discussion.
3. **Distributed pool trust model:** the current design treats distributed workers as stateless and disposable; if the distributed pool is not fully trusted (e.g., shared with other tenants), additional integrity verification of returned results may be needed — this also matters for the concurrency model in Section 9, since untrusted results must not be allowed to corrupt the shared Belief Graph across threads.
4. **Checkpoint and Ledger size growth:** the Belief Graph, the reputability decision log, and now the ever-growing, never-purged Question Ledger (with full answer-version history) will grow indefinitely; a compaction/tiering policy against the 500 TiB HDD ceiling (e.g., moving very old, low-importance, never-re-opened question histories to a colder or summarized representation, while never deleting them) should be defined before long-term operation.
5. **Definition of "done":** for a system whose purpose is continual evolution of knowledge, and whose answers can now be explicitly superseded (Section 9.3), consumers of an answer need a clear convention for "is this the current version?" — e.g., a subscription or notification mechanism for important questions whose answer has changed, versus a pull-only model where the requester must check back.
6. **Re-evaluation trigger tuning:** the `reevaluation_trigger_threshold` (Section 10) needs a concrete definition of "material" Belief Graph change; too sensitive and low-importance graph churn causes excessive re-answering, too coarse and genuinely important revisions get missed.

---

*End of design document. No implementation has been performed; this document is intended solely to establish and review the architecture prior to any build phase.*
