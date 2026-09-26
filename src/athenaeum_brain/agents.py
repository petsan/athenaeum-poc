"""
Master Agents (Section 2): narrow, real deterministic computation first,
a real model-backed fallback second (added 2026-09-23, model_backed_
reasoning.py -- OLMo 3 7B Instruct via the model-lab guests, infra/proxmox/model-lab/).

Every agent below tries its own hand-checkable computation FIRST (real
primality, kinematics, sandboxed execution, dated-event chronology --
this proves the deliberation *mechanics*, claim structure/jurisdiction/
cross-examination/commit-boundary, independent of any model's reasoning
quality). Only when that finds nothing relevant for a question the agent
IS routed to does it fall back to a real model call -- never a guess
dressed up as certainty: fallback claims carry deliberately capped
confidence (model_backed_reasoning.FALLBACK_CONFIDENCE) rather than the
1.0 reserved for mechanically-verified claims. Logic is the one
deliberate exception: Section 2.2 requires it never assert first-order
claims, so it has no fallback path at all, by construction.

Registration (added 2026-09-22, alongside the World News agent): every
Master Agent class below is decorated with @master_agent, which appends
it to a module-level registry. rounds.py builds ALL_AGENTS from that
registry (`all_agents()`) instead of hardcoding a class list -- adding a
new domain is: write the class here, decorate it, done. No other file
needs to change for the agent to be routed, cross-examined, and included
in Domain Fidelity Monitoring's per-agent scan (domain_fidelity.py's
FINGERPRINT_CHECKS is a separate, OPTIONAL per-agent lookup -- an
unregistered fingerprint check just means fingerprint_deviation() returns
0.0 for that agent, not an error, so a new agent works correctly even
before anyone gets around to adding one)."""
from __future__ import annotations
import re
from .claims import Claim, is_vacuous_defeat
from .model_backed_reasoning import model_backed_claim

_REGISTRY: list[type] = []


def master_agent(cls):
    """Class decorator: registers a Master Agent so it's automatically
    included in rounds.all_agents() -- see module docstring above."""
    _REGISTRY.append(cls)
    return cls


def _strip_leading_article(s: str) -> str:
    """Free-text causal statements naturally include 'the' ('the fall of
    the berlin wall'), but the _EVENTS registry keys don't -- stripped
    here rather than adding 'the'-prefixed duplicate keys to the
    registry, which would just be the same data twice."""
    return s[4:] if s.startswith("the ") else s


_INFLECTIONS = r"(?:s|es|ed|d|ing)?"


def mentions(text: str, keywords) -> bool:
    """Whole-word keyword matching with common inflections ('primes',
    'rounded', 'forces', 'causes'). Replaces plain substring tests, which
    routed Logic on 'b-all', Mathematics on 'a-round' and 'sev-en', World
    News on 'be-cause' and 'to-war-d', Engineering on 'la-test', and fired
    Philosophy's category-error check on 'must-ard' (known-bugs.md #28).
    Multi-word keywords ('lead to') match as whole phrases."""
    q = text.lower()
    return any(re.search(rf"\b{re.escape(k)}{_INFLECTIONS}\b", q) for k in keywords)


def all_agents() -> list:
    """Fresh instances of every registered Master Agent, in registration
    (i.e. declaration) order -- deterministic, so routing/framing output
    doesn't depend on dict/set ordering."""
    return [cls() for cls in _REGISTRY]


def _is_prime(n: int) -> bool:
    if n < 2:
        return False
    for d in range(2, int(n ** 0.5) + 1):
        if n % d == 0:
            return False
    return True


