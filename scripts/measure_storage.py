"""Storage growth on the API's own wiring (batch 6, Phase AB).

Every store write appends a checkpoint holding the store's FULL state
(body-design.md 5.3: append-only, never overwritten). This drives the
production path -- build_app's Maintainer, idle cycles at the default
cadence -- and reports, after every `step` answered questions, the total
on-disk size and which logs it comes from.

    ATHENAEUM_OFFLINE_MODELS=1 python scripts/measure_storage.py [questions] [step]

Per log: entries (checkpoints written), redundant entries (identical to
the one before -- a write of unchanged state), and the distinct payload
bytes the log references. Payloads are content-addressed, so identical
states are stored once; the index entry itself is still appended."""
from __future__ import annotations
import json
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from athenaeum_body.api import build_app  # noqa: E402
from athenaeum_body.storage.checkpoint import CheckpointLog  # noqa: E402

QUESTIONS = ["is {n} prime?", "how long does it take an object to fall {n} meters?",
             "should we round {n}.5 up or down?"]


def disk_bytes(root: Path) -> int:
    return sum(f.stat().st_size for f in root.rglob("*") if f.is_file())


def per_log(data_dir: Path, cas) -> dict:
    report = {}
    for index in sorted(data_dir.glob("*.txt")):
        log = CheckpointLog(cas=cas, index_path=index)
        entries = log.all_entries()
        refs = [e.payload_ref for e in entries]
        distinct = set(refs)
        report[index.stem] = {
            "entries": len(entries),
            "redundant": sum(1 for a, b in zip(refs, refs[1:]) if a == b),
            "payload_bytes": sum(cas._path_for(r).stat().st_size for r in distinct),
            "latest_state_bytes": cas._path_for(refs[-1]).stat().st_size if refs else 0,
        }
    return report


def main(total: int = 60, step: int = 20) -> dict:
    data_dir = Path(tempfile.mkdtemp(prefix="athenaeum-storage-"))
    app = build_app(data_dir)
    m, cas = app.maintainer, app.maintainer.ingestion_cas
    rows, previous = [], 0
    for i in range(1, total + 1):
        m.submit_question(f"q-{i}", QUESTIONS[i % len(QUESTIONS)].format(n=10 + i))
        m.run()
        if i % step == 0:
            size = disk_bytes(data_dir)
            rows.append({"questions": i, "idle_cycles": m.cycles, "total_bytes": size,
                         "bytes_per_question_since_last": (size - previous) // step,
                         "logs": per_log(data_dir, cas)})
            previous = size
    return {"data_dir": str(data_dir), "rows": rows}


if __name__ == "__main__":
    args = [int(a) for a in sys.argv[1:3]]
    result = main(*args)
    for row in result["rows"]:
        print(f"{row['questions']:>4} questions, {row['idle_cycles']:>3} idle cycles: "
              f"{row['total_bytes'] / 1e6:8.2f} MB total, "
              f"{row['bytes_per_question_since_last'] / 1e3:8.1f} KB per question since the last row")
    last = result["rows"][-1]["logs"]
    print("\nper log at the end (largest first):")
    for name, r in sorted(last.items(), key=lambda kv: -kv[1]["payload_bytes"])[:10]:
        print(f"  {name:<22} {r['entries']:>6} entries ({r['redundant']:>5} redundant)  "
              f"{r['payload_bytes'] / 1e6:8.2f} MB payloads, latest state {r['latest_state_bytes'] / 1e3:8.1f} KB")
    Path(result["data_dir"], "measurement.json").write_text(json.dumps(result, indent=1))
