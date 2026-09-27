"""Are the agents' confidences honest? Calibration of committed claims.

The data are the claims the deliberation suite labelled right or wrong
against its golden answers: formal and empirical claims only, each with its
agent and stated confidence. Ground truth, so nothing here depends on a judge.
(The runtime calibration store, fed by idle-evolution re-challenges, is judged
by the challenger model; it belongs to a judge-scored gate, not this one.)

Gates, all on the pessimistic end of a bootstrap interval that resamples
golden questions, since a question's wordings share their claims' fate:
- ECE (expected calibration error) and Brier score, over all labelled claims;
- the worst agent's ECE, over agents with enough labelled claims;
- PSI of the confidence distribution against the saved baseline's, when a
  baseline sample exists (optional: nothing to compare with on a first run).

What this can't show, and says on the card: when every labelled claim is
right (the deterministic agents compute their answers), ECE only measures
under-confidence. It becomes a test of over-confidence once wrong claims
appear, e.g. from model-backed fallbacks on the lab models.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from evalcore import Config, GateSpec, Suite, SuiteMetric
from evalcore.calibration import brier, ece
from evalcore.stats import psi

from . import deliberation

KEY = "calibration"
SOURCE = deliberation.KEY                    # the suite whose results this scores
NAN = float("nan")
CONFIDENCES = Path(__file__).resolve().parents[2] / "evals" / "baselines" / "confidences.json"

SUITE = Suite(
    key=KEY, title="Claim calibration (per agent)",
    suite_gates=[
        GateSpec("ece", "Expected calibration error", "<=", "calibration_max_ece"),
        GateSpec("brier", "Brier score", "<=", "calibration_max_brier"),
        GateSpec("worst_agent_ece", "Worst agent's calibration error", "<=", "calibration_max_agent_ece", min_n=1),
        GateSpec("confidence_psi", "Confidence drift from baseline (PSI)", "<=", "calibration_max_psi", min_n=1),
    ],
    optional_gates=frozenset({"confidence_psi"}),
    defaults={"calibration_max_ece": 0.10, "calibration_max_brier": 0.10,
              "calibration_max_agent_ece": 0.15, "calibration_max_psi": 0.25,
              "calibration_min_agent_claims": 15},
)


def labelled(results) -> list[dict]:
    """(case, agent, confidence, verified) for every labelled claim."""
    return [{"case": r.case_id, **claim} for r in results for claim in r.detail.get("labelled", [])]


def _cluster_bootstrap(rows: list[dict], fn, config: Config, seed_offset: int = 0) -> tuple[float, float, float]:
    """fn over all rows, with a percentile interval from resampling whole
    golden questions (every wording of a question together)."""
    y = np.array([r["verified"] for r in rows], dtype=float)
    p = np.array([r["confidence"] for r in rows], dtype=float)
    point = float(fn(y, p))
    by_case = defaultdict(list)
    for i, r in enumerate(rows):
        by_case[r["case"]].append(i)
    clusters = [np.array(v) for v in by_case.values()]
    rng = np.random.default_rng(config.seed + seed_offset)
    stats = []
    for _ in range(config.bootstrap_iterations):
        idx = np.concatenate([clusters[k] for k in rng.integers(0, len(clusters), len(clusters))])
        stats.append(fn(y[idx], p[idx]))
    alpha = (1 - config.confidence) / 2
    return point, float(np.quantile(stats, alpha)), float(np.quantile(stats, 1 - alpha))


def _metric(rows, fn, config, note, seed_offset=0) -> SuiteMetric:
    if not rows:
        return SuiteMetric(NAN, n=0, detail={"note": "no labelled claims"})
    value, lo, hi = _cluster_bootstrap(rows, fn, config, seed_offset)
    return SuiteMetric(value, lo, hi, n=len(rows), detail={"note": note})


def metrics(results, config: Config | None = None, baseline_confidences: list[float] | None = None
            ) -> dict[str, SuiteMetric]:
    config = config or Config()
    thresholds = {**SUITE.defaults, **dict(config.thresholds)}
    rows = labelled(results)
    wrong = sum(1 for r in rows if not r["verified"])
    note = (f"{len(rows)} labelled claims from {len({r['case'] for r in rows})} golden questions, {wrong} wrong"
            + ("; none wrong, so this measures only under-confidence" if rows and not wrong else ""))
    out = {"ece": _metric(rows, ece, config, note), "brier": _metric(rows, brier, config, note, 1)}

    per_agent = defaultdict(list)
    for r in rows:
        per_agent[r["agent"]].append(r)
    floor = int(thresholds["calibration_min_agent_claims"])
    gated, small = {}, []
    for i, (agent, agent_rows) in enumerate(sorted(per_agent.items())):
        if len(agent_rows) < floor:
            small.append(f"{agent} (n={len(agent_rows)})")
            continue
        gated[agent] = _cluster_bootstrap(agent_rows, ece, config, 10 + i) + (len(agent_rows),)
    agent_note = ", ".join(f"{a}={v:.3f} (n={n})" for a, (v, _, _, n) in gated.items())
    if small:
        agent_note += f"{'; ' if agent_note else ''}not gated (fewer than {floor} claims): {', '.join(small)}"
    if gated:
        worst = max(gated, key=lambda a: gated[a][2])          # the pessimistic end decides
        v, lo, hi, n = gated[worst]
        out["worst_agent_ece"] = SuiteMetric(v, lo, hi, n=n, detail={"note": f"worst: {worst}; {agent_note}"})
    else:
        out["worst_agent_ece"] = SuiteMetric(NAN, n=0, detail={"note": agent_note or "no labelled claims"})

    if baseline_confidences is None:
        baseline_confidences = saved_confidences()
    if baseline_confidences and rows:                          # absent: the optional gate stays NOT_RUN
        value = psi(baseline_confidences, [r["confidence"] for r in rows])
        out["confidence_psi"] = SuiteMetric(value, value, value, n=len(rows),
                                            detail={"note": f"against {len(baseline_confidences)} baseline confidences"})
    return out


def saved_confidences(path: Path = CONFIDENCES) -> list[float] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))["confidences"]


def save_confidences(results, path: Path = CONFIDENCES) -> None:
    path.write_text(json.dumps({"confidences": [r["confidence"] for r in labelled(results)]}, indent=1) + "\n",
                    encoding="utf-8")
