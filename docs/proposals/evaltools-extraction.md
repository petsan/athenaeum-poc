# Plan: a thin, reusable evaluation toolkit extracted from evalgate

Status: **plan only, for the owner's decision. Nothing is built.**
Written 2026-09-27, from evalgate `9baa359` (v0.2.0). Working name **`evalcore`** (decision X1).

This plan lives in the Athenaeum repo only because that is where this session works. It is **not Athenaeum work**: the toolkit is meant for any project. The file moves to the new repo when that repo is created.

## 1. Goal

Take the evaluation *tools* out of evalgate and package them as a small, general library that any project can use:
- the statistics, the gates and the verdict;
- the detectors, the judge calibration and the calibration metrics;
- the baselines and the reporting.

It must work in projects that have nothing to do with Athenaeum, medical devices, SQL or RAG, and in projects that don't use pytest.

"Thin" is a hard requirement:
- **One dependency: numpy.** No pandas, no scikit-learn, no pytest, no pydantic, no sqlglot. Each of those becomes optional or goes away.
- **No global state:** no settings singleton, no recorder singleton. Everything is passed explicitly, so two evaluations can run in one process and tests need no resets.
- **No framework coupling.** Plain functions and small dataclasses. The pytest plugin, CLI and viewer are separate, optional layers on top.
- **Small:** about 1,200 lines of library code. evalgate's generic machinery is about 1,100 lines today, plus the new tool-efficacy module (§3, item 9).

## 2. What is extracted, and what stays behind

| evalgate today | Goes to `evalcore` | Stays in evalgate (or is dropped) |
|---|---|---|
| `stats.py` | all of it: Wilson CI, cluster bootstrap over cases, bootstrap metric, percentile, PSI | — |
| `gates.py` | `Gate`, `decide`, the gate kinds (hard, quality, robustness, SLO, suite), the judge-dependency rule, the verdict, baseline save/compare | The glue that reads `S` settings and the pytest outcome counts; it becomes a thin call into the core |
| `recorder.py` | `CaseResult`, `SuiteMetric`, `Recorder` as an **instance** | The `RECORDER` singleton (evalgate keeps one instance for its plugin) |
| `registry.py` | `Suite`, `GateSpec`, `CoverageCheck` as plain declarations | Registration into pytest markers, `plugin=` import hooks |
| `metrics/judges.py` | `Judge` protocol, `LexicalJudge`, `LLMJudge(complete)`, `parse_judge_score` | — |
| `suites/judge.py` | judge calibration: agreement with a Wilson CI, Cohen's kappa (pure-numpy, replacing scikit-learn), disagreements | The pytest test function and the medical calibration data |
| `metrics/rag_eval.py` | recall@k, MRR, citation extraction, fabricated citations, citation support | — |
| `metrics/safety.py` | `leaked_canaries`; a **configurable** pattern detector (`find_patterns(text, patterns)`) | The PHI regexes become an optional preset (`presets.phi_us`), not the default |
| `metrics/scoring_eval.py`, `suites/scoring.py` | ECE (inclusive bins), Brier, ROC-AUC (pure numpy), worst-subgroup | The pytest tests, the DataFrame holdout loaders |
| `data.py` | dataset hashing, variant expansion (original + paraphrases), required-category and minimum-case checks | pydantic model loading becomes optional (any callable validator) |
| `card.py`, `report.py` | eval card (only checks that ran), results JSON **schema v2, unchanged**, report embedding | The viewer HTML stays shared; see §3 item 11 |
| `cache.py` | the response cache, development only, keyed by system, method, args and run | — |
| `metrics/sql_*`, `suites/text_to_sql.py`, `suites/rag.py`, `demo/`, medical golden data | — | **Stay in evalgate.** Domain suites are consumers of the core, not part of it |
| `settings.py`, `plugin.py`, `cli.py`, `runtime.py`, `selftest.py` | — | **Stay in evalgate** as its pytest front end. The core gets its own plain-Python front end (§3 item 10) |

## 3. The toolkit, module by module

1. **`evalcore.stats`**: `wilson_ci`, `cluster_bootstrap_mean`, `bootstrap_metric`, `percentile`, `psi`, `cohen_kappa`. New:
   - `min_detectable_effect(n, threshold, confidence)`;
   - `required_n(successes_allowed, threshold, confidence)`.
   
   These answer "how many cases do I need?" before anyone builds a golden set. This is the Athenaeum finding generalised: 24/24 can't prove 0.95; 73 cases can, with zero misses.
