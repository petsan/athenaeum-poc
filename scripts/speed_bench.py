#!/usr/bin/env python3
"""Speed benchmark for an OpenAI-compatible llama-server (stdlib only).

    python3 speed_bench.py --url http://192.168.0.96:8080 --label q4

Reports, from the server's own `timings` block (not wall-clock guesses):
  - single-stream generation tok/s over 4 fixed prompts (temperature 0, thinking off)
  - draft acceptance when speculative decoding is on
  - 2 concurrent requests: per-request tok/s and combined tok/s
  - prompt-processing (prefill) tok/s on a ~6k-token prompt
"""
import argparse, json, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

PROMPTS = [
    "Write a Python function that merges overlapping intervals, with a docstring and two example calls.",
    "Explain in about 200 words how a hash table handles collisions.",
    "Return a JSON object describing a fictional user with fields id, name, email, tags (array of 4 strings) and address (object with street, city, zip).",
    "Summarize the causes of the French Revolution in five bullet points.",
]


def chat(url, prompt, max_tokens=400):
    body = {"messages": [{"role": "user", "content": prompt}], "temperature": 0, "seed": 1,
            "max_tokens": max_tokens, "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(url.rstrip("/") + "/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    t0 = time.time()
    r = json.load(urllib.request.urlopen(req, timeout=900))
    r["_wall"] = time.time() - t0
    return r


def main():
    a = argparse.ArgumentParser(); a.add_argument("--url", required=True); a.add_argument("--label", required=True)
    a = a.parse_args()
    print(f"== {a.label} ({a.url})")
    chat(a.url, "Say hi.", 8)  # warm-up
    rates, acc = [], []
    for p in PROMPTS:
        r = chat(a.url, p); t = r.get("timings", {})
        rates.append(t.get("predicted_per_second", 0))
        if t.get("draft_n"):
            acc.append(t["draft_n_accepted"] / t["draft_n"])
    print(f"  single-stream: {[round(x, 1) for x in rates]}  mean {sum(rates) / len(rates):.1f} tok/s"
          + (f"  draft acceptance mean {100 * sum(acc) / len(acc):.0f}%" if acc else ""))
    t0 = time.time()
    with ThreadPoolExecutor(2) as ex:
        rs = list(ex.map(lambda p: chat(a.url, p), PROMPTS[:2]))
    wall = time.time() - t0
    toks = sum(r["usage"]["completion_tokens"] for r in rs)
    per = [round(r["timings"]["predicted_per_second"], 1) for r in rs]
    print(f"  2 concurrent: per-request {per} tok/s, combined {toks / wall:.1f} tok/s (wall {wall:.1f}s)")
    filler = " ".join(f"Record {i}: the archive logged routine event number {i} without incident." for i in range(450))
    r = chat(a.url, filler + "\n\nSay only the word OK.", 8); t = r["timings"]
    print(f"  prefill: {r['usage']['prompt_tokens']} prompt tokens at {t['prompt_per_second']:.0f} tok/s")


if __name__ == "__main__":
    main()