@master_agent
class MasterOfMathematics:
    """Domain: formal/quantitative claims. Reasoning mode: definition ->
    derivation -> proof (Section 2.2). Here: real primality checks."""
    name = "Mathematics"
    domain_keywords = ("prime", "number", "divisible", "sum", "even", "odd", "round")

    def in_jurisdiction(self, question: str) -> bool:
        return mentions(question, self.domain_keywords)

    def explore(self, question: str, question_id: str) -> list[Claim]:
        claims = self._explore_deterministic(question, question_id)
        if not claims and self.in_jurisdiction(question):
            fallback = model_backed_claim(agent_name=self.name, question=question,
                                           question_id=question_id, claim_type="formal")
            if fallback:
                claims = [fallback]
        return claims

    # A whole number that isn't part of a decimal and doesn't carry a unit:
    # "17" yes; "4.9m", "1 second", "20 kg" no (known-bugs.md #25).
    _BARE_INTEGER = re.compile(
        r"(?<![\d.])(\d+)(?![\d.])"
        r"(?!\s*(?:m|meters?|metres?|km|cm|mm|s|secs?|seconds?|min|minutes?|hours?|days?|years?|kg|g|%)\b)")

    def _explore_deterministic(self, question: str, question_id: str) -> list[Claim]:
        claims = []
        # Primality is the one property computed here, so it is only claimed
        # when the question asks about primality -- "is 4 even?" used to get
        # the irrelevant claim "4 is not prime".
        candidates = self._BARE_INTEGER.findall(question.lower()) if mentions(question, ("prime",)) else []
        for token in dict.fromkeys(candidates):
            n = int(token)
            prime = _is_prime(n)
            claims.append(Claim(
                question_id=question_id, round=1, issuing_agent=self.name,
                statement=f"{n} is {'prime' if prime else 'not prime'}",
                claim_type="formal", confidence=1.0 if n > 1 else 0.99,
                defeat_condition=f"a divisor of {n} other than 1 and itself is exhibited",
                jurisdiction_check=True,
                supporting_provenance=["computed:trial_division"],
            ))
        if mentions(question, ("round",)):
            for token in question.replace("?", "").split():
                try:
                    from decimal import Decimal, ROUND_HALF_UP
                    val = Decimal(token)
                except Exception:
                    continue
                rounded = val.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                claims.append(Claim(
                    question_id=question_id, round=1, issuing_agent=self.name,
                    subject=token,
                    statement=f"{token} rounds to {rounded} (classical round-half-up convention)",
                    claim_type="formal", confidence=1.0,
                    defeat_condition="a different result under the round-half-up rule",
                    jurisdiction_check=True,
                    supporting_provenance=["computed:decimal.ROUND_HALF_UP"],
                    recommendation_option={
                        "option": f"round half up ({token} -> {rounded})",
                        "serves_objective": "matching the classical schoolbook convention most readers expect",
                        "reversibility": "fully reversible while the unrounded values are kept",
                    },
                ))
        return claims

    def cross_examine(self, claim: Claim, question_id: str) -> Claim | None:
        """Independently re-derive another agent's numeric claim; challenge
        if the computation disagrees (Section 3.3)."""
        if claim.issuing_agent == self.name or claim.claim_type != "formal":
            return None
        import re
        m = re.match(r"(\d+) is (not )?prime", claim.statement)
        if not m:
            return None
        n, negated = int(m.group(1)), bool(m.group(2))
        actual = _is_prime(n)
        agrees = (actual and not negated) or (not actual and negated)
        return Claim(
            question_id=question_id, round=2, issuing_agent=self.name,
            statement=f"independent re-derivation of '{claim.statement}': {'confirmed' if agrees else 'contradicted'}",
            claim_type="formal", confidence=1.0,
            defeat_condition="a different trial-division result",
            jurisdiction_check=True,
            relation="corroborates" if agrees else "challenges",
            target_claim_id=claim.claim_id,
            supporting_provenance=["computed:trial_division"],
        )


@master_agent
class MasterOfLogic:
    """Domain: validity of argument form, never first-order domain content
    (Section 2.2). Chairs synthesis/dispute resolution (Section 4)."""
    name = "Logic"
    domain_keywords = ("all", "every", "therefore", "if", "then", "valid", "validity")

    def in_jurisdiction(self, question: str) -> bool:
        return mentions(question, self.domain_keywords)

    def explore(self, question: str, question_id: str) -> list[Claim]:
        # Logic doesn't assert first-order claims (Section 2.2) -- it only
        # ever produces procedural claims, checked in tests (Section 8 table).
        return []

    def cross_examine(self, claim: Claim, question_id: str) -> Claim | None:
        """Checks only argument FORM, never domain substance (Section 4.2.3)."""
        if claim.issuing_agent == self.name:
            return None
        if not claim.jurisdiction_check:
            return Claim(
                question_id=question_id, round=2, issuing_agent=self.name,
                statement=f"claim '{claim.statement}' asserted outside {claim.issuing_agent}'s declared jurisdiction",
                claim_type="procedural", confidence=1.0,
                defeat_condition="issuing agent's domain scope is redefined to include this",
                jurisdiction_check=True, relation="challenges",
                target_claim_id=claim.claim_id,
            )
        if claim.argument:
            from .logic_engine import check_validity
            result = check_validity(claim.argument["premises"], claim.argument["conclusion"])
            explanation = result["explanation"]
            if not result["valid"]:
                return Claim(
                    question_id=question_id, round=2, issuing_agent=self.name,
                    statement=f"argument for '{claim.statement}' is INVALID: {explanation}",
                    claim_type="procedural", confidence=1.0,
                    defeat_condition="a proof that no counterexample assignment exists",
                    jurisdiction_check=True, relation="challenges",
                    target_claim_id=claim.claim_id,
                )
            return Claim(
                question_id=question_id, round=2, issuing_agent=self.name,
                statement=f"argument for '{claim.statement}' is valid: {explanation}",
                claim_type="procedural", confidence=1.0,
                defeat_condition="a counterexample assignment is exhibited",
                jurisdiction_check=True, relation="corroborates",
                target_claim_id=claim.claim_id,
            )
        return None


