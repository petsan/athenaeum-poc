"""Fold the owner's marks from the labelling page into citation_support.json (D17).

    python scripts/apply_citation_labels.py LABELS_DIR [--file evals/labelling/citation_support.json]

LABELS_DIR holds one JSON document per marked item, named <item id>.json,
as the labelling page stores them ({"label": true|false|null, "unsure": bool,
"note": str}); a Claude session exports them from the page's `labels`
collection. Items without a mark are left as they are, and a mark for an item
the file doesn't have is reported, never invented. The page is
https://claude.ai/artifact/5yiqY91tivAJnRvMD2dEf1 (private to the owner).
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from athenaeum_evals import provenance  # noqa: E402


def apply(labels_dir: Path, path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    by_id = {i["id"]: i for i in data["items"]}
    applied, unknown = 0, []
    for f in sorted(labels_dir.glob("*.json")):
        mark = json.loads(f.read_text(encoding="utf-8"))
        item = by_id.get(f.stem)
        if item is None:
            unknown.append(f.stem)
            continue
        label = mark.get("label")
        if label not in (True, False, None):
            raise ValueError(f"{f.name}: label must be true, false or null, not {label!r}")
        item["label"] = label
        item["note"] = mark.get("note", "") or ("unsure" if mark.get("unsure") else "")
        applied += 1
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"applied": applied, "unknown": unknown,
            "labelled": sum(1 for i in data["items"] if i.get("label") is not None), "items": len(data["items"])}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("labels_dir", type=Path)
    p.add_argument("--file", type=Path, default=provenance.LABELS)
    args = p.parse_args(argv)
    r = apply(args.labels_dir, args.file)
    print(f"{args.file}: {r['applied']} marks applied; {r['labelled']} of {r['items']} items labelled"
          + (f"; marks for unknown items ignored: {', '.join(r['unknown'])}" if r["unknown"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
