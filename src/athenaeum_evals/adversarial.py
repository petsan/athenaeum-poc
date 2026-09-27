"""The 15 failure modes of brain-design §8, as hard gates.

Each of the 16 checks in `evaluation.ADVERSARIAL_CASES` (category error has
two) exercises one defence against the real deliberation machinery. Here a
check that returns False, or raises, is a hard violation: one undefended
failure mode rejects the release. A coverage line on the card says whether
every §8 row had at least one check that ran.
"""
from __future__ import annotations

import time
import traceback

from evalcore import CaseResult, CoverageCheck, Suite

from athenaeum_brain.evaluation import ADVERSARIAL_CASES, SECTION_8_COVERAGE

KEY = "adversarial"
ROW_OF = {case: row for row, cases in SECTION_8_COVERAGE.items() for case in cases}


def _every_row_ran(results, _metrics):
    ran = {r.category for r in results}
    missing = sorted(set(SECTION_8_COVERAGE) - ran)
    label = (f"Every §8 failure mode checked ({len(ran)} of {len(SECTION_8_COVERAGE)} rows)" if not missing
             else f"§8 rows with no check that ran: {', '.join(missing)}")
    return (not missing, label)


SUITE = Suite(
    key=KEY, title="Adversarial failure modes (brain-design §8)",
    hard_gate_label="Undefended failure modes",
    coverage=[CoverageCheck(_every_row_ran)],
)


def evaluate(checks: dict | None = None) -> list[CaseResult]:
    """Run each check once. Pure apart from the checks themselves, so a test
    can pass in a planted failing (or crashing) check."""
    checks = ADVERSARIAL_CASES if checks is None else checks
    results = []
    for name, check in checks.items():
        row = ROW_OF.get(name, "unmapped")
        result = CaseResult(KEY, name, row, "original", 0)
        started = time.perf_counter()
        try:
            defended = bool(check())
        except Exception as e:                          # a crashing defence is not a defence
            defended = False
            result.detail["error"] = "".join(traceback.format_exception_only(type(e), e)).strip()
        result.latency_s = time.perf_counter() - started
        result.metrics["defended"] = float(defended)
        if not defended:
            why = result.detail.get("error", "the defence did not hold")
            result.hard_violations.append(f"{row}: {why}")
            result.detail["problem"] = f"{name}: {why}"
        results.append(result)
    return results