@master_agent
class MasterOfEngineering:
    """Domain: specification/implementation/verification via execution
    (Section 2.2, the sixth Master Agent). Here: real Decimal computation
    under the IEEE-754-style round-half-to-even convention -- a genuinely
    different, equally defensible answer from Mathematics's classical
    round-half-up convention, used to exercise Section 4.2's jurisdictional
    conflict path."""
    name = "Engineering"
    domain_keywords = ("round", "implement", "implementation", "execute", "execution", "verify", "verified", "verification", "test")

    def in_jurisdiction(self, question: str) -> bool:
        return mentions(question, self.domain_keywords)

    def explore(self, question: str, question_id: str) -> list[Claim]:
        claims = self._explore_deterministic(question, question_id)
        if not claims and self.in_jurisdiction(question):
            # Section 2.2: "a design/architecture claim requiring
            # qualitative review, not asserted with the same confidence
            # grammar as a verified implementation" -- this IS that case,
            # so claim_type stays 'empirical', never 'executable' (that
            # type is reserved for verify_code()'s actual sandbox runs).
            fallback = model_backed_claim(agent_name=self.name, question=question,
                                           question_id=question_id, claim_type="empirical")
            if fallback:
                claims = [fallback]
        return claims

    def _explore_deterministic(self, question: str, question_id: str) -> list[Claim]:
        if not mentions(question, ("round",)):
            return []
        claims = []
        from decimal import Decimal, ROUND_HALF_EVEN
        for token in question.replace("?", "").split():
            try:
                val = Decimal(token)
            except Exception:
                continue
            rounded = val.quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)
            claims.append(Claim(
                question_id=question_id, round=1, issuing_agent=self.name,
                subject=token,
                statement=f"{token} rounds to {rounded} (IEEE-754 round-half-to-even convention)",
                claim_type="executable", confidence=1.0,
                defeat_condition="a different result under decimal.ROUND_HALF_EVEN",
                jurisdiction_check=True,
                supporting_provenance=["computed:decimal.ROUND_HALF_EVEN"],
                recommendation_option={
                    "option": f"round half to even ({token} -> {rounded})",
                    "serves_objective": "avoiding systematic upward bias when many rounded values are summed (the IEEE-754 default)",
                    "reversibility": "fully reversible while the unrounded values are kept",
                },
            ))
        return claims

    def cross_examine(self, claim: Claim, question_id: str) -> Claim | None:
        return None

    def verify_code(self, task_id: str, code: str, *, question_id: str, sandbox_run=None,
                     serving_model: str = "deterministic:sandbox_execution") -> Claim:
        """The real specify->implement->execute->verify loop (Section 2.2,
        Phase 15 tasks 42-43): `code` is a self-contained Python program
        that prints exactly 'PASS' and exits 0 on success -- that IS the
        specification format here, mirroring the design's own claim that a
        failing test/counterexample/build error is a direct, mechanical
        defeat condition, not an inferred one. Actually runs inside the
        Body's sandbox (body-design.md Section 4.6) via `sandbox_run`
        (defaults to sandbox.run_sandboxed; injectable so callers that
        don't want to spin the real OS sandbox for every case still can) --
        confidence is tied directly to the real exit code and stdout, never
        asserted without an actual run."""
        if sandbox_run is None:
            from athenaeum_body.sandbox import run_sandboxed as sandbox_run
        result = sandbox_run(code)
        passed = result.status == "completed" and result.returncode == 0 and "PASS" in result.stdout
        return Claim(
            question_id=question_id, round=1, issuing_agent=self.name,
            subject=task_id,
            statement=f"task '{task_id}': {'implementation verified (PASS)' if passed else 'implementation FAILED verification'}",
            claim_type="executable", confidence=1.0 if passed else 0.0,
            defeat_condition=f"a failing execution (status={result.status}, returncode={result.returncode}, stderr={result.stderr.strip()[:200]!r})",
            jurisdiction_check=True,
            supporting_provenance=[f"executed:sandbox_run:{task_id}"],
            serving_model=serving_model,
        )

    def verify_claim(self, claim: Claim, code: str, *, question_id: str, sandbox_run=None,
                      serving_model: str = "deterministic:sandbox_execution") -> Claim:
        """Cross-cutting verification routing (Phase 15 task 44): another
        agent's formalizable claim (a Mathematics combinatorial check, a
        Physics simulation) can be routed to Engineering with `code` as the
        executable check for that specific claim; the result feeds back as
        a corroborating/challenging response against the ORIGINAL claim,
        not a fresh standalone one."""
        verification = self.verify_code(f"verify:{claim.claim_id}", code, question_id=question_id,
                                         sandbox_run=sandbox_run, serving_model=serving_model)
        passed = verification.confidence == 1.0
        return Claim(
            question_id=question_id, round=2, issuing_agent=self.name,
            statement=f"executable verification of '{claim.statement}': {'confirmed' if passed else 'contradicted'}",
            claim_type="executable", confidence=1.0,
            defeat_condition="a different result from re-running the same executable check",
            jurisdiction_check=True,
            relation="corroborates" if passed else "challenges",
            target_claim_id=claim.claim_id,
            supporting_provenance=verification.supporting_provenance,
            serving_model=serving_model,
        )


