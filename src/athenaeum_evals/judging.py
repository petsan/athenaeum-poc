"""Can the admitted challenger model judge? The judging benchmark as a
judge-validation suite (`validates_judge=True`, evalcore's judge dependency).

It reads each challenger's latest recorded benchmark result (written by
scripts/run_judging_benchmark.py --record) and turns it into one suite metric:
the fraction of cases the model judged right on every repeat, with its Wilson
interval, gated on the lower bound against the same bar the runtime uses.
The metric is withheld (INSUFFICIENT_DATA, never a pass) when:
- there is no result, or it is for older items or prompts; or
- the benchmark is provisional: the owner hasn't reviewed it yet (D15).
Every other suite's judge-scored gates depend on this one passing.

The suite is informational (owner decision, batch 14): its gate is shown on
the card but never decides the verdict. No lab model qualifies yet, and the
runtime already ignores an unqualified challenger's challenges, so a miss
here is a capability status, not a release defect.
"""
from __future__ import annotations

from pathlib import Path

from evalcore import GateSpec, Suite, SuiteMetric
from evalcore.stats import wilson_ci

from athenaeum_body.model_fitness_store import ModelFitnessStore
from athenaeum_body.storage.checkpoint import CheckpointLog
from athenaeum_body.storage.content_addressed import ContentAddressedStore
from athenaeum_brain import judging_benchmark as jb
from athenaeum_brain.model_backed_reasoning import DEFAULT_MODEL

KEY = "judging"
NAN = float("nan")
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "api-run"           # the API's store, where live runs are recorded

SUITE = Suite(
    key=KEY, title="Challenger judging benchmark",
    suite_gates=[GateSpec("challenger_agreement", f"Admitted challenger ({DEFAULT_MODEL}) judges right",
                          ">=", jb.QUALIFYING_ACCURACY, min_n=1)],
    validates_judge=True,
    informational=True,
)
SYSTEM_INFO = {"name": "challenger", "model_id": DEFAULT_MODEL, "prompt_version": jb.PROMPT_VERSION}


def store_at(data_dir: Path) -> ModelFitnessStore:
    return ModelFitnessStore(CheckpointLog(cas=ContentAddressedStore(data_dir / "cas"),
                                           index_path=data_dir / "model-fitness.txt"))


def agreement(result: dict | None, reviewed: bool) -> SuiteMetric:
    """One recorded benchmark result as a suite metric (withheld when it can't count)."""
    if result is None:
        return SuiteMetric(NAN, n=0, detail={"note": "never run on the judging benchmark"})
    if result.get("benchmark_version") != jb.BENCHMARK_VERSION or result.get("prompt_version") != jb.PROMPT_VERSION:
        return SuiteMetric(NAN, n=0, detail={"note": "the latest result is for older items or prompts; run it again"})
    if "cases_right" not in result:
        return SuiteMetric(NAN, n=0, detail={"note": "recorded before the Wilson rule; run it again"})
    right, n = result["cases_right"], result["cases"]
    low, high = wilson_ci(right, n, jb.CONFIDENCE)
    misses = len(result.get("misses", []))
    note = f"{right}/{n} cases right on every repeat; {misses} missed judgment(s)"
    if not reviewed:
        return SuiteMetric(NAN, n=n, detail={"note": f"{note}; benchmark provisional (awaiting the owner's review)"})
    return SuiteMetric(right / n, low, high, n=n, detail={"note": note})


def metrics(data_dir: Path | None = None, model: str = DEFAULT_MODEL) -> dict[str, SuiteMetric]:
    store = store_at(data_dir or DATA_DIR)
    return {"challenger_agreement": agreement(store.judging(model), jb.reviewed())}
