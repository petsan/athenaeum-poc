# Open owner decisions — briefs

Each brief covers one call that is the owner's to make. **Decisions 2–5 and 7–10 were made on 2026-09-26 (marked "Decided" below); 6 awaits the owner reading the draft.** It gives the evidence gathered so far, the realistic options, what each costs, and a recommendation. None of the decided items is implemented yet (see batch 10 in `docs/progress.md`); the numbers match `docs/progress.md`'s owner-decision list. Written 2026-09-26, at the end of batch 9.

---

## 2. The flaky `qwen2.5-1.5b` factual assertion

**Evidence.** `test_model_serving_real.py::test_model_serving_layer_routes_real_request_through_cpu_fallback` asserts that a 1.5B model says "jupiter" for "Name the largest planet". It has failed about one full run in seven (the model says "Saturn"), and passes on immediate re-runs (§59, §74). The test exists to prove that CPU-fallback *routing* works, and it does.

**Options.**
- **(a)** Assert only a non-empty completion from the right backend and model. The test then checks what it is for. Cost: no factual check on this path.
- **(b)** Keep the assertion but ask something a 1.5B model can't plausibly get wrong (e.g. "What is 2+2?"). Cost: still probabilistic, just much less often.
- **(c)** Leave it. Cost: roughly one full run in seven goes red for no code reason, which trains everyone to ignore red.

**Recommendation: (a).** Model quality isn't what this test measures. If a factual probe is wanted, it belongs in a separate, non-gating quality report (the live smoke, `scripts/live_smoke.py`, is the natural home).

**Decided (owner, 2026-09-26): (a).** Assert a non-empty answer from the right backend and model only.

---

## 3. Engineering's reasoning style while the sandbox is off

**Evidence.** Engineering's rounding claims come from an in-process `decimal` computation but are typed `executable`, which the design reserves for real sandboxed execution (§3.5, §8). Retyping them `formal` makes every rounding answer register as Engineering drifting out of its domain, because its fidelity fingerprint is literally `claim_type == "executable"`. Widening the fingerprint to accept `computed:` provenance makes Engineering indistinguishable from Mathematics (known-bugs.md, open limitations). The sandbox stays off by hard constraint on this host.

**Options.**
- **(a)** Retype them `formal`, and give Engineering a fingerprint of its own that doesn't depend on the sandbox: *claims that name an implementation convention or standard* (IEEE-754, a file format, a protocol). That is what actually separates "2.5 rounds to 2 under IEEE-754" from Mathematics' convention-free claims. Cost: a new fingerprint check, and existing fixtures change type.
- **(b)** While the sandbox is off, Engineering abstains from claims it would normally verify by execution. Cost: the Engineering-vs-Mathematics plural answer on rounding, one of the clearest demonstrations of jurisdictional conflict, disappears until the sandbox is enabled.
- **(c)** Keep the mislabel, documented. Cost: an `executable` claim that nothing executed, the exact failure mode §8 warns about.

**Recommendation: (a).** It makes the claim type true and keeps the plural answer. It also gives Engineering a style that stays meaningful whether or not a sandbox exists.

**Decided (owner, 2026-09-26): (a).** Retype the rounding claims `formal`; Engineering's fingerprint becomes "names an implementation standard".

---

## 4. Which models to admit, and wiring fitness into the API