@master_agent
class MasterOfPhysics:
    """Domain: empirical, causal claims about the natural world, always
    paired with a stated defeat condition (Section 2.2). Here: real
    kinematics -- free-fall time from a stated drop height, computed via
    d = (1/2) g t^2, not asserted. Cross-examines by independently
    re-deriving another claim's stated fall time and challenging on
    disagreement, the same re-derivation pattern Mathematics uses."""
    name = "Physics"
    # Motion verbs are everyday words ("the fall of the Berlin Wall", "drop the
    # subject"), so on their own they only put a question in Physics's
    # jurisdiction when there is physical context too: a stated height or a
    # physical object. The other keywords are unambiguous (known-bugs.md #28).
    _MOTION_VERBS = ("fall", "falling", "fell", "drop", "dropped", "dropping")
    _PHYSICS_TERMS = ("gravity", "velocity", "acceleration", "force", "momentum", "mass")
    _PHYSICAL_OBJECTS = ("object", "ball", "stone", "rock", "apple", "feather", "body", "projectile",
                         "weight", "height", "hammer")
    domain_keywords = _MOTION_VERBS + _PHYSICS_TERMS
    _G = 9.8  # m/s^2, standard gravity approximation

    def in_jurisdiction(self, question: str) -> bool:
        if mentions(question, self._PHYSICS_TERMS):
            return True
        return mentions(question, self._MOTION_VERBS) and (
            bool(self._heights(question)) or mentions(question, self._PHYSICAL_OBJECTS))

    def explore(self, question: str, question_id: str) -> list[Claim]:
        claims = self._explore_deterministic(question, question_id)
        if not claims and self.in_jurisdiction(question):
            fallback = model_backed_claim(agent_name=self.name, question=question,
                                           question_id=question_id, claim_type="empirical")
            if fallback:
                claims = [fallback]
        return claims

    # A number is a drop height only when it carries a length unit ("20m",
    # "20 meters") or directly follows "from" without a time unit. Bare
    # numbers used to be taken as heights, so "did the berlin wall fall in
    # 1989?" produced a 1989 m free-fall claim (known-bugs.md #21).
    _HEIGHT_WITH_UNIT = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*(?:m|meters?|metres?)\b(?!/)")
    _HEIGHT_AFTER_FROM = re.compile(
        r"\bfrom\s+(\d+(?:\.\d+)?)(?![\w.])"  # whole number only: '19.6m' must not yield '19'
        r"(?!\s*(?:s|secs?|seconds?|min|minutes?|hours?|%|mm|cm|km)\b)")
    # "within 3 seconds", "in under 2.5 s", "in more than 4 seconds", ...
    _TIME_BOUND = re.compile(
        r"\b(within|in under|in less than|under|less than|in more than|more than|longer than|at least)\s+"
        r"(\d+(?:\.\d+)?)\s*(?:s|secs?|seconds?)\b")
    _AT_MOST = ("within", "in under", "in less than", "under", "less than")

    def _heights(self, question: str) -> list[str]:
        q = question.lower()
        found = [m.group(1) for m in self._HEIGHT_WITH_UNIT.finditer(q)]
        found += [m.group(1) for m in self._HEIGHT_AFTER_FROM.finditer(q)]
        return [h for h in dict.fromkeys(found) if float(h) > 0]

    def _explore_deterministic(self, question: str, question_id: str) -> list[Claim]:
        if not mentions(question, self._MOTION_VERBS):
            return []
        claims = []
        for height in self._heights(question):
            h = float(height)
            t = (2 * h / self._G) ** 0.5
            claims.append(Claim(
                question_id=question_id, round=1, issuing_agent=self.name,
                subject=height,
                statement=f"an object falling from {height}m takes approximately {t:.2f}s to hit the ground (v0=0, g={self._G} m/s^2)",
                claim_type="empirical", confidence=0.95,
                defeat_condition=f"a differing result under d = 0.5 * g * t^2 with g={self._G} m/s^2, or a measured fall time that disagrees beyond air-resistance-scale tolerance",
                jurisdiction_check=True,
                supporting_provenance=["computed:kinematics_free_fall"],
            ))
            forecast = self._forecast(question, question_id, height, t)
            if forecast is not None:
                claims.append(forecast)
        return claims

    # Probability that a drop resolves the forecast's way, from how much
    # room the vacuum fall time leaves for air resistance -- which can only
    # LENGTHEN a fall, never shorten it. Explicitly a placeholder policy,
    # same status as GRADE_WEIGHT: the direction of each step is physics,
    # the exact numbers are not.
    _SLACK_BANDS = ((0.25, 0.9), (0.10, 0.75), (0.0, 0.5))

    def _forecast(self, question: str, question_id: str, height: str, t: float) -> Claim | None:
        """Section 5.4: a genuine Forecast, only when the question asks for
        one ('will ...') and states a time bound to resolve against. The
        probability lives in the forecast payload, never in `confidence`
        (which stays this agent's confidence in its own computation)."""
        from .output_types import FORECAST, classify_output_type
        if FORECAST not in classify_output_type(question):
            return None
        m = self._TIME_BOUND.search(question.lower())
        if m is None:
            return None
        phrase, bound = m.group(1), float(m.group(2))
        at_most = phrase in self._AT_MOST
        slack = (bound - t) / t  # >0: the vacuum fall finishes before the bound
        if at_most:
            event = f"lands within {m.group(2)}s"
            if slack < 0:
                probability = 0.02
                sensitivity = (f"the {t:.2f}s vacuum fall time already exceeds {m.group(2)}s and air "
                               "resistance only lengthens it; resolves YES only if the height or g is wrong")
            else:
                probability = next(p for floor, p in self._SLACK_BANDS if slack >= floor)
                sensitivity = f"resolves NO if air resistance adds more than {bound - t:.2f}s to the {t:.2f}s vacuum fall time"
        else:
            event = f"takes more than {m.group(2)}s to land"
            if slack <= 0:
                probability = 0.95
                sensitivity = (f"the {t:.2f}s vacuum fall time already meets the bound and air resistance "
                               "only lengthens it; resolves NO only if the height or g is wrong")
            else:
                probability = round(next(1 - p for floor, p in self._SLACK_BANDS if slack >= floor), 2)
                sensitivity = f"resolves YES only if air resistance adds at least {bound - t:.2f}s to the {t:.2f}s vacuum fall time"
        statement = f"forecast: an object dropped from {height}m {event} (probability {probability:.2f})"
        return Claim(
            question_id=question_id, round=1, issuing_agent=self.name,
            statement=statement, claim_type="empirical", confidence=0.95,
            defeat_condition="a timed drop from this height resolving the other way",
            jurisdiction_check=True,
            supporting_provenance=["computed:kinematics_free_fall"],
            output_type_relevance=[FORECAST],
            forecast={
                "statement": f"an object dropped from rest at {height}m {event}",
                "probability": probability,
                "resolution_criterion": f"measured time from release (v0=0) to ground contact {'<=' if at_most else '>'} {m.group(2)}s",
                "resolution_source": "a direct timing measurement of the drop",
                "deadline": "when the drop is performed",
                "sensitivity": sensitivity,
                "assumptions": ["released from rest", f"g = {self._G} m/s^2",
                                "air resistance not modelled (it can only lengthen the fall)"],
            },
        )

    def cross_examine(self, claim: Claim, question_id: str) -> Claim | None:
        if claim.issuing_agent == self.name or claim.claim_type != "empirical":
            return None
        # Section 2.2 / Section 8 ("unfalsifiable claims presented as
        # physical/empirical"): an empirical claim must say what observation
        # would defeat it. One that can't be falsified isn't asserted as
        # empirical; it's sent to Philosophy's jurisdiction instead.
        if is_vacuous_defeat(claim.defeat_condition):
            return Claim(
                question_id=question_id, round=2, issuing_agent=self.name,
                statement=(f"claim '{claim.statement}' is typed empirical but states no condition under which "
                           "it would be false -- unfalsifiable as stated, so it belongs with Philosophy "
                           "(metaphysical or normative), not with empirical claims"),
                claim_type="procedural", confidence=0.9,
                defeat_condition="the claim is given an observable defeat condition, or retyped non-empirical",
                jurisdiction_check=True, relation="challenges",
                target_claim_id=claim.claim_id,
                supporting_provenance=["reasoning:falsifiability"],
            )
        import re
        m = re.match(r"an object falling from ([\d.]+)m takes approximately ([\d.]+)s", claim.statement)
        if not m:
            return None
        h, stated_t = float(m.group(1)), float(m.group(2))
        actual_t = (2 * h / self._G) ** 0.5
        agrees = abs(actual_t - stated_t) < 0.05
        return Claim(
            question_id=question_id, round=2, issuing_agent=self.name,
            statement=f"independent re-derivation of '{claim.statement}': {'confirmed' if agrees else 'contradicted'} (recomputed {actual_t:.2f}s)",
            claim_type="empirical", confidence=0.95,
            defeat_condition=f"a different result under d = 0.5 * g * t^2 with g={self._G} m/s^2",
            jurisdiction_check=True,
            relation="corroborates" if agrees else "challenges",
            target_claim_id=claim.claim_id,
            supporting_provenance=["computed:kinematics_free_fall"],
        )


