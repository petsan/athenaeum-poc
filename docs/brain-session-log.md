# Brain Backlog — Running Decision Log

Judgment calls made while working through the Brain backlog (`progress.md`
§26, ordered per the 2026-09-22 planning conversation), with the reasoning,
so nothing gets decided silently. Newest entries at the bottom.

---

## 2026-09-22 — Physics/Philosophy/Theology agent design choices

**Q: What real, verifiable computation grounds each of the three new
agents, matching the existing "no hand-waved text" discipline
(`agents.py`'s own module docstring) that Mathematics/Logic/Engineering
already hold to?**

- **Physics** → real kinematics: free-fall time from a stated drop height
  via `d = 0.5 * g * t^2`, cross-examined by independent re-derivation, the
  same pattern Mathematics already uses for primality. Chosen because it's
  genuinely falsifiable (§2.2's stated requirement for Physics specifically)
  and mechanically checkable, not because it's the most interesting physics
  could do.
- **Philosophy** → is-ought category-error detection. Philosophy's design
  role (§2.2) is framing/assumption-surfacing, not first-order domain
  claims — so unlike the other five agents, its "computation" is a
  detection rule, not a formula: on a normative question, it names the
  is-ought gap as an explicit hidden assumption instead of answering the
  substantive question; on cross-examination, it flags any *other* agent's
  claim typed `empirical` that smuggles a normative conclusion. This is the
  literal category-conflation check §2.2 calls out by name for Philosophy,
  made mechanical via keyword detection on modal words (should/ought/must)
  rather than left as prose vigilance.
- **Theology** → a small, real lookup table of three named traditions'
  documented positions (Stoicism, Buddhism, Epicureanism), always emitted
  as `claim_type: traditional` with confidence capped at 0.75. Cross-
  examination enforces §6.4's discipline mechanically: any claim typed
  `traditional` but asserted above ~0.95 confidence is challenged for
  claiming empirical-grade certainty it isn't entitled to. This is
  deliberately narrow (three traditions, not a general theology KB) —
  matches the existing project principle of not building more than a task
  needs; expanding the table is cheap later if a real question needs a
  fourth tradition.

**Real interaction found while testing on LXC 104, not designed for in
advance:** adding Philosophy changed the committed-claim count on the
existing "how should we round 2.5?" test question from 2 to 3, because
that question contains "should" and now correctly routes to Philosophy,
which adds its own standalone is-ought claim alongside the pre-existing
Mathematics/Engineering jurisdictional-conflict pair. This is the system
behaving *more* correctly than before, not a regression — the design
always said a normative-phrased question should get Philosophy's framing
input — but it broke two tests that had hardcoded `committed == 2`
assuming only two agents would ever be routed to that specific fixture
question. Fixed by updating both tests' expectations rather than changing
Philosophy's behavior to avoid touching that fixture — the fixture's
phrasing was the accidental part, not Philosophy's response to it.

---

## 2026-09-22 — Output Types (Phase 7) design choices

**Q: How should Forecast probability avoid the category-error risk §5.4
explicitly names ("must never be presented with the same grammar" as
Research confidence)?**

Structurally, not just by convention: `build_forecast_answer()`'s return
dict has a `probability` field and deliberately has no `confidence` field
at all, so there's nothing for a caller to conflate by accident — the same
"close the risk by construction, not vigilance" approach §12.2 already
uses for content-integrity. Enforced with a test
(`test_forecast_probability_field_is_not_called_confidence`).

**Q: Does a Recommendation-classified question still get a Research
section, and does a pure Forecast question?**

Yes and no, respectively, and both follow directly from §5.4's own
example ("should we do X" implies *both* a Research Answer about the facts
and a Recommendation about the choice) rather than from an arbitrary
symmetry rule: `classify_output_type()` always includes Research alongside
Recommendation, but a pure Forecast (no recommendation cue) stands alone
— a probability estimate doesn't inherently imply a separate research
section the way a recommendation inherently implies a factual basis does.

**Q: What actually gets wired into the deliberation loop today, versus
just built as a standalone module?**

Only the Research Answer builder is wired into `loop.py`'s synthesis round
(round_index 3), because it's the only one buildable purely from what
today's toy agents actually produce. `build_forecast_answer()` and
`build_recommendation_answer()` are complete, tested, standalone functions
— per Phase 7's own task list this is legitimate (they're specified as
"synthesis paths," not required to have a producing agent yet) — but
nothing in the current agent set emits a claim with the resolution/
objective structure they need as input. Wiring them for real is deferred
to whichever future agent (or the eventual Forecast-capable model backend)
actually produces that structure, rather than building a fake one now
just to exercise the wiring.

**Not resolved, and not claimed to be:** Open Question 4 (confidence
aggregation across a plural or multi-type answer) is only partially
addressed — `compose_answer()` keeps sections non-collapsing per-type,
which sidesteps needing a single blended number, but there's still no
defined method for "overall confidence" when a reader wants one number
across a multi-type answer. Left open per the design doc's own framing,
not silently closed by this session's work.

---

## 2026-09-22 — Human Input Pipeline (Phase 13) design choices

**Q: §11.1 says justification is "required, not optional," but also says
unjustified assertions are "accepted... as low-weight testimony at most" —
which is it?**

Both, read as two different things: *presence* of the field is required
(passing `justification=None` is a hard `HumanInputError`), but the
*content* isn't policed beyond that — an empty or whitespace-only
justification is accepted, just capped at confidence ≤0.3 regardless of
what the submitter requested. This reading lets the design's own two
sentences both be true rather than picking one and quietly dropping the
other.

**Q: Is submitter track-record tracking (§11.3) a new mechanism, or does
the existing Reputability Engine actually already support it?**

Already supports it, without any change to `reputability_store.py`.
`ReputabilityStore.record_outcome(subject_id, subject_type, outcome)` was
already generic over `subject_type` (used for sources today) — Phase 13
task 36 turned out to be "call it with `subject_type='human_submitter'`,"
not "build a parallel tracking system." Worth flagging because it's the
kind of thing that's easy to over-build if you don't check what the store
already does first.

**Q: How is the §11.7 conflict-of-interest rule (a submitter can't clear
their own triggered checkpoint) enforced?**

As a hard error (`CheckpointConflictError`) inside `clear_checkpoint()`,
comparing `reviewer_id` against the `submitter_id` recorded on the
checkpoint at trigger time — not left as a caller-discipline convention,
since §11.7 calls this "a basic conflict-of-interest safeguard," which
reads as something the system should refuse to let happen, not just
discourage.

**Real limitation surfaced while testing, logged rather than hidden:**
cross-examination of a `human_input` claim only produces a genuine
challenge/corroboration when the claim's free-text statement happens to
match one of the existing toy agents' narrow regex patterns (e.g.
Mathematics' `"N is (not )?prime"` format). Anything else — which is most
realistic human input — currently survives cross-examination by omission,
not because it was evaluated. This is a real, not cosmetic, gap relative
to §11.2's "examined, never auto-accepted at full weight" — it's a
consequence of not having a real reasoning backend yet (same root
limitation as every toy agent), not something Phase 13's own code could
have closed. Verified with a test
(`test_human_input_claim_flows_through_cross_examination_and_synthesis`)
that documents the current behavior honestly rather than asserting it's
been "examined."

---

## 2026-09-22 — Engineering real loop + Model Fitness (Phase 15) design choices

**Q: What does "specify" actually mean for a deterministic toy agent with
no real model backend — how is a coding task specified without an LLM to
interpret a natural-language prompt?**

The specification format IS the code itself: `verify_code(task_id, code,
...)` takes a self-contained Python program that must print exactly
`PASS` and exit 0 to count as verified — anything else (wrong output,
non-zero exit, an exception, a timeout) is captured verbatim in
`defeat_condition` from the sandbox's real stdout/stderr/status. This is
honest about what a non-LLM Engineering agent can actually specify (a
mechanical pass/fail contract, not a natural-language task description)
rather than pretending to parse intent it doesn't have.

**Q: Open Question 10 (Model Fitness cold-start) asks for "a defined
default starting weight... too generous... too conservative" — what's the
actual resolution, and why is it defensible rather than arbitrary?**

Laplace (add-one) smoothing over the (corroborated, challenged) tally:
`(corroborated + 1) / (corroborated + challenged + 2)`. At zero evidence
this is exactly 0.5 — not a separately chosen constant, but a direct
consequence of the same formula that governs every later update, which
means there's no discontinuity between "cold-start default" and "normal
operation" the way a hardcoded 0.5-until-N-observations rule would have.
It also naturally damps early overreaction (one corroboration alone
yields ~0.67, not 1.0), which is the actual mechanism by which it avoids
both failure modes the open question names, not just a claim that it
does.

**Q: Why tie Engineering's `verify_code`/`verify_claim` tests to the real,
unmocked sandbox rather than stubbing `run_sandboxed`?**

Matches this project's own established principle (`CLAUDE.md` #1 --
"verify empirically, don't trust") and the exact precedent already set by
`test_sandbox.py`'s 8 fault-injection scenarios: a mocked sandbox would
prove the claim-construction logic is wired correctly, but wouldn't prove
the Engineering agent's central claim -- "confidence is tied directly to
an actual run" -- is actually true. Both a known-correct and a
known-buggy solution are run for real on LXC 104, which is exactly Phase
15 task 42's own stated requirement. A separate injectable-stub path
still exists (`sandbox_run` parameter) for callers that need to unit-test
the pass/fail decision logic in isolation, since spinning the real OS
sandbox for every edge case would be wasteful, not because the real path
is untrustworthy.

