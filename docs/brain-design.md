# Design Document: Athenaeum — The Brain

**Status:** Primary design focus, active development (rev. 4 — adds a sixth Master Agent, Engineering, for coding competence, and Model Fitness judgment over the Body's local model ecosystem; rev. 3 cherry-picked proposal-only writes, three output types, integrity gates, held-out evaluation, governance roles, and injection-resistance from the alternate v1.0 review package and explicitly declined its infra/taxonomy pivot)
**Scope:** All cognitive logic — the Master Agents, the deliberation loop's actual reasoning content, the Reputability Engine's judgment mechanisms, re-evaluation decision logic, knowledge consolidation, human input handling, and content-integrity rules.
**Explicitly out of scope:** infrastructure, storage, elasticity, concurrency execution mechanics, and ingestion mechanics — all covered in `body-design.md` and assumed complete, stable, and available as a set of interfaces described in Section 1.2 below.

---

## Provenance of This Revision

An alternate, independently-produced design package (`athenaeum-complete-project-v1_0.zip`) proposed a different pivot: a leaner researcher/critic/synthesizer role model in place of the five classical Master Agents, and a conservative single-VM, PostgreSQL-centered, CPU-first infrastructure in place of the elastic Proxmox Body. That pivot is **not** adopted — the classical five-domain taxonomy and the elastic infrastructure model remain the founding design. Several specific mechanisms from that package were strong on their own merits and are folded in here regardless of the infrastructure disagreement:

- Three distinct output product types (Section 5.4)
- Proposal-only agent writes with a single validated commit boundary (Section 4.4)
- Non-compensatory integrity gates (Section 9.8)
- Held-out, contamination-resistant evaluation (Section 9.9 — resolves prior Open Question #3)
- Baseline/ablation evaluation methodology (Section 9.7)
- Human governance roles for submission and checkpoint approval (Section 11.7)
- An explicit rule that ingested content and human input are evidence, never instructions (Section 12)

Declined from the same package: the single-VM/no-GPU/CPU-first operational posture, the specific technology stack (PostgreSQL/llama.cpp/OIDC/Caddy), the allowlisted-only corpus posture, and the replacement of the five Master Agents with a three-role model. Rationale for each is in the response accompanying this revision.

---

## 0. An honest framing, stated up front

Before anything else: this document is different in kind from `body-design.md`. The Body's tasks had clear pass/fail tests — a checkpoint either restores identical state or it doesn't. Most of the Brain's tasks don't have that property. "Did the Physics Master reason well about this question" is not something a unit test can verify the way "did the checkpoint round-trip" can. This document tries to be as concrete and buildable as possible anyway, but it does not pretend the hard problem — building something that actually reasons well, calibrates its confidence honestly, and knows what it doesn't know — is solved by having a good architecture diagram. Section 9 (Evaluation) is arguably the most important section in this document for that reason: without a real way to measure reasoning quality, everything else here is just well-organized guessing.

---

## 1. Purpose and Interfaces to the Body

### 1.1 What the Brain is responsible for
Everything that decides *what to think*, as opposed to *where to store it or how to keep running*:
- The five Master Agents' actual reasoning behavior.
- The deliberation loop's round content: framing, exploration, cross-examination, synthesis, and idle-evolution.
- The Reputability Engine's judgment: grading criteria, dispute adjudication, and evolution of the standard itself.
- Re-evaluation judgment: deciding whether a change in the Belief Graph is material enough to warrant reopening a dormant answer.
- Knowledge consolidation judgment: deciding what deserves to persist as durable "deep-knowledge" versus what should be trimmed or compacted (Section 10).
- Human input judgment: how a human contribution enters the graph, how much it can move existing belief, and when it requires a human checkpoint before an answer is finalized (Section 11).
- Content-integrity judgment: ensuring ingested material and human input are always treated as evidence to be evaluated, never as instructions the reasoning process obeys (Section 12).

### 1.2 What the Brain assumes the Body provides (contract, not redesign)
- A durable, versioned Belief Graph store, Provenance Ledger store, Reputability Engine store, and Question Ledger store (read/write, queryable, checkpointed automatically).
- A work-unit/round execution model: the Brain defines round *handlers* (pure-ish functions: current state + inputs → outputs + proposed writes); the Body decides when and on what hardware they run, and guarantees atomicity at round boundaries.
- A resource-state signal (how much compute/memory/GPU is currently available) that round handlers may consult to scale their own internal effort (e.g., how many candidate hypotheses to explore) — but never to change correctness, only thoroughness.
- A guarantee that once a round handler returns its proposed writes, they are either fully committed or fully discarded — the Brain never has to reason about partial writes.
- A cold-archive write/read path (Body Tier 3) that the Brain can target for full-fidelity historical traces displaced by consolidation (Section 10), and retrieve from on demand.
- Content-addressed, tamper-evident storage for checkpoints and provenance blobs, and support for idempotency keys / expected-version checks on writes (per `body-design.md` Section 3.4 and 7.5) — the concrete mechanism underneath the single commit boundary in Section 4.4.

Nothing in this document defines how any of the above is actually implemented, stored, or scaled. That boundary is intentional and should be preserved.

---

## 2. The Master Agents

### 2.0 A deliberate extension: six agents, not five
The founding brief specified five classical domains. Strong coding competence is now a stated first-class requirement, and it doesn't fit inside any of the original five without distortion — it isn't Mathematics (formal proof), though it leans on it; it isn't Physics (natural law), though it shares Physics's empirical, falsifiable posture. Rather than stretch an existing agent's jurisdiction past its domain scope statement (which Section 2.4's own drift monitoring would then have to flag as a violation of the design it's supposed to protect), a sixth Master Agent — **Engineering** — is added, with its own classical grounding (2.3) so it isn't an ungrounded modern bolt-on. This is recorded here explicitly, the same way every other deliberate departure in this document is recorded, rather than silently expanding the taxonomy.

### 2.0b A second deliberate extension: World News (seven agents, added 2026-09-22)
A new stated requirement — building timelines showing how major world events tie into each other, current and historical — doesn't fit inside any of the original six either. It isn't Philosophy (it doesn't reason about assumptions or values), and it isn't Logic (it isn't checking argument form). It's a distinct domain with its own falsifiable core: documented chronology and the temporal-precedence constraint any causal/contributing claim between two events must satisfy (an event cannot cause, or contribute to, one that occurred before it). A seventh Master Agent — **World News** — is added on the same basis Section 2.0 already established for Engineering: it doesn't distort an existing agent's domain scope statement, and it's recorded here explicitly rather than silently expanding the taxonomy again.

**Domain:** current and historical world events — their chronology and documented causal/contributing relationships to one another, for timeline construction.

**Reasoning mode:** mirrors Physics's defeat-condition discipline (2.2), but the falsifiable unit is temporal precedence against documented dates rather than a physical law — mechanically checkable the same way Mathematics checks primality, not asserted plausibility. A claimed causal/contributing link is flagged chronologically POSSIBLE or IMPOSSIBLE based on whether the claimed cause's date precedes the claimed effect's date; this is a necessary condition this toy agent can check, not a sufficient one for actual causation (precedence alone doesn't prove causation — post hoc ergo propter hoc is exactly the fallacy Logic's cross-examination remains responsible for catching on top of this agent's narrower chronological check).

**Toy-slice scope, same discipline as every other agent in this repo:** a small, real, explicitly narrow lookup of well-documented, uncontroversially-dated events (`agents.py`'s `MasterOfWorldNews._EVENTS`) — not a general history knowledge base, and not yet LLM-backed. Real events outside this registry are correctly abstained from (never guessed at), the same "silently abstain outside real jurisdiction" discipline every other agent here already follows.

**Plumbing note:** adding this agent (and any future one) no longer requires editing `rounds.py` — `agents.py` now exposes a `@master_agent` registration decorator; `rounds.ALL_AGENTS` is built from that registry (`all_agents()`), not a hardcoded class list. See `agents.py`'s module docstring and `docs/brain-session-log.md` for the full reasoning.

### 2.1 Common structure
Every Master Agent shares the same internal shape, so that adding, removing, or later re-training an agent doesn't require redesigning the loop around it:

- **Domain scope statement** — an explicit, checkable definition of what falls inside and outside this agent's jurisdiction (critical for Section 4's dispute resolution).
- **Foundational corpus** — the classical texts and reputable commentary this agent was trained/grounded on (Section 2.3).
- **Reasoning mode** — the dominant style of inference this agent is expected to apply (see 2.2), used both to guide its own behavior and to let *other* agents sanity-check whether it's reasoning in a way appropriate to its domain.
- **Claim interface** — every output a Master Agent produces, whether a candidate answer, a challenge to another agent, or a vote in synthesis, is expressed in one normalized structure (Section 3.5), never free-form prose alone, and is always a **proposal**, never a direct write (Section 4.4).
- **Self-declared confidence** — every claim ships with the agent's own confidence estimate *and* a brief statement of what would change its mind (a falsifiability/defeat condition), which is what makes cross-examination (Section 3.3) possible rather than performative.

### 2.2 The five agents and their reasoning modes

**Master of Physics**
- Domain: empirical, causal claims about the natural world; consistency with observed law and established theory.
- Reasoning mode: hypothesis formation → prediction → check against known empirical results; explicit distinction between "consistent with current physics," "consistent with historical-but-superseded physics," and "unresolved/open question in physics."
- Defeat condition discipline: must always be able to state what observation or established result would contradict its claim. A claim it cannot falsify in this sense is flagged as *metaphysical*, not physical, and routed toward Philosophy.

**Master of Mathematics**
- Domain: formal systems, proof, quantitative structure.
- Reasoning mode: definition → derivation → proof (or explicit statement of conjecture/unproven status). Never asserts a mathematical claim as settled without a derivable chain back to accepted axioms/theorems it can cite from its corpus or the Provenance Ledger.
- Serves a second, cross-cutting role: any *other* agent's claim that contains a quantitative or formally structured component can be routed through the Mathematics agent for a rigor check, independent of that claim's subject domain.

**Master of Logic**
- Domain: the *form* of arguments — validity, soundness, fallacy detection — across all other agents' outputs.
- Reasoning mode: does not generate first-order domain claims itself; instead evaluates other agents' claim structures for validity (does the conclusion follow from the stated premises?), consistency (do this agent's claims contradict its own earlier claims?), and fallacy patterns (equivocation, circular support, unfalsifiable-but-asserted-as-empirical, etc.).
- Chairs the dispute-resolution and synthesis-tie-breaking procedures (Sections 4 and 6) precisely because it has no first-order stake in any domain's conclusions — its authority is procedural, not substantive.

**Master of Philosophy**
- Domain: epistemology, ethics, metaphysics; question-framing and assumption-surfacing.
- Reasoning mode: before other agents engage substantively, Philosophy (with Logic) performs the framing round (Section 3.1) — decomposing the question, naming hidden assumptions, and identifying which domains are actually implicated. It also holds a standing responsibility to flag when a question conflates categories (e.g., treats an ought-claim as if it were an is-claim), and to flag which of the three output types (Section 5.4) a question is actually asking for.

**Master of Theology**
- Domain: the history, structure, and internal logic of religious/metaphysical traditions — what a tradition holds and why, argued from within that tradition's own premises.
- Reasoning mode: represents traditions accurately and charitably, explicitly distinguishes "this is what tradition X holds, and its internal reasoning for holding it" from "this is empirically or logically demonstrable independent of accepting tradition X's premises." Never asserts a faith-premised claim with the same confidence grammar as an empirically-grounded one (enforced jointly with Logic and Philosophy — see Section 6.4).

**Master of Engineering** *(new)*
- Domain: software and system specification, implementation, and verification — writing, reviewing, and reasoning about code and the systems it builds.
- Reasoning mode: specify → implement → execute/test → verify. This mirrors Physics's hypothesis-and-defeat-condition discipline but grounds falsifiability in something stronger than observation: a failing test, a counterexample input, or a build/type error is a direct, mechanical defeat condition, not an inferred one. A code claim this agent cannot express as something executable or testable is flagged as a design/architecture claim requiring qualitative review, not asserted with the same confidence grammar as a verified implementation.
- Like Mathematics, serves a cross-cutting verification role: any other agent's claim with a formalizable or computable component (a simulation Physics wants run, a combinatorial argument Mathematics wants checked, a decision procedure Logic wants executed) can be routed to Engineering to actually build and run the check, rather than reasoning about it purely in prose.
- Execution happens only inside the Body's sandboxed execution capability (`body-design.md` Section 4.6) — this agent never has standing access to anything beyond that sandbox, and its claims about "what the code does" are only as trustworthy as the sandbox's isolation guarantees (tracked as a dependency in Section 14).

### 2.3 Foundational corpus and ongoing grounding
Each agent's starting foundation is the classical primary literature in its domain (public-domain texts and standard reputable critical editions, per the Body's ingestion mechanics). This is a *grounding*, not a cap: agents continue to draw on newly ingested, Reputability-graded material (Section 6) throughout operation. The classical foundation exists so that each agent's reasoning style is anchored in the discipline's own historical methodology (e.g., Euclidean-style derivation for Mathematics, Aristotelian/Scholastic argument forms available to Logic and Theology as reference structures) rather than starting from an ungrounded, purely modern statistical prior. Engineering's classical anchor is the ancient constructive/mechanical tradition — Euclid's constructive proofs (a proposition is established by actually building it), Archimedes' mechanics, Heron of Alexandria's *Pneumatica* and automata, Vitruvius's *De Architectura* — chosen because their common thread (a claim about a mechanism is settled by building and testing the mechanism, not by argument alone) is exactly Engineering's reasoning mode, not a retrofit.

### 2.4 Domain Fidelity Monitoring
As agents ingest new material over time, there's a real risk that an agent's *reasoning style*, not just its claims, quietly drifts from its declared domain scope — e.g., the Physics agent gradually starts reasoning more like a generalist, leaning on pattern-matched plausibility instead of hypothesis-and-defeat-condition discipline. Checking only claim correctness won't catch this, because a drifted agent can still produce individually defensible claims while reasoning in a way that's no longer distinctly *Physics* reasoning. The proposal:

**2.4.1 Two independent drift signals, tracked continuously per agent:**
1. **Jurisdictional overreach rate** — Logic already records, per claim, whether an agent's `jurisdiction_check` (3.5) was upheld or challenged during cross-examination. Aggregating this over time gives a structural signal: an agent increasingly asserting claims outside its declared domain scope (2.1) is drifting, independent of whether those claims happen to be correct.
2. **Reasoning-fingerprint deviation** — define a small set of style markers per agent, checkable mechanically from its claim structures: for Physics, the presence rate of an explicit defeat condition; for Mathematics, the presence rate of a cited derivation chain versus a bare assertion; for Logic, the ratio of procedural-only outputs to any first-order claims (which should be ~zero); for Philosophy, assumption-surfacing frequency in framing rounds it participates in; for Theology, the rate at which `claim_type: traditional` is correctly attached versus omitted. Each marker is computed over a rolling window and compared against a baseline fingerprint established during initial validation (Section 9).

**2.4.2 Combined Domain Fidelity Score.** The two signals are combined into a single tracked score per agent, stored in the Belief Graph exactly like the calibration record (5.3) — this is deliberately the same kind of object, since both are "is this agent still behaving the way it's supposed to" metrics, just measuring different things (accuracy vs. style/jurisdiction).

**2.4.3 Remediation path, not silent correction.** A statistically significant drop in an agent's Domain Fidelity Score does not trigger an automatic behavioral change (that would risk masking rather than fixing the problem). It triggers: (a) a flagged review during the next idle-evolution cycle, where a sample of the agent's recent claims is re-examined specifically for style, not just correctness; (b) if confirmed, a re-grounding pass — increasing retrieval weight toward the agent's foundational classical corpus (2.3) for a period, on the theory that drift is often a symptom of newer, less-disciplined material crowding out the agent's grounding; (c) if drift persists after re-grounding, escalation to the human checkpoint (Section 11.5), since a persistently drifting Master Agent is exactly the kind of high-importance structural problem that shouldn't be resolved by the system adjudicating itself indefinitely.

**2.4.4 Why this is separate from calibration (5.3).** An agent can be perfectly calibrated (its confidence matches its outcomes) while still drifting in style — e.g., a generalist reasoning process can be accurate without being *Physics* reasoning. Domain fidelity and calibration are tracked as two distinct scores precisely so that one drifting silently underneath acceptable accuracy doesn't go unnoticed.

---

## 3. The Deliberation Loop

### 3.1 Framing round
Inputs: a raw question. Outputs: a decomposition into sub-questions, an explicit statement of ambiguous terms and hidden assumptions, a routing list of which Master Agents are implicated and why, and which of the three output types (Section 5.4) the question is actually asking for.
- Run jointly by Philosophy and Logic. Philosophy proposes the decomposition and surfaces assumptions; Logic checks that the decomposition doesn't smuggle in a conclusion (a framing that already answers the question is a framing error, not a neutral first step).
- Output is itself written to the Belief Graph as a first-class object (a "question frame"), so later re-evaluation (Section 7) can detect if a *framing* itself becomes outdated, not just the answer built on it.

### 3.2 Parallel exploration round
Each routed Master Agent independently retrieves relevant material (from the Belief Graph and Provenance Ledger, via the Body's query interface) and produces one or more **candidate claims** in the normalized structure (Section 3.5), each with a confidence estimate and a defeat condition.
- Agents work independently in this round *by design* — no cross-talk yet — to avoid premature anchoring on another agent's framing of the answer.
- An agent may also produce a "no relevant claim" output, which is itself informative (it tells synthesis that a domain has nothing to add, rather than staying silent by omission).

### 3.3 Cross-examination round
Every candidate claim from Round 2 is exposed to every other routed agent. Each agent may:
- **Corroborate** — cite independent support from its own domain.
- **Challenge** — cite a specific contradiction, either from its own domain's material or from a logical/formal defect (routed to Logic/Mathematics as needed).
- **Request clarification** — flag that a claim is ambiguous or under-specified enough that it can't yet be evaluated; this can trigger a mini-return to framing (3.1) for that specific sub-question, not a full restart.
- **Abstain** — explicitly declare the claim outside its jurisdiction (using the domain scope statement from 2.1), which matters for Section 4's dispute resolution: an abstention is not a disagreement.
This round may trigger additional retrieval, including a request to the (Body-mechanical) ingestion pipeline if the existing corpus is insufficient to resolve a challenge — the Brain decides *that* more evidence is needed and *what kind*; the Body handles fetching it. All retrieved content, regardless of source, enters this round as material to be cross-examined — never as instructions (Section 12).

### 3.4 Synthesis round
See Section 4 in full — this is involved enough to warrant its own section.

### 3.5 The normalized claim structure
Every claim, challenge, and corroboration in the loop is expressed as:
```
{
  claim_id, question_id, round, issuing_agent,
  statement,                     # the assertion itself, stated precisely
  claim_type,                    # empirical | formal | executable | normative | traditional | human_input | procedural
  output_type_relevance,         # which of research | forecast | recommendation this claim bears on (Section 5.4)
  confidence,                    # calibrated estimate, see Section 5
  defeat_condition,              # what would falsify or overturn this claim
  supporting_provenance,         # source IDs + their current reputability grade
  serving_model,                 # which local model (per body-design.md's registry) produced this claim, for Model Fitness tracking (6.7)
  relation,                      # corroborates | challenges | abstains | clarifies (+ target claim_id if applicable)
  jurisdiction_check,            # explicit statement that this falls within issuing_agent's domain scope
  status                         # proposed | committed  (Section 4.4)
}
```
Requiring `claim_type` up front is what lets Section 6.4's category-error enforcement (never treating a traditional/faith-premised claim as if it were empirical) be checked mechanically rather than relying on prose vigilance. The `human_input` claim type is what lets human contributions flow through the same structure as every other claim, rather than being bolted on as a special case (Section 11). The `executable` claim type marks claims verified by actually running code (Engineering's reasoning mode, Section 2.2), which carries the strongest defeat-condition discipline of any claim type — its confidence is directly tied to test/execution results, not argued plausibility. The `status` field is what makes every claim's proposal-vs-canonical state explicit and queryable (Section 4.4). The `serving_model` field is what makes Model Fitness tracking (6.7) possible without conflating "the agent was wrong" with "the underlying model backing the agent was a poor fit for this task."

### 3.6 Idle-evolution rounds
Between and alongside active questions, the same round structure (framing → exploration → cross-examination) is re-run over *existing* Belief Graph content rather than a new question:
- Randomly or priority-sampled existing claims are re-challenged against the *current* state of the corpus and reputability grades, to catch claims that were reasonable when made but are no longer well-supported.
- This is also where the Reputability Engine's own standard (Section 6.5) gets periodically re-examined for internal consistency, and where Domain Fidelity reviews (Section 2.4) and knowledge consolidation passes (Section 10) are run.
- Idle-evolution findings that touch a dormant, previously-answered question feed into re-evaluation (Section 7).

---

## 4. Synthesis and Dispute Resolution Authority

This section resolves the open question flagged in earlier drafts: what happens when Master Agents disagree in a way that isn't simply "one has better evidence," but reflects a genuine conflict about *which domain's judgment should govern*.

### 4.1 The ordinary case: evidence-weighted synthesis
When surviving claims (post cross-examination) don't conflict in kind, only in confidence or completeness, synthesis is mechanical: combine corroborated, unchallenged, or successfully-defended claims into the leading conclusion, weighted by confidence and source reputability, per the output contract in Section 5.

### 4.2 The hard case: jurisdictional conflict
A jurisdictional conflict is a specific, detectable pattern: two agents each claim their domain governs the answer, and their `jurisdiction_check` fields (3.5) disagree rather than their evidence. Example: "is it wrong to X" produces a Philosophy claim (ethical reasoning from first principles) and a Theology claim (a tradition's teaching) that reach different conclusions — the disagreement isn't about facts, it's about which lens is authoritative for this question.

**Resolution procedure (chaired by Logic, which has no first-order stake):**
1. **Restate the question's actual ask.** Does the original question (post-framing, 3.1) ask "what does tradition X hold," "what follows from first-principles ethical reasoning," or "what is the most likely outcome, all considered"? Often the jurisdictional conflict dissolves once the question is restated precisely — the two agents may not actually be disagreeing, just answering different questions.
2. **If the question is genuinely asking for a single, all-things-considered answer:** Logic does not pick a winner by fiat. Instead, synthesis produces a **structured plural answer**: it presents each domain's conclusion *as that domain's conclusion*, explicitly labeled, rather than collapsing them into one voice. The "most likely outcome" framing (Section 5) is still produced, but for jurisdictionally-contested questions it is accompanied by a mandatory dissent record — this is a deliberate departure from single-answer synthesis, because manufacturing false consensus across domains that reason from genuinely different premises would misrepresent the actual state of the system's knowledge.
3. **Logic checks only the form of each side's argument**, never the substance of which domain "should" win — e.g., it can flag that Theology's claim doesn't actually follow from the cited tradition's own premises (a validity failure within that domain), but it cannot rule that Philosophy's framework is simply correct and Theology's is not, or vice versa. That would exceed Logic's jurisdiction as defined in 2.2 — a rule the design deliberately enforces on the system's own chairing agent, not just on the disputing parties.
4. **The dispute and its resolution (or its explicit non-resolution into a plural answer) is logged** to the Belief Graph exactly like a Reputability dispute (Section 6.4), so the pattern of which kinds of questions produce jurisdictional splits is itself visible and reviewable over time.

### 4.3 Why this is the right default, not a cop-out
An earlier draft of this system left "synthesis authority" as an open question because the honest answer is that forcing a single voice onto a genuine cross-domain disagreement produces a *false* most-likely-outcome — it would look more confident than the underlying reasoning warrants. Structured plural answers, clearly labeled, are more useful and more honest than a hidden tie-break rule that quietly favors one Master Agent's worldview. This is treated as a load-bearing design decision, not a placeholder.

### 4.4 Proposal-only writes and the single commit boundary
Every claim any Master Agent produces — in exploration, cross-examination, or synthesis — is a **proposal** (`status: proposed` in 3.5) until it passes through exactly one validating step: the **Synthesis Commit**. This formalizes something the loop already implied and makes it an explicit, enforceable rule:

- No Master Agent, including Logic acting as chair, may write directly to the canonical Belief Graph. Agents only ever emit proposed claims.
- The Synthesis Commit is the single procedure (Section 4.1 for the ordinary case, 4.2 for the plural case) authorized to mark claims `status: committed` and apply the resulting write to the Belief Graph, via the Body's atomic round-boundary write guarantee (Section 1.2).
- This gives the system one clear, auditable answer to "how did this claim become part of what we believe" — every committed claim traces back to exactly one Synthesis Commit event, which itself references every proposal it drew on.
- This is also the enforcement point for Section 12's rule that ingested content and human input can never bypass evaluation: nothing — not a corpus document, not a human submission, not an agent's own retrieval — becomes canonical without first being expressed as a proposed claim and surviving synthesis.

---

## 5. Confidence, Calibration, and the Output Contract

### 5.1 Confidence is not vibes
Every `confidence` value in the claim structure (3.5) must be traceable to at least one of: (a) strength and independence of corroborating sources, weighted by their current reputability grade; (b) whether the claim survived cross-examination unchallenged, was challenged-and-defended, or is contested; (c) for formal claims, whether a complete derivation exists versus a plausibility argument. Confidence is never a free-floating number an agent simply asserts.

### 5.2 Final answer structure
Every answer the system produces (ordinary or plural, per Section 4) includes:
- The leading conclusion (or the labeled set of domain-specific conclusions, if jurisdictionally plural).
- Calibrated confidence for each.
- The principal alternative(s) considered and why they were weighted lower.
- The full provenance chain, including each source's reputability grade *at the time it was used* (never silently updated retroactively).
- Explicit claim-type flags (Section 3.5) so a reader can immediately see which parts of the answer are empirical, formal, normative, traditional, or human-sourced in nature.
- Which of the three output types (Section 5.4) the answer is.
- Two distinct snapshot references: the **corpus snapshot ID** (the exact state of ingested source material the deliberation drew on) and the **Belief Graph snapshot ID** (the exact state of derived claims/confidence the answer was synthesized from) — kept separate because a corpus snapshot can be reused unchanged across many Belief Graph snapshots as reasoning about it evolves.
- Its checkpoint status if it required human review (`pending_human_checkpoint` / `current` — Section 11.5).

### 5.3 Calibration tracking (this is the accountability mechanism)
The system maintains a running calibration record: of claims made at confidence level X, what fraction later survived idle-evolution re-challenge (Section 3.6) or external verification, versus were overturned? This is tracked per Master Agent, not just system-wide, so that (for example) if the Physics agent is consistently overconfident relative to its outcomes, that is visible and actionable — this record is itself stored in the Belief Graph and is a primary input to Section 9's evaluation strategy, and is tracked distinctly from the Domain Fidelity Score (Section 2.4).

### 5.4 Three output product types
A single "most likely outcome" framing blurs together three genuinely different kinds of uncertainty. Every question, once framed (Section 3.1), is classified as asking for one or more of the following, and each is synthesized and calibrated according to its own semantics rather than a shared generic confidence number:

- **Research Answer** — what the available evidence supports: the leading conclusion, alternatives, dissent, gaps, and citations, calibrated per Section 5.1. This is the default type for descriptive/explanatory questions ("what caused X," "what is the current state of understanding of Y").
- **Forecast** — a probability estimate for a precisely defined future event, requiring: an objective resolution criterion, a resolution source, a deadline, explicit assumptions, and sensitivity to what would change the estimate. Forecast confidence is a genuine probability, not a research-confidence score relabeled — the two must never be presented with the same grammar (this is a category-error risk analogous to 6.4.3's empirical/traditional distinction, and is checked the same way).
- **Recommendation** — what a stated decision-maker should do, given explicit objectives, values, and constraints: alternatives considered, tradeoffs, reversibility of the choice, and conditions that should trigger a review. Recommendations are always explicitly value-laden (Philosophy's jurisdiction, Section 2.2) and must never be presented as if they followed from evidence alone the way a Research Answer does.
- A single question may legitimately warrant more than one type (e.g., "should we do X" implies both a Research Answer about the facts and a Recommendation about the choice) — in that case the answer is structured as clearly labeled, separate sections, not blended into one voice, using the same non-collapsing principle established for plural answers in Section 4.2.
- Re-evaluation materiality (Section 7.2) is extended so that a **Forecast's resolution** (the defined future event actually occurring or not) is itself always treated as material — every resolved forecast automatically triggers a calibration update (Section 9) regardless of importance rating, since forecast accuracy is only ever knowable in hindsight.

---

## 6. The Reputability Engine (judgment logic)

### 6.1 Seed criteria (bootstrap, not permanent doctrine)
At genesis, seeded with transparent, revisable starting heuristics: primary texts and their standard critical editions; peer-reviewed venues; recognized academic/scientific/archival institutions; official standards-body publications; internal consistency and independent corroboration relative to already-trusted material. Stored as version 0 of the standard, explicitly labeled as a starting point.

### 6.2 Continuous evidence accumulation
Every use of a source in a deliberation records an outcome against it: did its claims survive cross-examination? Were they independently corroborated? Did later evidence overturn them? This produces a running, evidence-based track record per source rather than a static label — mechanically, this is simply an aggregation over the claim structures (3.5) that cite it, keyed by source ID. Sources are stored content-addressed (per `body-design.md` Section 3.4), so a source's identity and its reputability record are tied to its exact content, not merely its location — a source can't quietly change underneath its own track record. As of Section 11, this same mechanism is extended to track human contributors as sources in their own right.

### 6.3 Graded, versioned, non-retroactive scoring
Sources receive a graded score (e.g., foundational / strongly corroborated / provisionally accepted / contested / rejected) with a written rationale and evidence trail. Grades move in either direction as evidence accumulates. Critically: **a source's grade at time-of-use is permanently attached to any answer that cites it** (Section 5.2) — later grade changes never rewrite history, they only affect *future* deliberations and trigger re-evaluation checks (Section 7) for past ones that relied on the now-changed grade.

### 6.4 Dispute resolution procedure
When two Master Agents disagree about a source's reputability, or a source is flagged contested (contradicted by a higher-graded source, unclear provenance, or suspected circularity), Logic runs a structured adjudication:
1. Restate the specific disputed claim(s) and the sources on each side.
2. Compare track records (6.2) and independence of corroboration — sources that merely cite each other are not independent corroboration, and Logic is specifically responsible for detecting that pattern.
3. Check for conflicts of interest and **category errors** — most importantly, a claim of faith being evaluated as if it were an empirical claim, or a forecast probability being conflated with a research-confidence score (Section 5.4). This check is routed to the relevant domain agents (Theology/Philosophy for faith-vs-empirical; Philosophy alone for research-vs-forecast-vs-recommendation), since Logic alone should not be the one deciding what counts as a category error in a domain it doesn't own (mirroring the humility principle in Section 4.3).
4. Issue a ruling with written rationale, logged permanently and reversibly on new evidence — no single Master Agent has unilateral blacklist/whitelist authority.

### 6.5 The standard itself evolves, nothing is destroyed
The reputability standard (6.1, as amended) is versioned like the Belief Graph: version N+1 supersedes N for new decisions, but full history of prior standards and which decisions were made under which version is retained permanently. Periodic idle-evolution review (3.6) re-examines the standard for internal consistency — e.g., has a criterion in the current version produced a pattern of disputes that suggests it's miscalibrated? That finding itself becomes a proposed amendment, logged and reviewed the same way a substantive dispute is.

### 6.6 Hard floor (not subject to the Engine's own revision)
Regardless of standard version: sources must be freely and legally accessible, no paid/metered service is ever used, and no unlawful action is taken or recommended. These are constitutional constraints on the Engine, not tunable heuristics — the Engine can change *how* it grades reputability, never *whether* these three hold. These floors are enforced as part of the non-compensatory integrity gates in Section 9.8.

### 6.7 Model Fitness Tracking
The Body's Local Model Serving Layer (`body-design.md` Section 4.5) makes any number of local models available on request, but deciding *which model should back which Master Agent for which kind of task* is a judgment call, not a resource-allocation decision — the same kind of judgment the Engine already applies to sources, extended to a second dimension.

- **Per-(agent, model) evidence accumulation.** Because every claim now carries `serving_model` (3.5), the same evidence-accumulation mechanism used for sources (6.2) is applied per agent-model pairing: did claims produced by the Engineering agent while backed by Qwen3-Coder-Next survive cross-examination at a higher rate than when backed by a generalist model? This is tracked continuously, not benchmarked once at model-admission time, because a model's fitness for a given agent's reasoning mode can only really be seen in how its outputs hold up under this system's own cross-examination — a generic leaderboard score is a reasonable prior, never the verdict.
- **Fitness informs routing, not correctness.** A low-fitness (agent, model) pairing doesn't make a claim automatically wrong — it lowers the claim's starting confidence pending its own cross-examination (exactly as a low-track-record human submitter's input still gets evaluated on its merits, Section 11.3), and it informs which model the Body's serving layer is asked for on the *next* similar task.
- **Model admission is a lightweight Reputability-style gate.** A new candidate model (evaluated by a human via the workbench pattern in `body-design.md` Section 4.5) is admitted at a provisional, low-confidence-weighted status, exactly like a newly ingested source at 6.1 — it earns a stronger standing only through accumulated evidence under 6.2's mechanism, never by manufacturer claims or benchmark marketing alone.
- **Never a hard floor override.** Model fitness never overrides 6.6 — a highly fit model backing an agent still produces claims subject to the full cross-examination and Synthesis Commit pipeline (Section 4.4); fitness affects *starting weight*, never *exemption from scrutiny*.

---

## 7. Re-evaluation Judgment

### 7.1 Importance rating
Assigned at submission and revisable: based on breadth of domains touched, how many other Belief Graph claims or questions causally depend on it, and any explicit priority given by the requester. This is a computed/estimated value, not purely user-declared — the framing round (3.1) contributes to it by identifying how many sub-questions and domains a question actually implicates.

### 7.2 Materiality: what counts as a "change worth reopening"
A Belief Graph delta is material to a dormant question if, and only if, at least one of the following holds:
- A claim the original answer's leading conclusion **directly cited** has changed reputability grade by more than a configurable threshold, or been newly contested/overturned.
- A newly ingested or newly corroborated/challenged claim exists in the Belief Graph that the framing round would now route to the same question (i.e., it's newly relevant, not just newly present).
- The question's own **frame** (3.1) has been flagged outdated by idle-evolution — e.g., an assumption the original framing treated as settled is now itself contested.
- The reputability *standard itself* (6.5) has changed version in a way that would alter the grade of a source the original answer relied on.
- A new, sufficiently weighted human input (Section 11.2) directly targets a claim the original answer relied on.
- The original answer was a **Forecast** (Section 5.4) whose defined resolution event has now occurred — always material, unconditionally.

Deliberately excluded from materiality: changes to claims the original answer did not rely on, changes below the confidence-shift threshold, and general corpus growth that doesn't newly implicate the specific question. This keeps re-evaluation proportionate rather than triggering on every corpus update.

### 7.3 Reopening procedure
When materiality is triggered for a sufficiently important dormant question, it re-enters the deliberation loop (Section 3) as if newly submitted, but with its prior answer and full prior deliberation trace available as *input context* (not as an unquestioned starting point — agents are expected to re-derive, not merely rubber-stamp the old answer). If the prior answer had been consolidated into deep-knowledge (Section 10), its full trace is first expanded back from cold archive (Section 10.5) before re-deliberation begins. The new answer is appended as a new version (per the Body's Question Ledger versioning), with an explicit diff against the prior version: what changed, which specific claim/grade/frame/human-input/forecast-resolution shift caused it, and whether the leading conclusion's confidence increased, decreased, or the conclusion itself reversed.

### 7.4 Why judgment here matters
This is deliberately not a simple "any change triggers a rerun" rule (which the Body could have implemented mechanically) nor a purely user-driven "only reopen when asked" rule (which would defeat the system's stated purpose of continual knowledge development). The materiality test in 7.2 is itself a piece of domain judgment — it requires knowing *why* a claim was cited, not just *that* it changed — which is why it belongs to the Brain rather than being reducible to Body-level graph-diffing.

---

## 8. Failure Modes Specific to Cognition

These are risks the architecture must actively guard against, distinct from the Body's resource/infrastructure failure modes:

| Failure mode | Guard in this design |
|---|---|
| **False consensus** — synthesis papering over a genuine cross-domain disagreement | Structured plural answers for jurisdictional conflicts (Section 4.2), mandatory dissent record |
| **Circular corroboration** — sources that just cite each other treated as independent support | Explicit independence check in dispute resolution (6.4.2) |
| **Category error** — faith-premised or normative claims stated with empirical-grade confidence, or forecast probability conflated with research confidence | `claim_type` and output-type tagging (3.5, 5.4) enforced mechanically; joint domain-agent review of category disputes (6.4.3) |
| **Overconfidence drift** — an agent's stated confidence not matching its actual track record | Per-agent calibration tracking (5.3), feeding into Section 9 evaluation |
| **Silent authority creep** — Logic (the procedural chair) starting to substantively adjudicate domain questions it has no jurisdiction over | Explicit jurisdictional limits on Logic's own role, stated and enforced in 4.2.3 and 6.4.3 |
| **Retroactive history rewriting** — a later grade/standard change altering the record of what was believed and why at the time | Non-retroactive grade attachment (6.3), versioned standard history (6.5), versioned answers (7.3) |
| **Stale framing** — a question's underlying assumptions going unexamined even as its cited claims are revisited | Frames are first-class, re-challengeable Belief Graph objects (3.1), explicitly included in materiality (7.2) |
| **Unfalsifiable claims presented as physical/empirical** | Physics agent's defeat-condition discipline (2.2); a claim it can't falsify is rerouted to Philosophy, not asserted as physics |
| **Silent style drift** — an agent stays accurate but stops reasoning like its domain | Domain Fidelity Score (Section 2.4), tracked separately from calibration |
| **Lossy or unaccountable compaction** — trimming knowledge in a way that silently discards the reasoning behind it | Fidelity-checked, non-destructive consolidation with full-trace cold archive (Section 10) |
| **Unjustified belief skew from human input** — a human contribution silently overriding accumulated evidence | Human input treated as an examinable, gradable claim, never auto-accepted at full weight (Section 11) |
| **Prompt/content injection via ingested corpus or human input** — text instructing the system, embedded in what should be evidence | Ingested content and human input are architecturally evidence only, never instructions (Section 12) |
| **Uncommitted/unauthorized canonical writes** — a claim entering the Belief Graph without surviving cross-examination and synthesis | Proposal-only writes, single Synthesis Commit boundary (Section 4.4) |
| **Silent model substitution** — a lower-capability local model quietly backing an agent (e.g., under VRAM pressure, `body-design.md` Section 4.5) without the drop in reliability being visible | `serving_model` recorded on every claim (3.5); Model Fitness tracking (6.7) surfaces a capability drop as a measurable, agent-specific signal rather than an invisible one |
| **Unverified execution claims** — Engineering asserting code "works" without it actually having been run | `executable` claim type (3.5) tied to real sandboxed execution (Section 2.2); an unexecuted code claim cannot carry `claim_type: executable` |

---

## 9. Evaluation Strategy — how we'll know if the Brain is actually working

This is the section that keeps the rest of this document honest. An architecture that *sounds* rigorous is not the same as one that *reasons* well, and the gap between those two is exactly where a system like this is most likely to fail quietly — by producing confident, well-formatted, wrong answers.

### 9.1 Ground-truth benchmarks (necessary but not sufficient)
For Mathematics and Logic especially, use problems with known, checkable answers (proof exercises, formal validity puzzles) to test whether the loop's actual mechanics (derivation, defeat conditions, cross-examination) produce correct results before trusting it on open questions where there's no ground truth to check against. These same benchmark questions also serve as the baseline-fingerprint source for Domain Fidelity Monitoring (Section 2.4).

### 9.2 Adversarial questions
Deliberately construct questions designed to trigger each failure mode in Section 8 — a question with a plausible-sounding but circular pair of sources, a question that conflates an ought and an is, a question where the "obvious" first-pass answer is wrong and only survives if cross-examination actually works, a question with injected instruction-like text embedded in source material. Passing these is a stronger signal than passing straightforward questions.

### 9.3 Calibration audits (ongoing, not one-time)
Use the per-agent calibration record (5.3) as a continuous health metric, not a one-off test — an agent whose confidence-to-outcome mapping drifts over time is a concrete, measurable regression signal, unlike "does this answer seem good."

### 9.4 Held-out re-evaluation review
Periodically sample re-evaluation events (Section 7.3) and manually check: was the materiality judgment correct? Did the new answer actually represent better reasoning, or just different reasoning? This is a check on Section 7's judgment quality specifically, since a bad materiality test could either thrash (reopening trivially) or stagnate (never reopening when it should).

### 9.5 Consolidation fidelity audits
Periodically expand a sample of compacted deep-knowledge nodes (Section 10) back to their full archived trace and verify the compact form still accurately represents the full reasoning — a direct check on whether consolidation (10) is losing meaning, not just size.

### 9.6 What this can't fully solve
No evaluation suite proposed here can certify that the Master Agents reason soundly on genuinely novel, high-stakes questions outside anything resembling their benchmarks or adversarial test set — that residual uncertainty is inherent to the problem, not a gap in this document. The honest position is: build the evaluation discipline in from the start (Sections 9.1–9.5), treat every deployed answer's confidence as provisional against that discipline, and expect the evaluation strategy itself to need revision as the system is actually exercised.

### 9.7 Baseline and ablation comparison
Reasoning quality claims are only meaningful relative to simpler alternatives. The evaluation harness maintains, alongside the full system:
- **B0 — retrieval-only control:** return the most relevant retrieved passages with no synthesis, no cross-examination, no confidence calibration.
- **B1 — single-agent baseline:** one generalist reasoning process, no domain specialization, no Master Agent structure, answering the same questions.
- **A1 — full Athenaeum workflow:** the complete framing → exploration → cross-examination → synthesis loop.
- **Required ablations:** variants of A1 with cross-examination removed, with synthesis collapsed to a naive majority vote, or with provenance/reputability weighting removed.
If A1 does not measurably outperform B0/B1 on the metrics in 9.1–9.2, and the ablations don't show each removed component actually contributing, that is treated as a real finding about the architecture, not a testing artifact to explain away.

### 9.8 Non-compensatory integrity gates
Certain failures block an answer or a release regardless of how well everything else scores — a high research-quality score never excuses a violation of these:
- Sources used that are paid/metered, illegally accessed, or unlicensed (Section 6.6).
- Fabricated or unverifiable provenance (a claim citing a source that doesn't actually support it).
- Evaluation or calibration figures computed against contaminated data (Section 9.9).
- A canonical write that bypassed the Synthesis Commit boundary (Section 4.4).
- A category error (Section 5.4, 6.4.3) reaching the final answer uncorrected.
These are pass/fail, not part of a weighted score — a system that is excellent everywhere else but fails one of these has still failed.

### 9.9 Held-out, contamination-resistant evaluation
Benchmark and adversarial question sets (9.1–9.2), and their correct answers/labels, are kept in an isolated store that ordinary retrieval and ingestion (Body-mechanical) cannot access — the Master Agents can be tested against them without ever having had the opportunity to ingest the answer key through the normal corpus-growth process. The same isolation applies to Forecast resolution outcomes (5.4) before their resolution date: a forecast's true outcome is never visible to the system's own retrieval until the resolution event has actually occurred, preventing the system from ever appearing better-calibrated than it is by having seen the answer. This resolves the evaluation-contamination concern raised as an open question in the prior revision of this document.

---

## 10. Knowledge Consolidation and the Deep-Knowledge Tier

The deliberation loop, run continuously across many concurrent and idle-evolution questions, will generate an enormous volume of raw reasoning traces — most of it useful once, rarely revisited, and not worth the DRAM/graph-traversal cost of keeping at full fidelity forever. At the same time, the system's core purpose is to *develop durable knowledge*, not just answer questions, so trimming cannot mean discarding the reasoning behind a conclusion — only demoting its level of detail while keeping it fully recoverable. This section proposes a three-tier knowledge maturity model, run as a Brain-owned judgment process during idle-evolution, targeting the Body's existing storage tiers (Section 1.2) as its mechanism.

### 10.1 Maturity tiers
- **Tier A — Working traces:** full, round-by-round deliberation detail (every candidate claim, challenge, and intermediate step) for questions that are active, recently answered, or not yet stable. Lives in the Belief Graph at full fidelity.
- **Tier B — Validated claims:** claims that have survived at least one full cross-examination round without being overturned, retained with their essential provenance and confidence, but with redundant or superseded intermediate reasoning steps pruned (e.g., abandoned candidate branches from exploration that lost to a stronger claim are summarized as "considered and rejected because X," not kept in full).
- **Tier C — Deep-knowledge (canon):** claims that have additionally survived multiple idle-evolution re-challenge cycles across a meaningful span of time, have independent corroboration from multiple high-reputability sources, and show stable confidence (no meaningful drift) across those cycles. These are stored as compact, canonical propositions: the statement, its current confidence, a minimal essential provenance chain, and a pointer/reference to the full historical trace rather than the trace itself.

### 10.2 Promotion criteria (A → B → C)
Promotion is judgment, not a timer:
- **A → B** requires: the claim survived cross-examination (corroborated or successfully defended against challenge) in its originating round, and — per Section 4.4 — has passed a Synthesis Commit.
- **B → C** requires: survival across at least N idle-evolution re-challenge cycles (configurable), corroboration from at least M independent, sufficiently-graded sources (configurable), and a calibration/confidence trend that is flat or improving, not declining — a claim whose confidence has been eroding across cycles is specifically excluded from promotion even if it hasn't yet been overturned, since that trend is itself informative.

### 10.3 The compaction step itself
Compaction is performed by a dedicated idle-evolution process, jointly specified by Logic (formal correctness of the compacted representation) and Philosophy (whether the compacted statement still accurately represents what was actually concluded, without smuggling in false precision or losing important qualification). Concretely: the full Tier A/B trace is summarized into the Tier C canonical form, the full trace is written content-addressed to the Body's cold archive (Tier 3) rather than deleted, and the active Belief Graph node is replaced with the compact form plus an archive pointer.

### 10.4 Nothing is ever truly deleted
This mirrors the append-only philosophy already used for checkpoints and the reputability standard: compaction changes what's resident and readily traversable, never what's recoverable. Any compacted node can be expanded back to its full trace on demand — required, not optional, whenever a compacted claim is challenged again (Section 10.5) or a re-evaluation touches it (Section 7.3), so compaction never compounds an error by reasoning only from a lossy summary when it matters.

### 10.5 De-compaction on challenge
If a Tier C (or Tier B) node is challenged during a later cross-examination round or targeted by re-evaluation, the system first retrieves its full archived trace before allowing further reasoning to build on it — the compact form is a fast-path for ordinary retrieval and citation, never the basis for resolving a live dispute about the claim itself.

### 10.6 Why this matters for the "infinite knowledge" goal
Without consolidation, the system's stated goal of continually developing knowledge without bound runs directly into DRAM's finite size (Body Section 5) far sooner than the corpus itself would exhaust. Consolidation is what lets "the graph keeps growing forever" coexist with "the hot, actively-reasoned-over graph stays small enough to keep fast" — durability lives in the archive, immediacy lives in the compacted canon, and the two are reconciled by the de-compaction guarantee in 10.4–10.5 rather than by ever discarding anything.

---

## 11. Human Input and the Human Checkpoint

Human input is powerful and risky in a specific way this system has to take seriously: because it comes from a person, it will tend to carry more perceived authority than an equivalently-evidenced automated claim, and a single human contribution — especially from someone treated as an expert — could otherwise skew established belief far out of proportion to its actual evidentiary weight. The design below treats human input as a first-class, examinable input to the graph, never as a silent override, while still giving it a real and meaningful path to change the system's mind, including overriding consolidated deep-knowledge when it's genuinely warranted.

### 11.1 Human input enters as a claim, not a command
A human contribution is submitted using the same normalized claim structure as everything else (Section 3.5), with `claim_type: human_input`, plus required metadata:
- **Submitter record** — a persistent identifier tied to a governed role (Section 11.7), not just an arbitrary stable handle.
- **Stated justification** — the human's own reasoning for the input, required, not optional; unjustified assertions are accepted into the graph as low-weight testimony at most, never as unexamined fact.
- **Declared scope** — which existing claim(s) or question(s) the input is meant to bear on, so it can be routed to the right agents rather than entering as an untargeted, ambient influence on the whole graph.

### 11.2 Human input is examined, never auto-accepted at full weight
A human_input claim goes through the same cross-examination round (Section 3.3) as any other claim: Master Agents corroborate, challenge, request clarification, or abstain, exactly as they would for a claim sourced from a text. It is a **proposal** like any other (Section 4.4) and only affects the canonical Belief Graph via a Synthesis Commit. This is the core safeguard against unjustified belief skew — the human's *justification* is what's being evaluated, on its merits, using the same standards (independence of corroboration, formal validity, category-appropriateness) applied everywhere else in the system, not the fact that a human said it.

### 11.3 Humans are graded like sources, transparently
The Reputability Engine (Section 6) extends its evidence-accumulation mechanism (6.2) to submitter records: does this person's input tend to survive cross-examination, or tend to be overturned? This produces a track record exactly like a source's, visible and auditable, and used the same way — as a *prior*, not a verdict. A low-track-record submitter's well-justified, well-evidenced input on a given occasion is still evaluated on its own merits and can still succeed; a high-track-record submitter's poorly-justified input can still fail cross-examination. The track record informs how much initial weight an input's confidence estimate should carry pending its own examination, nothing more.

### 11.4 Full rejection is allowed, and must be justified
The system can fully reject a human input's claim, exactly as it can reject any other contested claim — via the same dispute-resolution procedure (Section 6.4), chaired by Logic, checked for category errors by Theology/Philosophy where relevant. A rejection is not a silent drop: it produces a written rationale, logged permanently to the Belief Graph and visible to the submitter, and — like every other ruling in this system — reversible later on new evidence. This is the same non-negotiable transparency standard applied to source-reputability disputes (6.4.4), extended to people.

### 11.5 Materiality and the human checkpoint
Because a human contribution can legitimately warrant a significant, deliberate shift in established belief — including overturning a consolidated deep-knowledge item — human input is explicitly folded into the re-evaluation materiality test (Section 7.2): a sufficiently weighted human input targeting a claim an existing answer relies on is, by definition, material, and triggers reopening. Given the outsized potential impact, this is also precisely where the human checkpoint applies:

- Any re-deliberation triggered by human input that would **change a leading conclusion**, **overturn a Tier C deep-knowledge item** (Section 10.1), or touch a question above a configurable importance threshold (Section 7.1) produces its new answer in a `pending_human_checkpoint` status rather than `current`.
- A human reviewer holding the **Reviewer** role (Section 11.7) — not necessarily the original submitter — must approve, reject-with-note (which itself re-enters the loop as a new human_input claim, not a unilateral override), or request further deliberation before the answer becomes `current`.
- Ordinary human input that doesn't cross these thresholds flows through cross-examination and synthesis exactly like any other claim, without requiring a checkpoint — the checkpoint exists for consequence, not for gatekeeping every human contribution equally.
- This checkpoint status is added to the answer lifecycle referenced in Section 5.2, alongside the Body's Question Ledger versioning (`draft → pending_human_checkpoint → current → superseded`).

### 11.6 Why this balance, specifically
Two failure modes were both unacceptable: treating human input as automatically authoritative (which would let a single person silently redirect the system's accumulated, cross-examined knowledge without scrutiny — precisely the "skew existing beliefs in a not-insignificant way" risk this design was asked to address) and treating it as just more text to be graded coldly with no acknowledgment of its distinct weight and consequence (which would waste the genuine value of expert human correction and make the checkpoint meaningless). The design threads this by making human input fully examinable and fully rejectable with justification (addressing the first risk) while guaranteeing that its highest-consequence effects never take effect silently, but land in front of a human for confirmation (addressing the second).

### 11.7 Human governance roles
Human interaction with the system is scoped through defined roles rather than an undifferentiated notion of "a human":
- **Owner** — accountable for the system's operating parameters (thresholds in Section 7.1, 7.2; consolidation criteria in 10.2); can amend configuration but cannot unilaterally force a claim into the Belief Graph outside the normal proposal/commit path.
- **Reviewer** — authorized to approve, reject-with-note, or request further deliberation on `pending_human_checkpoint` answers (11.5); a Reviewer's own submissions still go through the same 11.1–11.4 process as anyone else's — the Reviewer role grants checkpoint authority, not evidentiary authority.
- **Member** — may submit human_input claims (11.1) and view answers; submissions are tracked under 11.3 like any other contributor's.
- **Service** — a non-human, automated identifier (e.g., an ingestion process or scheduled job) whose submissions are tracked distinctly from Member submissions in the reputability record, so an automated pipeline's track record is never silently conflated with a human's.
Role separation matters most for the checkpoint: the person whose input triggered a `pending_human_checkpoint` state should not, by default, also be the one who clears it — this is a basic conflict-of-interest safeguard, not a statement of distrust in any individual.

---

## 12. Content Integrity: Corpus and Human Input Are Evidence, Never Instructions

This section makes explicit and architectural a rule the rest of the design has relied on implicitly: nothing the system reads — an ingested source, a retrieved passage, a human submission — is ever executed as an instruction to the reasoning process. Everything is evidence to be evaluated, always.

### 12.1 The core rule
Ingested corpus content and human input enter the system exclusively as **candidate claims** (`claim_type: empirical | formal | normative | traditional | human_input`) subject to the full deliberation loop (Section 3) — never as directives that change how a Master Agent behaves, what it prioritizes, or which procedures run. A document that contains text formatted to look like a system instruction, a role reassignment, or a command to skip cross-examination is, mechanically, just a claim whose `statement` happens to contain that text — it is evaluated for truth and reputability like any other claim, and has zero special effect on the loop's own control flow.

### 12.2 Why this matters specifically here
This system is unusually exposed to this risk by design: it deliberately, continuously ingests freely available material from the open web (Section 8.2 of the corpus policy) and explicitly invites human contributions with real potential to move belief (Section 11). Both are exactly the channels an adversary would use to try to inject instruction-like content — a poisoned source claiming to be an authoritative update to the Reputability standard, or a human submission worded to look like a system-level command rather than a claim. The architecture closes this by construction rather than by vigilance: there is no code path by which ingested text or human text can reach anything other than the claim pipeline, so there is nothing for an injection attempt to hijack even if cross-examination were to (incorrectly) rate it highly.

### 12.3 Interaction with the Reputability Engine and dispute resolution
An ingested or human-submitted item that reads as an attempt to instruct rather than inform is itself evidence relevant to that source's or submitter's reputability (Section 6.2, 11.3) — a pattern of instruction-like submissions is exactly the kind of signal the dispute-resolution procedure (6.4) should treat as grounds for a low grade or full rejection, logged with that rationale.

### 12.4 Interaction with Section 4.4's commit boundary
Because the commit boundary already guarantees that nothing becomes canonical without surviving cross-examination and an explicit Synthesis Commit, an injection attempt has no faster path into the Belief Graph than any ordinary false claim does — it must actually out-argue independent corroboration and survive challenge, the same bar every other claim clears.

---

## 13. Work Breakdown (Brain-only phases, from the full task backlog)

Corresponds to Phases 4, 5, and 8 of the full system backlog, plus the evaluation, consolidation, human-input, and content-integrity work introduced in this and the prior revision.

**Phase 4 — Deliberation Loop**
1. Framing round logic (decomposition, assumption-surfacing, routing, output-type classification) as an isolated, testable function against a set of hand-written example questions.
2. Parallel exploration round: per-agent candidate claim generation against the normalized structure (3.5), tested against stub corpora with known expected candidate claims.
3. Cross-examination round: corroborate/challenge/clarify/abstain logic, including the independence check (6.4.2) and jurisdiction-check enforcement (3.5).
4. Synthesis round: ordinary evidence-weighted path (4.1), the jurisdictional-conflict path (4.2) with structured plural output, and the Synthesis Commit boundary itself (4.4).
5. Full end-to-end wiring of 1–4 for a single question — first "it actually reasons about something" milestone.

**Phase 5 — Reputability Engine (judgment)**
6. Seed criteria encoding (6.1) as versioned, human-readable config.
7. Evidence accumulation hook (6.2) wired into cross-examination outcomes, including the submitter-tracking extension (11.3) with role-aware tracking (11.7).
8. Grading logic (6.3) with non-retroactive attachment verified against a test case (grade changes after an answer is produced must not alter that answer's record).
9. Dispute resolution procedure (6.4), including the independence and category-error checks, tested against constructed disputes with known correct rulings.
10. Standard-versioning and idle-review logic (6.5).

**Phase 7 — Output Types** *(new)*
11. Output-type classification logic in the framing round (5.4, 3.1).
12. Research Answer synthesis path (extends 4.1/4.2 with citation/alternative/dissent structure).
13. Forecast synthesis path: resolution criterion capture, probability calibration distinct from research confidence, resolution-triggered materiality (7.2, 9.9).
14. Recommendation synthesis path: objective/constraint capture, tradeoff and reversibility structure, explicit value-ladenness flagging.
15. Multi-type answer composition (a question requiring more than one type, non-collapsing presentation per 5.4).

**Phase 8 — Re-evaluation Judgment**
16. Importance rating computation (7.1), tested against questions of varying breadth/dependency.
17. Materiality test (7.2) as an isolated function against synthetic Belief Graph deltas, including negative test cases and human-input/forecast-resolution-triggered cases.
18. Reopening/versioning wiring (7.3), verified against the Body's Question Ledger versioning contract, including full-trace de-compaction on reopen.

**Phase 9(b) — Evaluation Infrastructure**
19. Ground-truth benchmark set construction and scoring harness (9.1), reused as the Domain Fidelity baseline source (2.4).
20. Adversarial question set construction, one per failure mode in Section 8 (9.2), including injection-attempt fixtures for Section 12.
21. Calibration tracking dashboard/query over the Section 5.3 record (9.3).
22. Re-evaluation audit sampling process (9.4).
23. Consolidation fidelity audit process (9.5).
24. Baseline/ablation harness (B0/B1/A1 + component ablations) (9.7).
25. Non-compensatory integrity gate checks wired as release blockers (9.8).
26. Held-out, contamination-isolated evaluation and forecast-outcome store (9.9).

**Phase 11 — Domain Fidelity Monitoring**
27. Jurisdictional overreach rate tracking, aggregated from existing cross-examination logs (2.4.1).
28. Per-agent reasoning-fingerprint marker extraction and baseline computation (2.4.1).
29. Combined Domain Fidelity Score computation and idle-evolution review trigger (2.4.2–2.4.3).
30. Re-grounding mechanism and escalation-to-checkpoint path (2.4.3).

**Phase 12 — Knowledge Consolidation**
31. Tier A→B pruning logic (redundant/superseded branch summarization).
32. Tier B→C promotion criteria evaluation (survival count, independent corroboration count, confidence-trend check).
33. Compaction process itself: canonical-form generation, content-addressed cold-archive write, active-node replacement with pointer.
34. De-compaction path: full-trace retrieval on challenge or re-evaluation touch, wired into Phase 8's reopening logic.

**Phase 13 — Human Input Pipeline and Governance**
35. Human input submission structure (claim + justification + declared scope) and its entry into the normal claim/cross-examination flow.
36. Submitter track-record extension to the Reputability Engine (11.3).
37. Materiality integration: human input and forecast resolution as re-evaluation triggers (7.2, 11.5).
38. Human checkpoint status and lifecycle (`pending_human_checkpoint`), including reviewer approve/reject-with-note/request-more-deliberation paths.
39. Role model implementation (Owner/Reviewer/Member/Service) and conflict-of-interest enforcement on checkpoint clearance (11.7).

**Phase 14 — Content Integrity** *(new)*
40. Enforce claim-only ingress: verify by construction that no code path lets ingested or human text alter control flow, only claim content (12.1).
41. Instruction-like-content detection heuristic feeding into reputability signals (12.3) — informational only, never a gate on its own.

**Phase 15 — Engineering Agent and Model Fitness** *(new)*
42. Engineering agent implementation: specify → implement → execute/test → verify loop, tested against a set of hand-written coding tasks with known-correct and known-buggy solutions.
43. Sandboxed execution integration against the Body's execution capability (`body-design.md` Section 4.6); `executable` claim type wired to real pass/fail test results, never asserted without an actual run.
44. Cross-cutting verification routing: another agent's formalizable claim (a Mathematics combinatorial check, a Physics simulation) can be routed to Engineering and the result fed back as a corroborating/challenging claim.
45. `serving_model` field wired through the claim pipeline (3.5) end-to-end.
46. Per-(agent, model) evidence accumulation and Model Fitness score computation (6.7).
47. Model admission gate: provisional-status intake for a newly admitted local model, tested against the same non-retroactive-attachment discipline as source grading (6.3).

---

## 14. Open Questions for Review

1. **Plural-answer usability:** structured plural answers (4.2), and now multi-type answers (5.4), are more honest but harder for a requester to act on than a single conclusion — whether and how to eventually present a "practical recommendation" layered on top of an honest plural/multi-type answer, without collapsing the honesty, is unresolved.
2. ~~Cross-agent training drift~~ — resolved by Section 2.4 (Domain Fidelity Monitoring), pending validation once implemented.
3. ~~Evaluation set contamination~~ — resolved by Section 9.9 (held-out, contamination-resistant evaluation and forecast-outcome isolation).
4. **Confidence aggregation across a plural or multi-type answer:** Section 5.1 defines calibration per claim, but there's no defined method yet for what "overall confidence in the system's response" means when the response is structured-plural (4.2) or spans multiple output types (5.4) rather than being singular.
5. ~~When human review re-enters the loop~~ — resolved by Section 11.5 (human checkpoint) and 11.7 (governance roles), with conflict-of-interest separation now specified.
6. **Submitter identity and Sybil risk:** role-gating (11.7) narrows this — a Member identity is at least tied to a governed role rather than an arbitrary handle — but nothing yet prevents one person from holding multiple Member identities to manufacture an artificially strong track record before submitting an influential, under-scrutinized claim. Partially mitigated, not resolved.
7. **Consolidation threshold tuning:** the specific values for "N idle-evolution cycles" and "M independent corroborating sources" (10.2) are left as configurable but unset — set too low, Tier C fills with prematurely "canonized" claims; set too high, the system never consolidates enough to solve the DRAM-growth problem it exists to solve.
8. **Instruction-detection false negatives** *(new)*: Section 12.2's core defense is structural (no code path for text to become an instruction), which is the right primary defense, but the heuristic detector in 12.3/Phase-14-task-41 that feeds reputability signals is necessarily imperfect — how much weight that heuristic should carry in a reputability ruling, versus being purely advisory, isn't yet specified.
9. **Sandbox trust boundary** *(new)*: Engineering's `executable` claims (2.2, Section 8) are only as trustworthy as the isolation of the Body's execution sandbox (`body-design.md` Section 4.6) — this document assumes that sandbox is genuinely isolated (no network egress, no persistence beyond the sandbox, resource-bounded) but does not itself design or verify that isolation; it is a hard dependency worth flagging rather than assuming away.
10. **Model Fitness cold-start** *(new)*: a newly admitted model (6.7) has no track record yet, and the system needs a defined default starting weight for a provisional model before evidence accumulates — too generous, and an unproven model gets outsized early influence; too conservative, and a genuinely better model takes unnecessarily long to earn appropriate trust. Not yet specified.

---

*End of Brain design document. This is the harder, less certain half of the system, and is treated that way throughout: concrete where the design allows it, explicit about uncertainty where it doesn't.*