**Evidence.** The admission gate (§48) exists, but no model has been admitted, and the API passes no fitness store, so model-backed claims are currently *not* fitness-weighted at all in the deployed path. The only model the agents ask is `DEFAULT_MODEL` (OLMo 3 7B). The batch 9 live run showed that model producing correct short answers ("Gravity") once its run-on output is cut (known-bugs.md #35).

**Options.**
- **(a)** Admit OLMo 3 7B with a written rationale, and wire a `ModelFitnessStore` into the API. Its claims start at the cold-start weight of 0.5 and earn more (or less) per agent from outcomes. Cost: model claims immediately weigh half of today's unweighted value.
- **(b)** Wire the store without admitting anything. Model claims weigh 0: they can be committed but can never lead. Cost: model-only questions (e.g. "what force holds the moon in orbit?") would have no leading conclusion.
- **(c)** Leave both unwired (today). Cost: model output weighs the same as a deterministic proof, which is the outcome §6.7 exists to prevent.

**Recommendation: (a)**, for OLMo 3 7B only. Leave the smaller model-lab models unadmitted until each has a stated reason to be asked.

**Decided (owner, 2026-09-26): (a).** Admit OLMo 3 7B, with a written rationale, and wire a `ModelFitnessStore` into the API.

---

## 5. Should human input trigger a checkpoint only above an importance threshold?

**Evidence.** `human_input.trigger_checkpoint_if_needed` checkpoints on *any* material human input. It was written before importance ratings existed (§45). §11.5 speaks of an "importance-thresholded question", and `importance_rating` now exists to supply that threshold. This changes tested governance behaviour, which is why it was left alone.

**Options.**
- **(a)** Checkpoint only when the question's importance is at or above the re-evaluation threshold (0.3, a placeholder). Low-importance questions take human input as an ordinary examinable claim, with no reviewer step. Cost: less oversight on small questions. Human input still can't command anything there; it is cross-examined like any claim.
- **(b)** Keep checkpointing everything. Cost: reviewer load grows with every human contribution, however minor, and §11.5's wording is not followed.

**Recommendation: (a)**, with the threshold stated in config next to the re-evaluation one, so the two can be tuned together.

**Decided (owner, 2026-09-26): (a).** Checkpoint human input only at importance >= the re-evaluation threshold, configured alongside it.

---

## 6. Adopting `README.draft.md`

**Evidence.** The public README's body predates batches 1–9. The draft (local, excluded from git) describes the system as it now is, and has been refreshed at every batch's end. The README's top notice and the LICENSE are untouched by it and stay that way.

**Options.** (a) adopt it as the README body after reading it; (b) adopt with edits; (c) keep the current body.

**Recommendation:** read it and choose (a) or (b). It was written for a reader evaluating the work, which matches the stated purpose of the repository.

---

## 7. How a reviewer approves, and whether to allow ingestion over HTTP

**Evidence.** The API has no authentication, and binds `0.0.0.0` by default. So approving a human checkpoint and submitting URLs for ingestion (a server-side request forgery risk) are both Python-only by design (Phases Y, Z). Pending checkpoints are visible read-only in the client.

**Options.**
- **(a)** Network-level only: bind to localhost and reach it through SSH port forwarding or a private overlay network. Then add the write endpoints, trusting anyone who can connect. Cost: no per-reviewer identity, so §11's role separation and conflict-of-interest checks would need the reviewer id asserted by the caller.
- **(b)** A per-reviewer token in a local config file (never in the repo), checked on write endpoints only, with the reviewer id derived from the token. Cost: a small amount of code and key handling; no paid service involved.
- **(c)** Keep it Python-only (today). Cost: approvals need shell access.

**Recommendation: (b)** once there is more than one reviewer; **(a)** is acceptable while the owner is the only reviewer. Either way, the ingestion endpoint should also check the target URL's host against a curator allow-list, not just the caller.

**Decided (owner, 2026-09-26): (b).** Per-reviewer tokens from a local config file (never in the repo), checked on write endpoints; the reviewer id comes from the token; ingestion checks URL hosts against a curator allow-list.

---

## 8. Long-term storage layout for the ledger and graph

**Evidence (§76).** Every write snapshots the whole store. Phase AB cut total storage by 70% (161 → 49 MB for 60 questions), but the ledger still grows quadratically. It is 55% of the total, and roughly 6–7 GB by 1,000 questions. The Belief Graph has the same shape at a smaller scale. The design requires append-only logs and never overwriting.

**Options.**
- **(a)** One checkpoint log per question for the ledger, with a small index log listing questions. Each write then costs one question's size, and append-only holds per log. Cost: a storage-format change and a one-time migration; cross-question reads touch many logs.
- **(b)** Delta checkpoints (append the change, periodically a full snapshot). Cost: reads must replay, and integrity checks get more complex.
- **(c)** Prune or compact superseded snapshots. Cost: it contradicts append-only as written; history of *states* is lost, though the ledger's own versions are kept.

**Recommendation: (a) for the ledger** first, since it is the dominant cost and a question is the natural unit. Measure again with `scripts/measure_storage.py` before touching the graph.

**Decided (owner, 2026-09-26): (a).** One checkpoint log per question for the ledger, with a one-time migration; re-measure before touching the graph.

---

## 9. Should grade *upgrades* from routine use reopen answers?

**Evidence (§81).** Every deliberation citing a source records a corroboration, so a commonly used source rises to `foundational` on its fifth use. Since Phase X gave §7.2's grade trigger full reach, that upgrade reopens every earlier answer that used it. Under today's rule (any one-step change is material) this is correct, but it is churn: nothing new was learned; the source was merely used again.

**Options.**
- **(a)** Only downgrades are material. An upgrade can strengthen a conclusion but can't make it wrong, so it is picked up at the answer's next reopen for any other reason. Cost: an answer's displayed weights lag behind an upgrade.
- **(b)** Upgrades are material only if the corroborations behind them came from *other* questions than the answer being judged. Cost: tracking the origin of every corroboration.
- **(c)** Keep the current rule. Cost: reopen storms as common sources mature.

**Recommendation: (a).** It matches the intent of re-evaluation (catch answers that may now be wrong) at no bookkeeping cost. Note that §7.2's wording is symmetric, so this is a design change, not a fix.

**Decided (owner, 2026-09-26): (a).** Only downgrades are material; upgrades are picked up at the next reopen for any other reason.

---

## 10. May models challenge claims during idle re-examination? (new)

**Evidence.** Idle evolution re-challenges committed claims with today's agents. But the agents' `cross_examine` methods only recognise specific claim shapes, so a committed *model-backed* claim of an unfamiliar shape survives by default (known-bugs.md, open limitations). The obvious remedy is to let a model cross-examine. But a challenge moves reputability, fitness and calibration, and a small model's challenges would be noisy.

**Options.**
- **(a)** Models may challenge, but a model-only challenge is recorded as dissent without counting toward reputability or fitness until the challenging model is admitted and established (§48's `established` standing).
- **(b)** Models never challenge; only deterministic checks do. Cost: model-backed claims stay effectively unexamined.
- **(c)** Models challenge with full weight. Cost: noise propagates into grades.

**Recommendation: (a).** It closes the gap without letting an unproven model move the system's judgment of sources.

**Decided (owner, 2026-09-26): (a).** Models may challenge; a model-only challenge is dissent and counts toward reputability and fitness only once the challenging model is admitted and established.
