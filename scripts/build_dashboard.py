"""Measure Athenaeum's evaluation tools (the fault matrix) and build the dashboard.

    python scripts/build_dashboard.py [--runs evals/runs] [--out evals/out/dashboard]
                                      [--efficacy FILE | --trials 100]

Without --efficacy, the fault matrix is measured afresh (a few minutes) and
saved next to the page as efficacy.json. The page is one static HTML file
with no scripts: every tool's catch and false-alarm rates, the matrix, and
the history of the release evaluations found under --runs.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from evalcore.dashboard import load_runs, render_dashboard  # noqa: E402

from athenaeum_evals import faults, runner  # noqa: E402

TITLE = "Athenaeum evaluation dashboard"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--runs", type=Path, nargs="*", default=[runner.ROOT / "evals" / "runs"])
    p.add_argument("--out", type=Path, default=runner.ROOT / "evals" / "out" / "dashboard")
    p.add_argument("--efficacy", type=Path, help="reuse a measured matrix instead of measuring it")
    p.add_argument("--trials", type=int, default=100)
    args = p.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    if args.efficacy:
        efficacy = json.loads(args.efficacy.read_text(encoding="utf-8"))
    else:
        efficacy = faults.matrix(trials=args.trials)
        (args.out / "efficacy.json").write_text(json.dumps(efficacy, indent=1), encoding="utf-8")
    runs = load_runs([r for r in args.runs if r.exists()])
    (args.out / "index.html").write_text(render_dashboard(efficacy, runs, title=TITLE), encoding="utf-8")
    print(f"wrote {args.out / 'index.html'} ({len(runs)} runs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
