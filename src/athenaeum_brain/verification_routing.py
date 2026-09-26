"""
Cross-agent verification routing (brain-design.md Phase 15, task 44):
another agent's formalizable claim is routed to Engineering, which checks
it by actually executing an INDEPENDENT method in the Body's sandbox; the
result comes back as a corroborating or challenging response against the
original claim (MasterOfEngineering.verify_claim).

Independence is the point. Each verifier below re-derives the claim by a
different method from the one that produced it -- a sieve instead of
trial division for primality, numerical integration instead of the
closed-form d = g t^2 / 2 for free fall -- so agreement is real
corroboration, not the same computation run twice.

Gate: routing only ever happens when the caller says the execution
sandbox is enabled, and the deliberation loop takes that from
`execution_sandbox.enabled` in config (CLAUDE.md hard constraint: false
until every security-review-sandbox.md scenario passes on the target
host). While it is false, nothing is routed and nothing is executed; the
skip is reported, not silent.
"""
from __future__ import annotations
import re
from pathlib import Path
from athenaeum_body.config import Config
from .claims import Claim

_VERIFIERS = []

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "config.defaults.yaml"


def verifier(fn):
    """Registers a function claim -> python source (or None if the claim
    isn't one it can check). The source must print exactly 'PASS' and exit
    0 when the claim holds -- verify_code's specification format."""
    _VERIFIERS.append(fn)
    return fn


def sandbox_enabled(config: Config | None = None) -> bool:
    """execution_sandbox.enabled from config (defaults file if none given).
    Anything other than a literal True counts as disabled."""
    cfg = config or Config.load(str(DEFAULT_CONFIG))
    return cfg.get("execution_sandbox", "enabled", default=False) is True


@verifier
def primality_check(claim: Claim) -> str | None:
    m = re.fullmatch(r"(\d+) is (prime|not prime)", claim.statement)
    if not m:
        return None
    n, claimed_prime = int(m.group(1)), m.group(2) == "prime"
    if n > 10_000_000:
        return None  # a sieve that large isn't a sensible sandbox job
    return (
        f"n = {n}\n"
        "sieve = bytearray([1]) * (n + 1)\n"
        "sieve[0:2] = b'\\x00\\x00'[:min(2, n + 1)]\n"
        "i = 2\n"
        "while i * i <= n:\n"
        "    if sieve[i]:\n"
        "        sieve[i * i::i] = bytearray(len(range(i * i, n + 1, i)))\n"
        "    i += 1\n"
        f"print('PASS' if bool(sieve[n]) == {claimed_prime} else 'FAIL')\n"
    )


@verifier
def free_fall_check(claim: Claim) -> str | None:
    m = re.match(r"an object falling from ([\d.]+)m takes approximately ([\d.]+)s to hit the ground "
                 r"\(v0=0, g=([\d.]+) m/s\^2\)", claim.statement)
    if not m:
        return None
    h, t_claimed, g = (float(x) for x in m.groups())
    if h > 10_000:
        return None  # ~450k steps at most; beyond that, the sandbox's wall clock would decide, not physics
    # Semi-implicit Euler, 0.1 ms steps: an independent route to the fall
    # time, agreeing with the closed form to well under the 0.01 s the
    # claim is stated to.
    return (
        f"h, g, dt = {h}, {g}, 1e-4\n"
        "y, v, t = 0.0, 0.0, 0.0\n"
        "while y < h:\n"
        "    v += g * dt\n"
        "    y += v * dt\n"
        "    t += dt\n"
        f"print('PASS' if abs(t - {t_claimed}) <= 0.01 else 'FAIL')\n"
    )


def verification_code(claim: Claim) -> str | None:
    for fn in _VERIFIERS:
        code = fn(claim)
        if code is not None:
            return code
    return None


def route_for_verification(claims: list[Claim], question_id: str, *, enabled: bool,
                           sandbox_run=None) -> dict:
    """Routes every claim a verifier recognises to Engineering. Engineering's
    own claims are never routed back to it. Returns {'responses', 'routed',
    'skipped_reason'}; the responses are ordinary round-2 claims targeting
    the originals, so synthesis treats them like any cross-examination."""
    if not enabled:
        routable = sum(1 for c in claims if c.issuing_agent != "Engineering" and verification_code(c))
        return {"responses": [], "routed": 0,
                "skipped_reason": (f"execution_sandbox.enabled is false; {routable} verifiable claim(s) "
                                   "left to ordinary cross-examination") if routable else None}
    from .agents import MasterOfEngineering
    engineering = MasterOfEngineering()
    responses = []
    for claim in claims:
        if claim.issuing_agent == engineering.name:
            continue
        code = verification_code(claim)
        if code is not None:
            responses.append(engineering.verify_claim(claim, code, question_id=question_id,
                                                      sandbox_run=sandbox_run))
    return {"responses": responses, "routed": len(responses), "skipped_reason": None}
