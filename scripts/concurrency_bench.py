#!/usr/bin/env python3
"""Concurrency scaling benchmark for an OpenAI-compatible llama-server (stdlib only).

    python3 concurrency_bench.py --url http://192.168.0.96:8080 --label np3 --levels 1,2,3,4

For each level N, fires N simultaneous requests (fixed prompts, temperature 0,
thinking off, 400 max tokens), repeats `--rounds` times, and reports from the
server's own `timings`: per-request generation tok/s, combined tok/s
(total completion tokens / wall time) and the slowest request's wall time.
When N exceeds the server's slot count the extra requests queue, which shows
up as a longer slowest-request time, not a lower per-request tok/s.
"""
import argparse, json, statistics, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

PROMPTS = [
    "Write a Python function that merges overlapping intervals, with a docstring and two example calls.",
    "Explain in about 200 words how a hash table handles collisions.",
    "Return a JSON object describing a fictional user with fields id, name, email, tags (array of 4 strings) and address (object with street, city, zip).",
    "Summarize the causes of the French Revolution in five bullet points.",
]


def chat(url, prompt):
    body = {"messages": [{"role": "user", "content": prompt}], "temperature": 0, "seed": 1, "max_tokens": 400,
            "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(url.rstrip("/") + "/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    t0 = time.time()
    r = json.load(urllib.request.urlopen(req, timeout=900))
    return r, time.time() - t0


def main():
    a = argparse.ArgumentParser(); a.add_argument("--url", required=True); a.add_argument("--label", required=True)
    a.add_argument("--levels", default="1,2,3,4"); a.add_argument("--rounds", type=int, default=3)
    a = a.parse_args()
    props = json.load(urllib.request.urlopen(a.url.rstrip("/") + "/props", timeout=10))
    print(f"== {a.label} ({a.url})  slots={props.get('total_slots')}  n_ctx/slot={props.get('default_generation_settings', {}).get('n_ctx')}")
    chat(a.url, "Say hi.")  # warm-up
    for n in [int(x) for x in a.levels.split(",")]:
        per, comb, slow = [], [], []
        for _ in range(a.rounds):
            t0 = time.time()
            with ThreadPoolExecutor(n) as ex:
                res = list(ex.map(lambda i: chat(a.url, PROMPTS[i % len(PROMPTS)]), range(n)))
            wall = time.time() - t0
            per += [r["timings"]["predicted_per_second"] for r, _ in res]
            comb.append(sum(r["usage"]["completion_tokens"] for r, _ in res) / wall)
            slow.append(max(w for _, w in res))
        print(f"  N={n}: per-request {statistics.mean(per):5.1f} tok/s (min {min(per):.1f})  "
              f"combined {statistics.mean(comb):5.1f} tok/s  slowest request {statistics.mean(slow):4.1f}s")


if __name__ == "__main__":
    main()