---

## 2026-09-22 — Content Integrity (Phase 14) design choices

**Q: §12.2 says the architecture "closes this by construction rather than
by vigilance" — how do you actually test a "by construction" claim, as
opposed to just testing behavior?**

With a structural scan, not a behavioral assertion: the test reads every
`.py` file in `src/athenaeum_brain/` and fails if `eval(` or `exec(`
appears anywhere. This is a different (stronger) claim than "I tried an
injection and it didn't work" — it proves the *mechanism* for claim text
to become code doesn't exist in this codebase at all, not just that this
session's specific attempts failed. Paired with an end-to-end test
(`test_adversarial_human_submission_is_inert_claim_data_end_to_end`) that
still exercises a real adversarial string through the real pipeline, since
a construction proof alone doesn't show the ordinary path still works
correctly on hostile input.

**Q: Open Question 8 asks how much weight the instruction-detection
heuristic should carry "versus being purely advisory" — what's the actual
number?**

Exactly the weight of one ordinary cross-examination challenge — a single
call to the same `ReputabilityStore.record_outcome(..., "challenged")`
any other challenge uses, no separate multiplier or override path. Chosen
because §12.3 itself calls the heuristic "necessarily imperfect," which
argues against giving it outsized leverage over a well-evidenced
cross-examination outcome; and because §12.3's own language — "a
*pattern* of instruction-like submissions is grounds for a low grade" —
describes accumulation, which the existing tally mechanism already does
correctly without needing a new weighting scheme invented for this case.

