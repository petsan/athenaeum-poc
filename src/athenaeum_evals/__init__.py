"""Athenaeum's release evaluation, built on evalcore (github.com/petsan/evalcore).

Owner decision X7 (2026-09-27): Athenaeum uses evalcore directly. Each module
here is one suite: a pure `evaluate_*` function that turns Athenaeum's own
behaviour into evalcore `CaseResult`s and `SuiteMetric`s, plus the `Suite`
declaring its gates. `runner.run()` decides the verdict and writes the
artifacts (eval_results.json, EVAL_CARD.md, eval_report.html).

The plan is docs/proposals/evalgate-integration.md (with the owner's
decisions at its top); progress is docs/progress.md §107.
"""
