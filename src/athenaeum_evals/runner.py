"""Run Athenaeum's evaluation suites and write the artifacts.

    python scripts/run_evals.py [--suites adversarial,...] [--out eval_out]

Each suite module provides `SUITE` and `evaluate(...) -> list[CaseResult]`
(case-level suites) or `metrics(...) -> {name: SuiteMetric}` (suite-level).
A module with a `SOURCE` builds on another suite's case results
(`evaluate(results)`, `metrics(results, config)`); that suite is run for it
if it wasn't asked for, and never twice.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from evalcore import Config
from evalcore.run import Evaluation, EvaluationResult

from . import adversarial, api_service, calibration, deliberation, human_input, judging, model_answers, provenance

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "evals" / "golden"
BASELINE = ROOT / "evals" / "baselines" / "baseline.json"

SUITES = {m.KEY: m for m in (adversarial, deliberation, calibration, provenance, human_input, api_service, model_answers, judging)}
# The suites that can reach a verdict today: judging is informational and
# waits on a qualifying model (batch 14), provenance on the owner's citation
# labels (D17). The baseline is
# saved from these (owner decision, batch 13): run_evals.py --suites decidable --save-baseline
DECIDABLE = [k for k in SUITES if k not in (judging.KEY, provenance.KEY)]


def run(out: Path, suites: list[str] | None = None, *, config: Config | None = None,
        save_as_baseline: bool = False, generated_at: dt.datetime | None = None) -> EvaluationResult:
    keys = list(SUITES) if suites is None else suites
    unknown = sorted(set(keys) - set(SUITES))
    if unknown:
        raise ValueError(f"unknown suites {unknown}; available: {sorted(SUITES)}")
    # Per-suite baselines (evalcore 0.1.2): the baseline covers the decidable
    # suites (owner decision, batch 13), so the others must not switch it off.
    config = config or Config(baseline_per_suite=True)
    modules = [SUITES[k] for k in keys]
    ev = Evaluation([m.SUITE for m in modules], config, golden_dir=GOLDEN, baseline_path=BASELINE)
    case_results = {}

    def results_of(key):
        if key not in case_results:
            m = SUITES[key]
            case_results[key] = m.evaluate(results_of(m.SOURCE)) if hasattr(m, "SOURCE") else m.evaluate()
        return case_results[key]

    for m in modules:
        if hasattr(m, "evaluate"):
            for result in results_of(m.KEY):
                ev.record(result)
        if hasattr(m, "metrics"):
            got = m.metrics(results_of(m.SOURCE), config) if hasattr(m, "SOURCE") else m.metrics()
            for name, metric in got.items():
                ev.set_metric(m.KEY, name, metric)
        if hasattr(m, "SYSTEM_INFO"):
            ev.system_info(m.KEY, **m.SYSTEM_INFO)
    result = ev.finish(out, save_as_baseline=save_as_baseline, generated_at=generated_at,
                       report_name="Athenaeum evaluation")
    if save_as_baseline and result.verdict.status == "APPROVED" and calibration.KEY in keys:
        calibration.save_confidences(case_results[calibration.SOURCE])   # PSI's reference sample
    return result
