"""Mint a reviewer token for the API's write endpoints (owner decision 7).

    python scripts/add_reviewer.py <reviewer_id> <role> [--file PATH] [--allow-host HOST ...]

Stores only the token's SHA-256 hash in the reviewers file (default
data/api-run/reviewers.json, the API's default data dir, or
$ATHENAEUM_REVIEWERS_FILE) and prints the token ONCE -- keep it; it can't be
recovered, only replaced by running this again. Roles: owner, reviewer,
member, service. Only 'reviewer' may clear checkpoints (Section 11.7);
'owner' and 'reviewer' may submit ingestion. --allow-host adds hosts to the
ingestion allow-list.

The file must never be committed: data/ is git-ignored.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from athenaeum_body.reviewers import add_reviewer, reviewers_path  # noqa: E402


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("reviewer_id")
    p.add_argument("role")
    p.add_argument("--file", type=Path, default=None)
    p.add_argument("--allow-host", action="append", default=[])
    args = p.parse_args(argv)
    path = args.file or reviewers_path(Path("data/api-run"))
    token = add_reviewer(path, args.reviewer_id, args.role, args.allow_host)
    print(f"reviewer {args.reviewer_id!r} ({args.role}) written to {path}")
    print(f"token (shown once): {token}")


if __name__ == "__main__":
    main()
