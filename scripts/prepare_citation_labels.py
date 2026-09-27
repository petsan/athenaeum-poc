"""Prepare the owner's labelling file for citation support (decision D17).

    python scripts/prepare_citation_labels.py [RESULTS] [--out evals/labelling/citation_support.json]

RESULTS is an evaluation's eval_results.json (default: the newest under
evals/runs/). Every model-backed claim the deliberation suite committed
becomes an item: the question, the model's answer as committed, and a
`label` for the owner to set to true (a correct, supported answer) or false.
Running it again adds new claims and never touches an item already there,
so labels are never lost. The judge-scored gate needs at least 30 labels.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from evalcore.records import CaseResult  # noqa: E402

from athenaeum_evals import deliberation, provenance, runner  # noqa: E402

HOW = ("For each item, set label to true if the claim answers the question correctly, or false if not; "
       "add a note if it is unclear. The citation-support gate stays withheld until a judge is validated "
       "against at least 30 labels (D17).")


def newest_results(root: Path) -> Path:
    found = sorted((root / "evals" / "runs").glob("*/eval_results.json"))
    if not found:
        raise SystemExit("no evaluation runs under evals/runs/; pass a results file")
    return found[-1]


def merge(existing: dict | None, new_items: list[dict], source: str) -> dict:
    items = list((existing or {}).get("items", []))
    seen = {(i["question"], i["claim"]) for i in items}
    for item in new_items:
        if (item["question"], item["claim"]) not in seen:
            seen.add((item["question"], item["claim"]))
            items.append({**item, "id": f"cs-{len(items) + 1:03d}", "from": source})
    return {"about": HOW, "items": items}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("results", type=Path, nargs="?")
    p.add_argument("--out", type=Path, default=provenance.LABELS)
    args = p.parse_args(argv)
    path = args.results or newest_results(runner.ROOT)
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = [CaseResult(**{k: r[k] for k in ("suite", "case_id", "category", "variant", "run")}, detail=r.get("detail", {}))
             for r in data.get("results", []) if r.get("suite") == deliberation.KEY]
    existing = json.loads(args.out.read_text(encoding="utf-8")) if args.out.exists() else None
    merged = merge(existing, provenance.labelling_items(cases), path.parent.name)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(merged, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    labelled = sum(1 for i in merged["items"] if i.get("label") is not None)
    print(f"{args.out}: {len(merged['items'])} items, {labelled} labelled")
    return 0


if __name__ == "__main__":
    sys.exit(main())
