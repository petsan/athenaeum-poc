"""Live deployment smoke (batch 9, Phase AH): drives a REAL running API
server -- real model-lab guests, no stubs -- over HTTP, and reports what a
user would experience. It reports rather than gates: live-model output
isn't deterministic, so the only hard failures are an unreachable server,
a question that never finishes, or an error response.

    python -m athenaeum_body.api        # or serve(port=..., data_dir=...)
    python scripts/live_smoke.py [base_url] [timeout_seconds]
"""
from __future__ import annotations
import json
import statistics
import sys
import threading
import time
import urllib.request

ASYNC_QUESTIONS = [
    "is 97 prime?",                              # deterministic agents
    "how should we round 2.5?",                  # deterministic, plural answer
    "what force holds the moon in orbit?",       # only a model can answer
    "why do objects fall when dropped?",         # model-backed Physics
]
SYNC_QUESTION = "is 91 prime?"


def call(base: str, path: str, payload=None, timeout=900):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(base + path, data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json"})
    start = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return time.time() - start, r.status, json.loads(r.read())


def main(base: str = "http://127.0.0.1:8080", timeout: float = 900) -> dict:
    _, _, health = call(base, "/api/health")
    report = {"health_at_start": health, "submitted": {}, "polls": [], "problems": []}
    started = time.time()
    for q in ASYNC_QUESTIONS:
        _, status, body = call(base, "/api/questions", {"question": q, "async": True})
        report["submitted"][body["id"]] = {"question": q, "at": time.time() - started}

    # a synchronous question alongside, in its own thread: it waits for the
    # worker's lock between rounds, while the polls below carry on
    def ask_sync():
        sync_elapsed, status, sync_body = call(base, "/api/questions", {"question": SYNC_QUESTION})
        report["sync"] = {"seconds": round(sync_elapsed, 2), "status": status,
                          "committed": [c["statement"] for c in sync_body.get("answer", {}).get("committed", [])]}
    sync_thread = threading.Thread(target=ask_sync)
    sync_thread.start()

    done_at = {}
    while time.time() - started < timeout:
        elapsed, _, summary = call(base, "/api/questions?view=summary")
        _, _, h = call(base, "/api/health")
        report["polls"].append({"seconds": elapsed, "queued": h["queued_units"]})
        for s in summary:
            if s["id"] in report["submitted"] and s["status"] in ("completed", "suspended") and s["id"] not in done_at:
                done_at[s["id"]] = time.time() - started
        if len(done_at) == len(report["submitted"]):
            break
        time.sleep(0.5)
    else:
        report["problems"].append(f"not all questions finished within {timeout}s")
    sync_thread.join(timeout=timeout)
    if "sync" not in report:
        report["problems"].append("the synchronous question never returned")
        report["sync"] = {"seconds": None, "status": None, "committed": []}

    for qid, info in report["submitted"].items():
        _, _, entry = call(base, f"/api/questions/{qid}")
        latest = entry["versions"][-1] if entry["versions"] else {}
        info.update(status=entry["status"], finished_after=round(done_at.get(qid, -1), 1),
                    committed=[f"{c['issuing_agent']}: {c['statement']}" for c in latest.get("committed", [])],
                    error=entry.get("error"))
        if entry["status"] != "completed":
            report["problems"].append(f"{qid} ended {entry['status']}: {entry.get('error')}")
    busy = [p["seconds"] for p in report["polls"] if p["queued"]]
    report["poll_latency"] = {
        "polls": len(report["polls"]),
        "max_s": round(max(p["seconds"] for p in report["polls"]), 3) if report["polls"] else None,
        "median_s": round(statistics.median(p["seconds"] for p in report["polls"]), 4) if report["polls"] else None,
        "max_while_work_queued_s": round(max(busy), 3) if busy else None,
    }
    report["health_at_end"] = call(base, "/api/health")[2]
    report["events"] = call(base, "/api/maintenance")[2]["recent_events"]
    return report


if __name__ == "__main__":
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8080"
    timeout = float(sys.argv[2]) if len(sys.argv) > 2 else 900
    r = main(base, timeout)
    print(f"sync '{SYNC_QUESTION}': {r['sync']['seconds']}s -> {r['sync']['committed']}")
    for qid, info in r["submitted"].items():
        print(f"{qid} '{info['question']}': {info['status']} after {info['finished_after']}s")
        for c in info["committed"]:
            print(f"    {c[:140]}")
    print("poll latency:", r["poll_latency"])
    print("health at end:", r["health_at_end"]["worker"], "queued", r["health_at_end"]["queued_units"])
    print("events:", [e.get("question_id") or e.get("cycle_id") or e.get("kind") for e in r["events"]])
    print("problems:", r["problems"] or "none")
    sys.exit(1 if r["problems"] else 0)