2. **`evalcore.gates`**:
   - `Gate` and `decide(min_n)`, gating on the pessimistic bound, where below `min_n` a gate can FAIL but never PASS;
   - `compute_gates(records, suites, config)`, the robustness gap and the SLO gates;
   - `optional_gates`, and the judge dependency.
   
   The `config` is an explicit frozen dataclass: `confidence`, `iterations`, `seed`, `min_cases`, `gate_on_ci_bound`, `regression_tolerance`.
3. **`evalcore.verdict`**: `verdict(gates, regressions, outcomes)`. The precedence is INVALID > REJECTED > NOT APPROVED > APPROVED. A run with nothing connected is never APPROVED.
4. **`evalcore.baseline`**: `save_baseline` (APPROVED runs only), `compare_to_baseline`. It skips the comparison when the dataset hashes differ.
5. **`evalcore.records`**: `CaseResult`, `SuiteMetric`, `Recorder`, and `expand_variants`.
6. **`evalcore.detectors`**: canaries, configurable patterns, and citations (extract, fabricated, support); recall@k, MRR, abstention.
7. **`evalcore.calibration`**: ECE, Brier, AUC, worst-subgroup, PSI drift.
8. **`evalcore.judges`**: the `Judge` protocol, `LexicalJudge`, `LLMJudge(complete)`, and `calibrate_judge(judge, labelled_items)` returning agreement, CI, kappa and disagreements. `LLMJudge` takes any `complete(prompt)` callable, so it works with a local model (llama.cpp) or any API; the core names no vendor.
9. **`evalcore.efficacy`** (new, the part that shows how well each tool works):
   - `Fault` (a named wrapper that makes a system misbehave in a known way);
   - `run_fault_matrix(tools, faults, healthy)` returns, for each tool, the **catch rate** on each fault and the **false-alarm rate** on the healthy system, each with a Wilson CI, plus the **CI coverage** of the bootstrap on synthetic data with a known mean.
   
   Its output is a JSON block (`efficacy`) inside the results file, for the dashboard.
10. **`evalcore.run`**: a plain-Python front end with no pytest. `Evaluation(config).record(...)`, then `.finish()` returns the gates, verdict and artifacts. A small CLI is optional:
    - `evalcore report results.json` writes the HTML report;
    - `evalcore n-needed --threshold 0.95 --misses 1` answers the sizing question.
