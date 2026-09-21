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
                    topic=f"rounding:{token}",
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
                topic=f"rounding:{token}",
                statement=f"{token} rounds to {rounded} (IEEE-754 round-half-to-even convention)",
                claim_type="executable", confidence=1.0,
                defeat_condition="a different result under decimal.ROUND_HALF_EVEN",
                jurisdiction_check=True,
                supporting_provenance=["computed:decimal.ROUND_HALF_EVEN"],
            ))
        return claims

    def cross_examine(self, claim: Claim, question_id: str) -> Claim | None:
        return None