@master_agent
class MasterOfPhilosophy:
    """Domain: epistemology, ethics, metaphysics; question-framing and
    assumption-surfacing (Section 2.2). Never asserts a first-order
    empirical/formal claim itself -- like Logic, its authority here is
    about the SHAPE of a claim or question, not its content. Concretely:
    (a) on a normative question, names the is-ought gap as a hidden
    assumption rather than answering the substantive question; (b) on
    cross-examination, flags any OTHER agent's claim that smuggles a
    normative conclusion (should/ought/must) into a claim typed
    'empirical' -- exactly the category-conflation error Section 2.2
    calls out by name."""
    name = "Philosophy"
    domain_keywords = ("should", "ought", "must", "good", "right", "wrong", "value")
    _normative_words = ("should", "ought", "must")

    def in_jurisdiction(self, question: str) -> bool:
        return mentions(question, self.domain_keywords)

    def explore(self, question: str, question_id: str) -> list[Claim]:
        claims = self._explore_deterministic(question, question_id)
        if not claims and self.in_jurisdiction(question):
            fallback = model_backed_claim(agent_name=self.name, question=question,
                                           question_id=question_id, claim_type="normative")
            if fallback:
                claims = [fallback]
        return claims

    def _explore_deterministic(self, question: str, question_id: str) -> list[Claim]:
        q = question.lower()
        if not mentions(q, self._normative_words):
            return []
        # The statement names its question rather than saying "this
        # question": a claim must mean the same thing outside the
        # deliberation that produced it, or claim_key() would treat the
        # is-ought claims about two different questions as one claim
        # (known-bugs.md #22).
        return [Claim(
            question_id=question_id, round=1, issuing_agent=self.name,
            statement=(
                f"the question '{question.strip()}' asks for a normative ('ought') conclusion; "
                "deriving one validly requires at least one explicit normative premise "
                "(the is-ought gap), which the question as framed does not supply"
            ),
            claim_type="normative", confidence=0.9,
            defeat_condition="an explicit normative premise is supplied in the question or its framing",
            jurisdiction_check=True,
            supporting_provenance=["reasoning:is-ought_gap"],
        )]

    def cross_examine(self, claim: Claim, question_id: str) -> Claim | None:
        if claim.issuing_agent == self.name or claim.claim_type != "empirical":
            return None
        stmt = claim.statement.lower()
        if not mentions(stmt, self._normative_words):
            return None
        return Claim(
            question_id=question_id, round=2, issuing_agent=self.name,
            statement=f"claim '{claim.statement}' is typed empirical but asserts a normative conclusion -- category error (is-ought conflation)",
            claim_type="procedural", confidence=0.9,
            defeat_condition="the claim is retyped normative, or the normative wording is shown to be non-prescriptive in context",
            jurisdiction_check=True, relation="challenges",
            target_claim_id=claim.claim_id,
            supporting_provenance=["reasoning:is-ought_gap"],
        )


