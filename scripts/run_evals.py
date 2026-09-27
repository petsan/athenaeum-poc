"""Run Athenaeum's release evaluation (evalcore) and write its artifacts.

    python scripts/run_evals.py [--suites adversarial] [--out evals/out] [--save-baseline]

Exits 0 only for an APPROVED run. Needs evalcore (on LXC 104: /opt/athenaeum-venv).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from athenaeum_evals import runner  # noqa: E402


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--suites", default=",".join(runner.SUITES), help="comma-separated suite keys")
    p.add_argument("--out", type=Path, default=runner.ROOT / "evals" / "out")
    p.add_argument("--save-baseline", action="store_true")
    args = p.parse_args(argv)
    result = runner.run(args.out, [s.strip() for s in args.suites.split(",") if s.strip()],
                        save_as_baseline=args.save_baseline)
    print(f"verdict: {result.verdict.status}")
    for reason in result.verdict.reasons:
        print(f"  - {reason}")
    print(f"artifacts: {args.out}")
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
