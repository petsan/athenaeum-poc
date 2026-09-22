"""
Toy, deterministic Master Agents (Section 2).

These stand in for LLM-backed reasoning, which needs the Body's Local
Model Serving Layer (not yet built -- see progress.md). To keep this
slice honest and independently checkable without an LLM, each agent's
claims are backed by real, verifiable computation in a narrow domain,
not hand-waved text. This proves the deliberation *mechanics*
(claim structure, jurisdiction, cross-examination, commit boundary),
not reasoning quality.
"""
from __future__ import annotations
from .claims import Claim


def _is_prime(n: int) -> bool:
    if n < 2:
        return False
    for d in range(2, int(n ** 0.5) + 1):
        if n % d == 0:
            return False
    return True


class MasterOfMathematics:
    """Domain: formal/quantitative claims. Reasoning mode: definition ->
    derivation -> proof (Section 2.2). Here: real primality checks."""
    name = "Mathematics"
    domain_keywords = ("prime", "number", "divisible", "sum", "even", "odd", "round")

    def in_jurisdiction(self, question: str) -> bool:
        return any(k in question.lower() for k in self.domain_keywords)

    def explore(self, question: str, question_id: str) -> list[Claim]:
        claims = []
        for token in question.replace("?", "").split():
            if token.isdigit():
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
        if "round" in question.lower():
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


class MasterOfLogic:
    """Domain: validity of argument form, never first-order domain content
    (Section 2.2). Chairs synthesis/dispute resolution (Section 4)."""
    name = "Logic"
    domain_keywords = ("all", "every", "therefore", "if", "then", "valid")

    def in_jurisdiction(self, question: str) -> bool:
        return any(k in question.lower() for k in self.domain_keywords)

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


class MasterOfEngineering:
    """Domain: specification/implementation/verification via execution
    (Section 2.2, the sixth Master Agent). Here: real Decimal computation
    under the IEEE-754-style round-half-to-even convention -- a genuinely
    different, equally defensible answer from Mathematics's classical
    round-half-up convention, used to exercise Section 4.2's jurisdictional
    conflict path."""
    name = "Engineering"
    domain_keywords = ("round", "implement", "execute", "verify", "test")

    def in_jurisdiction(self, question: str) -> bool:
        return any(k in question.lower() for k in self.domain_keywords)

    def explore(self, question: str, question_id: str) -> list[Claim]:
        if "round" not in question.lower():
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


class MasterOfPhysics:
    """Domain: empirical, causal claims about the natural world, always
    paired with a stated defeat condition (Section 2.2). Here: real
    kinematics -- free-fall time from a stated drop height, computed via
    d = (1/2) g t^2, not asserted. Cross-examines by independently
    re-deriving another claim's stated fall time and challenging on
    disagreement, the same re-derivation pattern Mathematics uses."""
    name = "Physics"
    domain_keywords = ("fall", "falling", "drop", "gravity", "velocity", "acceleration", "force")
    _G = 9.8  # m/s^2, standard gravity approximation

    def in_jurisdiction(self, question: str) -> bool:
        return any(k in question.lower() for k in self.domain_keywords)

    def explore(self, question: str, question_id: str) -> list[Claim]:
        if not any(k in question.lower() for k in ("fall", "falling", "drop")):
            return []
        import re
        claims = []
        for token in question.replace("?", "").split():
            m = re.match(r"^(\d+(?:\.\d+)?)m?$", token)
            if not m:
                continue
            h = float(m.group(1))
            if h <= 0:
                continue
            t = (2 * h / self._G) ** 0.5
            claims.append(Claim(
                question_id=question_id, round=1, issuing_agent=self.name,
                subject=m.group(1),
                statement=f"an object falling from {m.group(1)}m takes approximately {t:.2f}s to hit the ground (v0=0, g={self._G} m/s^2)",
                claim_type="empirical", confidence=0.95,
                defeat_condition=f"a differing result under d = 0.5 * g * t^2 with g={self._G} m/s^2, or a measured fall time that disagrees beyond air-resistance-scale tolerance",
                jurisdiction_check=True,
                supporting_provenance=["computed:kinematics_free_fall"],
            ))
        return claims

    def cross_examine(self, claim: Claim, question_id: str) -> Claim | None:
        if claim.issuing_agent == self.name or claim.claim_type != "empirical":
            return None
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
        return any(k in question.lower() for k in self.domain_keywords)

    def explore(self, question: str, question_id: str) -> list[Claim]:
        q = question.lower()
        if not any(w in q for w in self._normative_words):
            return []
        return [Claim(
            question_id=question_id, round=1, issuing_agent=self.name,
            statement=(
                "this question asks for a normative ('ought') conclusion; deriving one validly "
                "requires at least one explicit normative premise (the is-ought gap), which the "
                "question as framed does not supply"
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
        if not any(w in stmt for w in self._normative_words):
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
    domain_keywords = ("tradition", "doctrine", "scripture", "faith", "religion")
    _TRADITIONS = {
        "stoicism": "the Stoics hold that virtue is the only true good, and that external things are indifferent to a life well-lived",
        "buddhism": "Buddhism's Four Noble Truths hold that suffering arises from craving/attachment, and that its cessation is attainable",
        "epicureanism": "the Epicureans hold that the good life consists in ataraxia (freedom from disturbance), attained through modest, deliberate pleasure",
    }
    _TRADITIONAL_CONFIDENCE_CAP = 0.75

    def in_jurisdiction(self, question: str) -> bool:
        q = question.lower()
        return any(k in q for k in self.domain_keywords) or any(t in q for t in self._TRADITIONS)

    def explore(self, question: str, question_id: str) -> list[Claim]:
        q = question.lower()
        claims = []
        for tradition, position in self._TRADITIONS.items():
            if tradition in q:
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