11. **`evalcore.artifacts`**: the results JSON (**schema v2 exactly**, so evalgate's existing viewer reads it unchanged), the eval card, the HTML report, and a static **dashboard generator**: run history, trends, and the tool-efficacy cards and fault matrix from the evalgate proposal §5. The viewer HTML moves into `evalcore` as package data; evalgate then uses it from there.

**Invariants carried over unchanged:**
- never over-claim (missing data is never PASS);
- gate on the pessimistic bound;
- resample cases, not samples;
- minimum evidence;
- judge-scored metrics need a validated judge;
- verdict precedence;
- baselines only from APPROVED runs.

New invariant: **no global state.**

## 4. How projects use it

Three ways, from least to most framework:

```python
# 1. Just the tools (any project, any test runner)
from evalcore.stats import wilson_ci, required_n
from evalcore.judges import calibrate_judge
lo, hi = wilson_ci(45, 48)                      # -> (0.83, 0.98): 45/48 does not prove 0.95
n = required_n(misses=1, threshold=0.95)        # -> 110

# 2. A whole evaluation, no pytest
from evalcore import Evaluation, Suite, GateSpec, Config
ev = Evaluation(Config(min_cases=30), suites=[Suite("summaries", per_case_gates=[GateSpec("accuracy", ">=", 0.9)])])
for case in golden:
    ev.record(case_result(case, system(case.input)))
result = ev.finish(out_dir="eval_out")          # gates, verdict, eval_results.json, EVAL_CARD.md, report.html

# 3. pytest: evalgate, rebuilt on evalcore (unchanged for its users)
```

## 5. Proving it is general

The toolkit counts as done only when it is proven outside evalgate's own domain. Three consumers, each deliberately different:

| Consumer | Kind of system | What it proves |
|---|---|---|
| **evalgate, rebased on `evalcore`** | pytest, text-to-SQL, RAG, scoring | Nothing changed for existing users: `check_demo_expectations.py` passes **with identical numbers** (90 passed, REJECTED; execution accuracy 0.958, robustness gap 0.125, RAG correctness 0.695, ROC-AUC 0.956, ECE 0.012, Brier 0.083, judge agreement 0.875) |
| **Athenaeum** | multi-agent deliberation, no pytest dependency in its core | The evalgate-integration proposal gets lighter: Athenaeum can depend on `evalcore` (numpy only) instead of the full evalgate stack (D13 would be revisited) |
| **A third, unrelated project**, chosen by the owner (X4) | something neither LLM nor RAG, for example a CLI tool's latency and correctness, or a classifier | The plain-Python front end, SLO and regression gates, and the dashboard work with no LLM concepts at all |

## 6. Phases

Each phase ends with its tests green, a commit and push, and updated docs (the new repo gets `progress.md`, `CLAUDE.md` and `HANDOFF.md` from the start, following evalgate's own conventions).

| Phase | Scope | Done when |
|---|---|---|
| **E1: stats, gates, verdict** | New repo; `stats`, `gates`, `verdict`, `baseline`, `records`; explicit `Config`; `required_n`, `min_detectable_effect`. | **Differential tests against evalgate:** on evalgate's self-test vectors, and on 1,000 random inputs, the core gives identical results (same seed, same numpy RNG). A test proves 24/24 cannot PASS a 0.95 gate. Only numpy is imported. |
| **E2: detectors, judges, calibration** | `detectors`, `judges` (with `calibrate_judge`), `calibration`; pure-numpy kappa and AUC. | Each detector has a known-bad self-test that it catches, and a known-good one it doesn't flag. Kappa and AUC match scikit-learn to 1e-12 on random data, checked in development only (scikit-learn is a dev dependency, never a runtime one). |
| **E3: artifacts** | results JSON v2, eval card, report, `evalcore.run.Evaluation`, minimal CLI. | evalgate's viewer loads a core-written results file with no changes. The card lists only checks that ran (self-test with a suite that didn't run). |
| **E4: efficacy and dashboard** | `efficacy` (faults, matrix, false alarms, CI coverage); the static dashboard generator. | On built-in synthetic faults, every tool's card shows a measured catch rate with a CI. Disabling one detector visibly drops its catch rate. The page works at phone width, in light and dark themes. |
| **E5: evalgate on the core** | In the **evalgate repo**, under its change protocol: replace its generic modules with imports from `evalcore`, keeping its pytest front end, suites and demo. | `scripts/verify.sh` passes and `check_demo_expectations.py` passes with identical values. evalgate's CI passes on Python 3.10–3.12. |
| **E6: the unrelated pilot, and Athenaeum** | The third consumer (X4), then Athenaeum's evaluation built on the core (per the revised evalgate-integration proposal). | Each produces an honest verdict and a dashboard page. The third project needs no LLM-specific code. |

## 7. Decisions needed from the owner

| # | Decision | Options | Recommendation |
|---|---|---|---|
| X1 | Name | `evalcore`; `evalgate-core`; something else | `evalcore` (short; says what it is) |
| X2 | Where it lives | (a) a new private repo `petsan/evalcore`; (b) a subpackage inside the evalgate repo | **(a)**: a separate repo is what makes it reusable elsewhere. Creating it is an outward action, so the owner creates the repo or approves it |
| X3 | License | evalgate has **no LICENSE file**; Athenaeum is proprietary (Piorun, Inc.) | Owner's call. Decide before the first commit, since the code moves out of evalgate |
| X4 | The third, unrelated pilot project | owner's choice | A small non-LLM project of the owner's |
| X5 | Rebase evalgate onto the core (E5) | (a) yes, so there is one engine; (b) no, keep two copies | **(a)**, gated on identical demo numbers |
| X6 | Dependency | numpy only (exact parity with evalgate's bootstrap); or pure stdlib (thinner, but bootstrap numbers differ from evalgate's, so E5 can't prove "identical") | **numpy only** |
| X7 | Relationship to the evalgate-integration proposal | Athenaeum uses `evalcore` directly (lighter) or full evalgate (pytest front end) | Decide after E1–E3; it doesn't block starting |

## 8. Risks

- **Silent behaviour change when extracting.** This is the main risk. The differential tests (E1) and evalgate's pinned demo numbers (E5) are there to catch it.
- **Scope creep back to a framework.** Guarded by §1's hard requirements: a test asserts the only third-party import is numpy.
- **The efficacy numbers being mistaken for real-system numbers.** Seeded-fault results are always labelled as such in the JSON and on the page.
- **Two repos to keep in step.** evalgate pins an `evalcore` version, and the change protocol in both repos says so.
