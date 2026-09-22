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

*See `docs/progress.md` §26 for the checklist this log's entries track
against, and `docs/infra-topology.md` for the infrastructure-side design
decisions made in the same planning conversation.*
