"""
Real propositional-logic validity checking (Section 2.2's actual job for
Logic -- "evaluates... claim structures for validity", not just
jurisdiction). Deterministic, no LLM: validity is decided by brute-force
truth-table enumeration, which is general (any propositional argument in
the supported grammar) rather than pattern-matching a fixed list of named
fallacies -- a genuine validity checker, not a lookup table.

Grammar (single-level, deliberately minimal but real):
  "A"            atomic variable (a single uppercase letter)
  "not A"        negation
  "A and B"      conjunction
  "A or B"       disjunction
  "A -> B"       implication
"""
from __future__ import annotations
import re
import itertools

_ATOM = re.compile(r"^[A-Z]$")

def _compile(expr: str):
    expr = expr.strip()
    if m := re.match(r"^not\s+([A-Z])$", expr):
        v = m.group(1); return lambda env: not env[v], {v}
    if m := re.match(r"^([A-Z])\s+and\s+([A-Z])$", expr):
        a, b = m.groups(); return lambda env: env[a] and env[b], {a, b}
    if m := re.match(r"^([A-Z])\s+or\s+([A-Z])$", expr):
        a, b = m.groups(); return lambda env: env[a] or env[b], {a, b}
    if m := re.match(r"^([A-Z])\s*->\s*([A-Z])$", expr):
        a, b = m.groups(); return lambda env: (not env[a]) or env[b], {a, b}
    if _ATOM.match(expr):
        return lambda env: env[expr], {expr}
    raise ValueError(f"unsupported expression form: {expr!r}")


def check_validity(premises: list[str], conclusion: str) -> dict:
    """An argument is VALID iff every truth assignment satisfying all
    premises also satisfies the conclusion (no counterexample exists).
    Returns a genuine counterexample assignment when invalid, not just
    a yes/no."""
    compiled = [_compile(p) for p in premises]
    concl_fn, concl_vars = _compile(conclusion)
    variables = set(concl_vars)
    for _, vs in compiled:
        variables |= vs
    variables = sorted(variables)

    for combo in itertools.product([False, True], repeat=len(variables)):
        env = dict(zip(variables, combo))
        if all(fn(env) for fn, _ in compiled) and not concl_fn(env):
            return {"valid": False, "counterexample": dict(env),
                    "explanation": f"premises are all true and conclusion is false under {env}"}
    return {"valid": True, "counterexample": None,
            "explanation": "no assignment makes every premise true and the conclusion false"}
