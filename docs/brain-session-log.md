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

*See `docs/progress.md` §26 for the checklist this log's entries track
against, and `docs/infra-topology.md` for the infrastructure-side design
decisions made in the same planning conversation.*
