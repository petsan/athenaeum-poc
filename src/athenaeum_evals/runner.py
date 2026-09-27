"""Run Athenaeum's evaluation suites and write the artifacts.

    python scripts/run_evals.py [--suites adversarial,...] [--out eval_out]

Each suite module provides `SUITE` and `evaluate(...) -> list[CaseResult]`
(case-level suites) or `metrics(...) -> {name: SuiteMetric}` (suite-level).
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from evalcore import Config
from evalcore.run import Evaluation, EvaluationResult

from . import adversarial, judging

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "evals" / "golden"
BASELINE = ROOT / "evals" / "baselines" / "baseline.json"

SUITES = {adversarial.KEY: adversarial, judging.KEY: judging}


def run(out: Path, suites: list[str] | None = None, *, config: Config | None = None,
        save_as_baseline: bool = False, generated_at: dt.datetime | None = None) -> EvaluationResult:
    keys = list(SUITES) if suites is None else suites
    unknown = sorted(set(keys) - set(SUITES))
    if unknown:
        raise ValueError(f"unknown suites {unknown}; available: {sorted(SUITES)}")
    modules = [SUITES[k] for k in keys]
    ev = Evaluation([m.SUITE for m in modules], config or Config(), golden_dir=GOLDEN, baseline_path=BASELINE)
    for m in modules:
        if hasattr(m, "evaluate"):
            for result in m.evaluate():
                ev.record(result)
        if hasattr(m, "metrics"):
            for name, metric in m.metrics().items():
                ev.set_metric(m.KEY, name, metric)
        if hasattr(m, "SYSTEM_INFO"):
            ev.system_info(m.KEY, **m.SYSTEM_INFO)
    return ev.finish(out, save_as_baseline=save_as_baseline, generated_at=generated_at,
                     report_name="Athenaeum evaluation")