@master_agent
class MasterOfTheology:
    """Domain: the history, structure, and internal logic of religious/
    metaphysical traditions, argued from within each tradition's own
    premises, never with empirical-grade confidence (Section 2.2). Here:
    a small, real lookup of named traditions' documented positions, always
    emitted as claim_type 'traditional' with confidence capped below
    empirical certainty. Cross-examination enforces the discipline
    mechanically: any claim typed 'traditional' but asserted at
    near-empirical confidence is flagged, jointly implementing what
    Section 6.4 assigns to Logic/Philosophy/Theology together."""
    name = "Theology"
    domain_keywords = ("tradition", "traditional", "doctrine", "scripture", "faith", "religion", "religious")
    _TRADITIONS = {
        "stoicism": "the Stoics hold that virtue is the only true good, and that external things are indifferent to a life well-lived",
        "buddhism": "Buddhism's Four Noble Truths hold that suffering arises from craving/attachment, and that its cessation is attainable",
        "epicureanism": "the Epicureans hold that the good life consists in ataraxia (freedom from disturbance), attained through modest, deliberate pleasure",
    }
    _TRADITIONAL_CONFIDENCE_CAP = 0.75

    def in_jurisdiction(self, question: str) -> bool:
        q = question.lower()
        return mentions(q, self.domain_keywords) or mentions(q, self._TRADITIONS)

    def explore(self, question: str, question_id: str) -> list[Claim]:
        claims = self._explore_deterministic(question, question_id)
        if not claims and self.in_jurisdiction(question):
            # capped at the same confidence as the registry lookup below,
            # not FALLBACK_CONFIDENCE's default -- a model-backed claim
            # about a tradition is still a traditional-premised claim,
            # subject to the exact same 6.4 discipline as a registry hit.
            fallback = model_backed_claim(agent_name=self.name, question=question,
                                           question_id=question_id, claim_type="traditional",
                                           confidence=self._TRADITIONAL_CONFIDENCE_CAP)
            if fallback:
                claims = [fallback]
        return claims

    def _explore_deterministic(self, question: str, question_id: str) -> list[Claim]:
        q = question.lower()
        claims = []
        for tradition, position in self._TRADITIONS.items():
            if mentions(q, (tradition,)):
                claims.append(Claim(
                    question_id=question_id, round=1, issuing_agent=self.name,
                    subject=tradition,
                    statement=f"according to {tradition}: {position}",
                    claim_type="traditional", confidence=self._TRADITIONAL_CONFIDENCE_CAP,
                    defeat_condition=f"a citation from {tradition}'s primary sources or standard critical commentary showing this misrepresents its actual position",
                    jurisdiction_check=True,
                    supporting_provenance=[f"corpus:{tradition}_primary_sources"],
                ))
        return claims

    def cross_examine(self, claim: Claim, question_id: str) -> Claim | None:
        if claim.issuing_agent == self.name or claim.claim_type != "traditional":
            return None
        if claim.confidence < self._TRADITIONAL_CONFIDENCE_CAP + 0.2:
            return None
        return Claim(
            question_id=question_id, round=2, issuing_agent=self.name,
            statement=f"claim '{claim.statement}' is typed traditional but asserted at confidence {claim.confidence}, which carries empirical-grade certainty a faith-premised claim must not claim (Section 6.4)",
            claim_type="procedural", confidence=0.9,
            defeat_condition="the claim's confidence is lowered to reflect its premise-dependent status",
            jurisdiction_check=True, relation="challenges",
            target_claim_id=claim.claim_id,
            supporting_provenance=["policy:traditional_confidence_discipline"],
        )