---

## 2026-09-22 — Evaluation Infrastructure (Phase 9b) design choices

**Q: §9.2 asks for adversarial coverage of "each failure mode in Section
8" — Section 8's table has 16 rows. Why does `ADVERSARIAL_CASES` only
cover 6?**

Because only 6 currently have a real, checkable mechanism behind them
without a model backend. Building a "check" for e.g. "silent style
drift" (Domain Fidelity Score) would either (a) require enough real
reasoning volume to see a fingerprint actually drift, which a
single-shot toy-agent call can't produce, or (b) be a hollow test that
technically imports `domain_fidelity.py` and asserts something trivial
just to claim coverage. Neither is honest. The six covered are named
explicitly in the module and in `progress.md` precisely so this reads as
"deliberately partial, here's exactly what's covered" rather than
implicitly claiming full §8 coverage.

**Q: The "remove reputability weighting" ablation came back identical to
A1 — is that a test bug?**

No — verified by reading `rounds.py`'s `synthesis_round` directly:
reputability grades are snapshotted onto the *answer* after commit
(`loop.py`'s `_attach_grades_and_record_outcomes`), and inform dispute
resolution, but nothing in `synthesis_round` itself reads a reputability
grade to change which claims survive or at what confidence. So "remove
reputability weighting" and "keep it" really do produce the same output
today, because the weighting this ablation is supposed to remove isn't
wired into synthesis yet. This is flagged as a real architectural gap
(§6.7 designs for it, the code doesn't implement it) rather than treated
as a test to fix — exactly the outcome §9.7's own text anticipates
("that is treated as a real finding... not a testing artifact to explain
away"). Worth revisiting when reputability-weighted synthesis is
actually built, not something to quietly patch over in this evaluation
module.

**Q: Why is contamination isolation (§9.9) a grep-based structural test
instead of an actual access-control layer (separate store, permissions,
etc.)?**

Because there's currently exactly one ingestion entry point
(`ingestion.py`'s `fetch()`), and it simply never imports
`evaluation.py` — there's nothing for an access-control layer to guard
against that doesn't already not exist. Building real access control here
now would be exactly the kind of speculative infrastructure this
project's own principles argue against (no future-proofing beyond what's
needed) — if a second ingestion path is ever added, this structural test
would need to grow to cover it too, and that's the natural trigger point,
not now.

---

## 2026-09-22 — Ingestion real fetch (opportunistic item) design choice

**Q: `FixtureSource` is now also the real fetch's return type — shouldn't
it be renamed to something like `FetchedSource`?**

Probably, in a codebase with more runway, but not done here: the class is
referenced in `ingestion.py` itself plus two existing test files, and a
rename would touch all of them for a naming-only change with zero
behavioral difference. Kept as-is and the reason documented in its own
docstring (it's now the shared shape both paths produce, not exclusively
a test fixture anymore) rather than silently leaving the now-slightly-
misleading name unexplained. If a third real caller of this shape shows
up later, that's the natural trigger to actually do the rename, not now.

**Q: Why does a genuinely failed page fetch (DNS error, timeout, HTTP
error) raise `FetchError` instead of being folded into the existing
`IngestionRejected`?**

Because they're different facts about the world: `IngestionRejected`
means "we successfully reached this source and its license/ToS/paid-
access properties disqualify it" — a policy decision. `FetchError` means
"we never even got content to evaluate" — a network fact. Conflating them
would hide, from any caller trying to distinguish "this source is
policy-ineligible" from "this source was temporarily unreachable, retry
later," exactly the information that distinction exists to preserve.

---

## 2026-09-22 — Distributed worker dispatch (Task 23) design choice

**Q: Task 23 was blocked on "needs a second process/host to be
meaningful" — why a second OS process on the same LXC rather than
actually standing up a second guest, now that the infra tier convention
makes that cheap?**

Because the thing Task 23 is actually testing — real network I/O between
a dispatcher and a worker, and real recovery when the worker disappears —
doesn't require a second physical host to be genuine; it requires the
worker to be a truly separate, independently-killable process that the
dispatcher can't reach into. `multiprocessing`'s fork context gives that
for real (its own PID, its own memory, killed with a real `terminate()`,
reached only over a real TCP socket) without the added cost, cleanup
burden, and resource-cap accounting of provisioning a new guest for one
test. If a *future* task specifically needs to test cross-host network
conditions (latency, partition, a host actually going offline), that's
the trigger to stand up a second guest — this one didn't need it to be
honest.

**Q: Why keep `distributed_worker.py` fully ignorant of
`athenaeum_brain`, when the only real work-unit type this project has is
a Brain deliberation?**

Because that's the same bet `loop.py` already made and it paid off:
`loop.py` adapts Brain rounds into the Body's `WorkUnit` contract, not the
reverse, which is what let the Brain backlog's later phases (output
types, human input, etc.) plug into the existing scheduler with zero Body
changes. Making `distributed_worker.py` generic over a
`round_handler_factory` extends that same seam to the network boundary
rather than opening a new, Brain-specific one — the worker test's own
wiring (`_run_worker_process` in the test file) is where the
Brain-specific `make_deliberation_handler` import actually lives, which
is exactly where it belongs.

---

## 2026-09-22 — World News agent + registry refactor design choices

**Q: "Adding new domains should not be difficult" — what did that
actually require changing, beyond just writing the new agent class?**

Only `rounds.py`'s `ALL_AGENTS = [MasterOfMathematics(), ...]` hardcoded
list was the actual friction point. Fixed by adding a `@master_agent`
decorator in `agents.py` that registers a class into a module list, and
having `rounds.py` build `ALL_AGENTS` from that registry instead. Checked
whether anything else needed touching for a new agent to work correctly
(routing, cross-examination, Domain Fidelity Monitoring, evaluation's
adversarial suite) — `domain_fidelity.py`'s `FINGERPRINT_CHECKS` was the
only other per-agent lookup, and it already degrades gracefully (returns
neutral 0.0) for an agent with no entry, so it didn't need a hard
"every agent must have one" rule to stay correct. `evaluation.py`'s
`ADVERSARIAL_CASES` was deliberately left as an explicit, named subset
(see the 2026-09-22 Evaluation Infrastructure entry above) rather than
something a new agent is required to extend.

**Q: Why a real dated-event lookup instead of something more
general-purpose for "timelines"?**

Because the project's own established discipline (stated in `agents.py`'s
own module docstring since session 1) is that every toy agent's claims
are backed by real, verifiable computation in a narrow domain, not
hand-waved text — a general "reason about any historical event" capability
would require exactly the LLM backend that doesn't exist yet. What a
toy agent CAN do honestly is check a mechanical, narrow property —
temporal precedence — against a small set of dates it actually has, and
correctly abstain (not guess) outside that set. `build_timeline()` is the
direct, literal answer to "we are going to create timelines": it's a real
utility, usable today, not a placeholder waiting on a future backend.

**Q: World War I / World War II — how was that bug actually found, not
just fixed?**

By writing a test for the exact scenario before trusting the substring
check (`_find_events`) was correct: a question naming only "World War
II" should find only WWII. Running it against the naive `event in q`
implementation failed immediately, which is what surfaced the substring
containment (`'world war i' in 'world war ii'` is literally `True` in
Python) rather than it being caught by inspection. Fixed with `\b`-bounded
regex matching, then the same test made green — matching this project's
own "verify empirically" principle applied at the smallest possible
scale, not just at the infrastructure level.

---

## 2026-09-23 — Model-lab manifest verified against live Hugging Face listings

Per explicit request to verify rather than trust the manifest as first written. Queried `huggingface.co/api/models/<repo>` for real for all six candidates (file listing + license tag), not re-derived from memory. Two real corrections came out of it:

1. **Qwen2.5-3B-Instruct is not apache-2.0.** It's under the "Qwen Research License" (`license_name: qwen-research`, non-commercial) -- confirmed via the model's own `cardData`. This directly fails the "legally fully modifiable" criterion the whole model-lab exercise exists to satisfy, so it would have been a real, consequential mistake to leave it in unverified. Every other Qwen2.5 size checked (0.5B/1.5B/7B) is genuinely apache-2.0, so this isn't "Qwen is restrictive," it's "license can vary *by size within one family*" -- worth remembering as a general lesson, not just fixed for this one model. Swapped to Qwen2.5-1.5B-Instruct.
2. **Two smaller misses**, also only caught by querying the real API: `ibm-granite/granite-3.1-2b-instruct-GGUF` returned 401 (gated/auth-required), so switched to `bartowski/granite-3.1-2b-instruct-GGUF` (public, verified apache-2.0); OLMo's actual GGUF filename is `OLMo-2-0425-1B-Instruct-Q4_K_M.gguf`, not the lowercase `olmo-2-...` guessed originally.

Nothing else in the original manifest needed changing -- Qwen2.5-Coder-1.5B, Phi-3.5-mini, and Mistral-7B-v0.3's repos/filenames/licenses were all correct as first written. Updated `manifest.tsv` and `model-lab/README.md` directly with the verified values, rather than leaving the correction only in this log.

---

## 2026-09-23 — Model-lab creation: three real bugs, and the real LLM backend milestone

**Three real bugs hit while actually creating the six guests, none of them known in advance:**
1. `pve_wait_task` treated Proxmox's routine "WARNINGS: 1" (a benign systemd-nesting notice every `debian-12-standard` LXC create prints) as a hard failure, aborting the creation script right after the guest was already successfully created. Fixed in `lib/common.sh` to accept `OK` or `WARNINGS:*`.
2. Manifest hostnames used underscores (`qwen2-5-1_5b`) to represent version numbers -- the Proxmox API correctly rejected these as invalid DNS names. Fixed to hyphens.
3. `huggingface-cli` is not just deprecated, it's been removed outright in the `huggingface_hub` version that installs today -- every one of the six guests' first setup attempt failed on it. Replaced with the current `hf download` command.

None of these three were guessable from documentation or training knowledge alone -- all three were only found by actually running the scripts against the real host, which is exactly why they're worth recording here rather than just silently fixed.

**Q: Once the six were live, what's the highest-value thing to build with them, given the standing instruction to keep going and "surprise" with something real?**

Wiring a real `Backend` into `model_serving.py` -- this closes the single most-repeated "not yet built" line in `progress.md`/`CLAUDE.md` across the entire session (Local Model Serving Layer, MockBackend-only), and it directly unblocks something evaluation.py had explicitly marked impossible: the B1 baseline (`B1_UNAVAILABLE`, "requires a real generalist reasoning backend"). Chose this over wiring a specific Master Agent to use it for its own claims, because the backend is the shared foundation every agent would need regardless of which one goes first -- doing the foundation once, generically, is worth more than doing one agent's wiring first and redoing the same backend work for each subsequent agent. Building foundation-then-consumer in that order matches how `loop.py` and `distributed_worker.py` were both built earlier this session (generic contract first, one concrete user of it after).

**Q: `n_predict=256` timed out on the 2-vCPU Phi-3.5-mini box at 60s -- was the fix to raise the timeout?**

No -- lowering `n_predict` to 64 by default. Raising the timeout treats a real, informative capacity number (these boxes are genuinely slow at longer generations under CPU inference on 2 vCPU) as if it were just an arbitrary threshold to relax. 64 tokens is fast and sufficient for comparison/sanity use, which is what these guests exist for right now; both `n_predict` and `timeout_seconds` are still there for a caller doing longer real reasoning to raise deliberately, together, rather than the default silently assuming everyone wants long generations.

---

## 2026-09-23 — OLMo 2 as the shared Master Agent fallback: design choices

**Q: You presented three options (shared backend, new eighth agent, one
pilot agent) and I picked shared backend — what did that actually
constrain in the implementation?**

Two things, both load-bearing: (1) the fallback had to be generic across
agent types, not hand-tuned per agent's own reasoning style, since the
same mechanism serves all six eligible agents — that's why
`model_backed_reasoning.py` is one small, agent-agnostic module rather
than six bespoke integrations; (2) it had to respect each agent's
*existing* claim-typing discipline rather than impose a uniform one —
Philosophy's fallback is `normative` specifically because `empirical`
would be the exact category error Philosophy's own cross-examination
polices in *other* agents (§2.2's category-conflation rule would be
violated by Philosophy's own claim if this weren't caught). Getting this
wrong would have meant the agent violating, in its own fallback claims,
the exact discipline it enforces on everyone else.

**Q: Why does the fallback check `self.in_jurisdiction(question)` again,
when `explore()` is only ever called by `rounds.py` for agents already
confirmed routed?**

Because `explore()` is also called directly in many existing tests,
bypassing routing entirely (`ph.explore("is 17 prime?", "q1")` to check
Philosophy correctly does nothing for an unrelated question). Without the
guard, that direct call would have triggered a real network call to OLMo
2 and very likely produced SOME response, breaking the `== []`
assertions those tests already depended on — not because the tests were
wrong, but because "silently abstain outside real jurisdiction" is a real
design discipline (`agents.py`'s own module docstring), and `explore()`
should honor it regardless of who's calling it, not just when routing
happens to have already filtered the caller.

**Q: Two real reliability issues surfaced only under the full test
suite's back-to-back load, not in isolation — timeout and occasional
near-empty completions. Why fix both centrally in `ask_model()` rather
than in each agent or each test?**

Because both are backend-level characteristics, true regardless of which
agent or caller hits them: the six model-lab guests queue concurrent
requests rather than reject them (so a tight timeout will eventually trip
under load no matter who's asking), and OLMo 2's own sampling
occasionally produces near-empty output for an ordinary prompt (true of
the model, not of any particular caller's prompt). Patching one test that
happened to hit it first would have left the same characteristic latent
for the next agent, the next test, or real production use — fixing it
once in the shared helper is the same "generic contract, not one caller's
workaround" choice already made for `distributed_worker.py` and
`loop.py` earlier in this session.

---

## 2026-09-23 — OLMo 2 → OLMo 3 swap, resource cap raise: design choices

**Q: The four smallest guests were resized 2→1 vCPU to fit the old 50%
cap, then back to 2 once the cap was raised — was shrinking them the
right call in the first place, given it caused real test timeouts?**

Yes, at the time it was made: the cap was still 50% when olmo3-7b and
olmo3-32b needed room, and the alternative was exceeding a hard
constraint, which isn't a tradeoff — it's not allowed regardless of
convenience. The resize was reversible, transparent (reported plainly,
not buried), and the timeouts it caused were a real, honest cost that got
fixed the moment the actual constraint changed (the cap raise), not
something quietly tolerated. Worth remembering: a resource-constrained
decision made correctly under yesterday's constraint can still need
revisiting the moment the constraint itself changes — that's not the
original decision being wrong, it's the ground shifting under it.

**Q: Three real bugs surfaced getting OLMo 3 working (chat-template
crash, retry-on-timeout not actually retrying, bare-question empty
completions) — why keep pushing through all three instead of reverting
to OLMo 2 once the first one or two appeared?**

Because none of them were reasons to doubt OLMo 3 itself — each was
either a llama.cpp/model interaction issue with a clean root-cause fix
(`--no-jinja`), a bug in code this session already wrote (the retry
logic), or a real, fixable prompt-format mismatch (Q:/A: framing). None
pointed at OLMo 3 being a worse choice than OLMo 2 — they pointed at gaps
in the *scaffolding* around it, the same category of thing already hit
and fixed for OLMo 2's own deployment (`huggingface-cli` deprecation,
the LXC-create warning bug). Reverting because scaffolding needed fixing
would have thrown out a strictly newer, more capable, still-Apache-2.0
model for reasons that had nothing to do with the model.

**Q: The retry-loop bug (timeout not retried) and the framing bug
(empty completion on bare questions) look similar on the surface — why
were they diagnosed as two separate things instead of one?**

Because they produced genuinely different evidence once actually
checked, not assumed: re-running the *exact* failing prompt directly
against the guest (`curl` in a loop, 4 times) showed **100% reproducible
empty output**, not intermittent failure — which ruled out "just a slow
timeout that needs retrying" as the explanation, since a timeout-retry
fix wouldn't touch a deterministic empty response. That single piece of
direct evidence is what redirected the investigation from "retry harder"
to "the prompt format itself doesn't work for this model" — worth
remembering as a general debugging move: when a fix doesn't fully resolve
a symptom, re-verify what's actually happening before assuming the first
fix just needs to be bigger.

---

---

## 2026-09-23 — Elastic GPU worker pool design choices

**Q: "I don't want to make this Windows machine a permanent dependency,
nor any specific machine... I want the scalability to be fully elastic" —
what did that actually constrain in the implementation, beyond "add a GPU
backend"?**

Three concrete things, all load-bearing: (1) health has to be checked
live on every call, never cached at process-start or on a fixed interval
— a stale "worker is up" flag is exactly the kind of state that would
make a machine going offline mid-session an actual crash risk rather than
a graceful fallback; (2) the failure path has to be the same
`BackendUnavailable` exception every other stateless-lease-holder
component in this codebase already uses (`LlamaCppBackend`,
`distributed_worker.py`), not a new error type, so `ModelServingLayer`
and `ask_model()` could catch it with the same discipline they already
had, rather than needing bespoke handling for "GPU worker specifically";
(3) the worker manifest (`elastic_workers.yaml`) has to support more than
one entry per model and more than one machine shape from day one, even
though only one worker exists right now, because "multiple such machines
with various configurations" was named explicitly as expected, not
speculative.

**Q: Why a hand-edited YAML manifest instead of push-based
self-registration (the worker calls home when it starts)?**

Because self-registration solves a problem this project doesn't have yet
— discovering workers nobody told the system about — at the cost of a
new network-facing write path (something has to authenticate an
unsolicited "I exist" message) that a hand-edited file entirely avoids.
One human-owned line in `elastic_workers.yaml` is simpler, more legible,
and matches this project's own "don't build speculative infrastructure"
principle (already applied to auto-scaling policy in
`docs/infra-topology.md` §5). If a fleet of many transient workers ever
makes hand-editing genuinely painful, that's the trigger to build
registration — not before.

**Q: The three broken unit tests (GPU worker answering for real instead
of hitting the intended CPU-path mock) — was this a bug in
`elastic_workers.py` itself?**

No, and worth stating precisely why not: the module did exactly what it's
designed to do — checked a real, currently-online worker, got a real
answer, used it. The bug was in test isolation, not in production logic:
three tests that intended to exercise `ask_model()`'s CPU-only retry
behavior only ever monkeypatched `LlamaCppBackend`, silently assuming no
GPU backend would answer first. That assumption held by accident for as
long as no real worker existed; the moment one did (this session,
deliberately), the assumption broke. Fixed by making the GPU path's
unavailability explicit and deterministic in those three tests
(`_stub_gpu_unavailable`), rather than by weakening `ask_model()`'s real
GPU-first preference to make the tests pass more easily — the tests were
wrong about what they were isolating, not the code.

---

## 2026-09-25 — Evidence-weighted synthesis (§4.1): design choices

**Q: Why add `weighted_confidence` alongside `confidence` instead of
rescaling `confidence` in place?**

§5.1 requires every confidence to be traceable to something. The agent's
own number is traceable to its own computation; the weighted number is
traceable to that plus the grades at time of use. Overwriting one with
the other would erase the first trace. Keeping both also means every
existing test and consumer that reads `confidence` sees exactly what it
saw before.

**Q: Why weakest link (min) across provenance rather than an average?**

Every provenance list the agents emit today is conjunctive — World News's
causal-precedence claim cites two dated events and is wrong if *either*
date is wrong. Averaging would let one good source dilute a rejected one.
If a future agent cites genuinely independent, disjunctive support, that
agent's claims will need a different combination rule — this one is
right for what exists, not a universal answer.

**Q: Does weighting decide what gets committed?**

No, deliberately. Commit/dissent is still decided purely by surviving
cross-examination (§4.4). Weighting only orders committed claims, which
is what the Research Answer's leading conclusion is chosen from. A claim
resting on a rejected source is still committed, just never leading —
removing it would be a second, unreviewed gate.

**Q: What else changed as a consequence?**

`build_research_answer` previously produced a `leading_conclusion` only
when exactly one claim was committed — with two compatible claims there
was no leading conclusion at all, which §4.1 doesn't allow. It now picks
the highest-weighted one and keeps the rest as `supporting_conclusions`.
Plural (§4.2) answers still have no leading conclusion.

The "no reputability weighting" ablation (§9.7), previously recorded as
indistinguishable from A1 (`ABLATION_NO_REPUTABILITY_WEIGHTING_FINDING`),
is now a real function, `ablation_no_reputability_weighting()`, and a
test proves it differs: with `computed:trial_division`'s track record
rejected, A1 leads "should we believe 17 is prime?" with Philosophy's
claim while the ablation still leads with Mathematics on raw confidence.

**Not done here:** Model Fitness (`apply_fitness_to_confidence`) is still
not applied at synthesis — it's a separate §6.7 weight, tracked with the
model admission gate item in `docs/progress.md` §26. `GRADE_WEIGHT`'s
numbers are an explicit placeholder, same status as the grading policy.

---

## 2026-09-25 — Dispute resolution (§6.4): design choices

**Q: What exactly counts as "not independent"?**

Two sources are one line of evidence if either reaches the other through
citations, or both reach a common upstream source. The common-upstream
rule matters most in practice: two news reports rewritten from the same
wire story don't cite each other, but they aren't independent either —
and the wire story itself often isn't on the claim's provenance list at
all, so the check follows citations beyond the listed sources. Grouping
is transitive (union-find), so A–B and B–C dependencies put A and C in
the same group even though they share nothing directly.

**Q: Where does citation data come from?**

The curator, same as `license`. Nothing in raw content mechanically
tells you what a source derived from, and pretending otherwise (e.g.
scraping hyperlinks) would confuse "links to" with "derives from." It's
an optional field on `FixtureSource`, stored in provenance metadata only
when present.

**Q: Why does the ruling compare counts of independent lines rather than
weigh grades more finely?**

§6.4 names two things Logic compares — track records and independence —
and Logic must not adjudicate domain substance (§4.2.3). Counting
independent, non-rejected lines of evidence is purely procedural; it
doesn't require Logic to judge whether a claim is *true*. A tie is
"unresolved" rather than broken by any secondary rule, for the same
reason synthesis doesn't pick winners in jurisdictional conflicts (§4.3).

**Q: Why doesn't a ruling downgrade the losing side's sources?**

§6.4.4: no single Master Agent has unilateral blacklist/whitelist
authority. A ruling is a logged, reversible judgment; grades move only
through accumulated outcomes (§6.2). A future step could record the
ruling as an ordinary outcome, but that's a policy decision, not
something to slip in here.

**One real test bug worth remembering:** the first version of the
Theology category-error test issued the overconfident `traditional`
claim *from Theology itself* and expected Theology to flag it. It
didn't, correctly — every agent's `cross_examine` skips its own claims.
The realistic case, and the fixed test, is a traditional-typed claim
arriving from another agent.

**Not done here:** conflict-of-interest checking for *sources* (§6.4.3
names it). No conflict-of-interest data exists for sources today; human
submitters already have role-based COI enforcement (§11.7). Disputes are
also not yet triggered automatically — `resolve_dispute` is called
explicitly, and an idle-evolution round (§3.6, still open) is the natural
caller.

---

## 2026-09-26 — Reputability standard versioning (§6.5): design choices

**Q: What is a "version of the standard", concretely?**

A named set of parameters for the grading rule plus a written rationale.
The rule's shape (rejected / contested / foundational / provisional)
stays fixed; its thresholds are what an amendment changes. That's the
smallest real thing §6.5 describes — "has a criterion produced a pattern
of disputes that suggests it's miscalibrated?" is a question about
thresholds — without inventing a pluggable-policy framework nobody needs
yet. Version 0 uses exactly the old hardcoded thresholds, so all prior
grades are genuinely v0 decisions, not relabelled ones.

**Q: When a standard changes, why regrade immediately instead of
waiting for each source's next outcome?**

Waiting would leave `current_grade()` reporting grades the standard in
force no longer supports, possibly indefinitely for a source that's
rarely cited. Regrading on adoption keeps "current grade" meaningful. It
stays non-retroactive because the regrade is a *new appended decision*
(`cause: "standard_amendment"`), never an edit — the history shows both
what was decided under v0 and what v1 changed.

**Q: Why does materiality need `grade_under()` rather than just comparing
standard version numbers?**

A version bump alone doesn't mean a cited source was affected, and a
grade change after an amendment might still be evidence-driven. §7.2's
wording is "changed version *in a way that would alter the grade*." The
precise test is counterfactual: apply the old standard to today's
evidence. If that still yields today's grade, the standard didn't cause
the change and the ordinary evidence threshold applies; if it doesn't,
the amendment did, and that's material at any size. Tested both ways,
including a one-band move that is material when standard-driven and
immaterial when evidence-driven at the same threshold.

**Q: Why make `current_grade()` return a projection instead of the raw
entry?**

It used to return the stored entry itself. With `decided_under`/`cause`
on entries, callers would have received storage details they never
asked for, and the snapshot attached to answers would have recorded the
standard a grade was *first* decided under rather than the one *in force*
at time of use — the wrong thing for materiality. The projection adds
exactly one field, `standard_version`.

**Not done here:** nothing proposes amendments yet; that belongs to the
idle-evolution review (§3.6), next-session plan item 4.

---

## 2026-09-26 — Forecast and Recommendation producers (§5.4, Phase A): design choices

**Q: Why is Physics the forecast producer, and why is it a genuine
forecast rather than a research claim in disguise?**

A dropped object's fall time is one of the few questions the toy agents
can forecast without guessing: kinematics gives the vacuum fall time
exactly, and the one ignored effect — air resistance — has a known
*direction* (it can only lengthen the fall). So the forecast states a
resolvable event (measured time vs. a stated bound), a probability, and
a computed sensitivity naming exactly how much drag would flip it. That
meets every field `build_forecast_answer` requires without inventing any.
The probability bands are a placeholder; their ordering is physics.

**Q: Why keep the probability out of `confidence`?**

§5.4's named category error is conflating forecast probability with
research confidence. The forecast claim's `confidence` (0.95) is
Physics's confidence that its computation is right; the event
probability (0.02 for a 45 m drop within 3 s) is a different quantity
and lives only in the `forecast` payload. Tested directly.

**Q: Why does the rounding Recommendation choose nothing?**

The two options serve different objectives — matching the schoolbook
convention vs. avoiding systematic bias when summing. Which matters more
is a value judgment that belongs to whoever is deciding, not to any
agent; picking one would manufacture a winner exactly as §4.3 forbids
for plural answers. The section still does the useful work: it names
both options, the objective each serves, their reversibility, and the
trigger for revisiting. With one shared objective, every option it
covers is chosen, since those are the same policy applied to different
values rather than competing alternatives.

**Q: Why emit an explicit "unavailable" section instead of omitting it?**

Before this change a forecast question produced an answer with *no*
forecast section and no explanation — indistinguishable from a bug.
§5.4 classifies the question as asking for a forecast; the honest answer
when no agent can produce one is to say so, with the reason.

**Real bug on the way in (known-bugs.md #21):** designing the time-bound
parser exposed that Physics read every bare number as a height, so "did
the berlin wall fall in 1989?" committed a 1989 m free-fall claim.
Fixed by requiring a length unit or a "from N" role; three related
weaknesses are logged as open limitations rather than fixed in passing.

---

## 2026-09-26 — Importance and reopening (§7.1, §7.3, Phase B): design choices

**Q: Why is importance computed from the frame rather than asked for?**

§7.1 says importance is "a computed/estimated value, not purely
user-declared", and that the framing round contributes by identifying
how many domains a question implicates. The rating therefore combines
breadth, output-type count, dependents and an optional requester
priority, and returns its components so a reader can see why a question
rated as it did. Logic is excluded from breadth because it chairs every
deliberation it is routed to.

**Q: What counts as a "dependent" when there's no Belief Graph?**

Another question whose latest answer commits one of the same claims. If
that claim is later contested, both answers are implicated, which is the
property §7.1 cares about. It is labelled as a proxy until real
dependency edges exist.

**Q: Why does a reopen re-run everything instead of patching the old
answer?**

§7.3: agents are expected to re-derive, not rubber-stamp. The prior
answer is attached as context and the diff is computed afterwards by
comparing the two, so nothing in the new answer is copied from the old
one. The prior version stays byte-identical in the ledger.

**Q: Why can a resolved forecast skip the importance threshold?**

§5.4 and §7.2 both say a forecast's resolution is always material,
unconditionally — forecast accuracy is only knowable in hindsight, so
it has to be checked every time. The outcome is a parameter, never
looked up, so the system can't have seen it early (§9.9).

**Real bug on the way (known-bugs.md #22):** the first dependency test
expected zero shared claims between two unrelated normative questions
and got one — Philosophy's "this question asks for a normative
conclusion…" statement was word-for-word identical across questions.
Fixed at the source by making the statement name its question, since
consolidation compares claims across questions the same way.

---

*See `docs/progress.md` §26 for the checklist this log's entries track
against, and `docs/infra-topology.md` for the infrastructure-side design
decisions made in the same planning conversation.*