@master_agent
class MasterOfWorldNews:
    """Domain: current and historical world events -- their chronology and
    documented causal/contributing relationships, for timeline
    construction. A deliberate extension beyond brain-design.md's
    original six Master Agents, recorded explicitly the same way Section
    2.0 records Engineering's own addition (see brain-design.md Section
    2.0b) rather than silently expanding the taxonomy.

    Reasoning mode: mirrors Physics's defeat-condition discipline, but the
    falsifiable unit here is temporal precedence, not a physical law -- an
    event cannot cause, or contribute to, an event that occurred before
    it. That single constraint is mechanically checkable against
    documented dates, the same way Mathematics checks primality: real
    computation, not asserted plausibility."""
    name = "WorldNews"
    domain_keywords = ("timeline", "history", "historical", "event", "war", "treaty",
                        "election", "revolution", "before", "after", "cause", "lead to")

    # Small, real, dated-event registry -- deliberately narrow (a handful
    # of well-documented, uncontroversially-dated events), the same
    # scoping discipline Theology's three-tradition lookup already
    # established: not a general history knowledge base.
    _EVENTS = {
        "world war i": "1914-07-28",
        "treaty of versailles": "1919-06-28",
        "world war ii": "1939-09-01",
        "d-day": "1944-06-06",
        "cuban missile crisis": "1962-10-16",
        "moon landing": "1969-07-20",
        "fall of the berlin wall": "1989-11-09",
        "collapse of the soviet union": "1991-12-26",
    }

    def _find_events(self, text: str) -> list[str]:
        """Event names matched with word boundaries, in the order they
        appear in `text` -- NOT a plain substring `in` check. Real bug
        caught while writing this: 'world war i' is a literal substring
        of 'world war ii' ('world war i' + 'i'), so a naive `in` check
        would wrongly match WWI inside a question that only ever
        mentions WWII. `\\b...\\b` fixes it, since there's no boundary
        between the two adjacent 'i' characters in 'world war ii'."""
        q = text.lower()
        found = []
        for event in self._EVENTS:
            m = re.search(r"\b" + re.escape(event) + r"\b", q)
            if m:
                found.append((m.start(), event))
        return [event for _, event in sorted(found)]

    def in_jurisdiction(self, question: str) -> bool:
        q = question.lower()
        return mentions(q, self.domain_keywords) or bool(self._find_events(question))

    def explore(self, question: str, question_id: str) -> list[Claim]:
        claims = self._explore_deterministic(question, question_id)
        if not claims and self.in_jurisdiction(question):
            fallback = model_backed_claim(agent_name=self.name, question=question,
                                           question_id=question_id, claim_type="empirical")
            if fallback:
                claims = [fallback]
        return claims

    def _explore_deterministic(self, question: str, question_id: str) -> list[Claim]:
        q = question.lower()
        events = self._find_events(question)
        if len(events) != 2:
            return []
        event_a, event_b = events
        date_a, date_b = self._EVENTS[event_a], self._EVENTS[event_b]
        claims = []
        if mentions(q, ("before", "after", "when", "order", "timeline")):
            order = "before" if date_a < date_b else "after"
            claims.append(Claim(
                question_id=question_id, round=1, issuing_agent=self.name,
                subject=f"{event_a}|{event_b}",
                statement=f"'{event_a}' ({date_a}) occurred {order} '{event_b}' ({date_b})",
                claim_type="empirical", confidence=1.0,
                defeat_condition=f"a documented date for '{event_a}' or '{event_b}' that contradicts {date_a}/{date_b}",
                jurisdiction_check=True,
                supporting_provenance=[f"dated_event:{event_a}", f"dated_event:{event_b}"],
            ))
        if mentions(q, ("cause", "caused", "lead to", "led to", "contribute to",
                        "contributed to", "result in", "resulted in")):
            valid = date_a <= date_b
            statement = (
                f"'{event_a}' ({date_a}) precedes '{event_b}' ({date_b}), so a causal/contributing "
                f"link is chronologically POSSIBLE"
            ) if valid else (
                f"'{event_a}' ({date_a}) occurred AFTER '{event_b}' ({date_b}), so it cannot have "
                f"caused or contributed to it -- chronologically IMPOSSIBLE"
            )
            claims.append(Claim(
                question_id=question_id, round=1, issuing_agent=self.name,
                subject=f"{event_a}|{event_b}",
                statement=statement,
                claim_type="empirical", confidence=1.0,
                defeat_condition=f"a documented date for '{event_a}' or '{event_b}' that contradicts {date_a}/{date_b}",
                jurisdiction_check=True,
                supporting_provenance=[f"dated_event:{event_a}", f"dated_event:{event_b}"],
            ))
        return claims

    def cross_examine(self, claim: Claim, question_id: str) -> Claim | None:
        """Independently re-checks another claim's stated causal assertion
        ('X caused Y' / 'X led to Y' / ...) against this registry's
        documented dates -- challenges only when BOTH named events are
        recognized and the claimed direction contradicts them; anything
        outside this registry's narrow coverage is silently abstained
        from, the same discipline every other agent here follows rather
        than guessing at unrecognized events."""
        if claim.issuing_agent == self.name:
            return None
        m = re.search(
            r"'?([\w \-]+?)'?\s+(?:caused|cause|led to|lead to|contributed to|contribute to|resulted in|result in)\s+'?([\w \-]+?)'?[.,]?$",
            claim.statement.strip(), re.IGNORECASE)
        if not m:
            return None
        cause = _strip_leading_article(m.group(1).strip().lower())
        effect = _strip_leading_article(m.group(2).strip().lower())
        if cause not in self._EVENTS or effect not in self._EVENTS:
            return None
        date_cause, date_effect = self._EVENTS[cause], self._EVENTS[effect]
        agrees = date_cause <= date_effect
        return Claim(
            question_id=question_id, round=2, issuing_agent=self.name,
            statement=f"chronological check of '{claim.statement}': {'consistent' if agrees else 'IMPOSSIBLE'} -- '{cause}' is dated {date_cause}, '{effect}' is dated {date_effect}",
            claim_type="empirical", confidence=1.0,
            defeat_condition=f"a documented date for '{cause}' or '{effect}' that contradicts {date_cause}/{date_effect}",
            jurisdiction_check=True,
            relation="corroborates" if agrees else "challenges",
            target_claim_id=claim.claim_id,
            supporting_provenance=[f"dated_event:{cause}", f"dated_event:{effect}"],
        )

    def build_timeline(self, event_names: list[str]) -> dict:
        """Not part of the claim/cross-examination loop -- a direct
        utility for the stated goal ('create timelines for how major
        events tie into each other'): sorts recognized events by their
        documented date. Unrecognized names are reported, not silently
        dropped, so a caller knows a returned timeline is partial rather
        than assuming completeness."""
        recognized = [(name, self._EVENTS[name.lower()]) for name in event_names if name.lower() in self._EVENTS]
        unrecognized = [name for name in event_names if name.lower() not in self._EVENTS]
        ordered = sorted(recognized, key=lambda pair: pair[1])
        return {
            "timeline": [{"event": name, "date": date} for name, date in ordered],
            "unrecognized": unrecognized,
        }
