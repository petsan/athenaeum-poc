#!/usr/bin/env python3
"""Long-context retrieval check for an OpenAI-compatible llama-server (stdlib only).

    python3 long_context_eval.py --url http://192.168.0.96:8080 --label q4 --out lc_q4.json

Builds deterministic filler documents of ~16k / 64k / 120k tokens, hides one
target sentence ("The secret access code for vault ORION is AMBER-4731.") at
10% / 50% / 90% depth together with two DECOY codes for other vaults, then
asks for the target vault's code. Graded by code: the answer must contain
the exact code and neither decoy. 9 cases per server.

Token counts are calibrated with the server's own /tokenize, and the real
prompt_tokens from the response are recorded. Needs a per-slot context of at
least ~125k (llama-server -c / -np). HONEST SCOPE: single-fact retrieval with
3 depths x 3 lengths = 9 cases, one greedy run each -- it detects gross
long-context failure, not subtle degradation.
"""
import argparse, json, random, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

ADJ = ["quiet", "ancient", "northern", "crowded", "modest", "restless", "golden", "weathered", "distant", "narrow"]
NOUN = ["harbor", "library", "orchard", "market", "bridge", "workshop", "garden", "station", "valley", "tower"]
VERB = ["recorded", "repaired", "inspected", "relocated", "catalogued", "measured", "painted", "surveyed"]
THING = ["lanterns", "ledgers", "barrels", "windows", "benches", "maps", "clocks", "baskets", "ropes", "tiles"]
PLACE = ["Aldermoor", "Brightwater", "Cinderfell", "Dunmarrow", "Eastgate", "Foxhollow", "Greywick", "Harrowdale"]
VAULTS = ["ORION", "VEGA", "LYRA", "CASTOR", "ALTAIR", "RIGEL", "DENEB", "MIRA", "SIRIUS", "POLARIS"]
CODEW = ["AMBER", "COBALT", "SAFFRON", "INDIGO", "MARBLE", "CRIMSON", "JADE", "ONYX", "IVORY", "TEAL"]


def post(url, path, body, timeout=1800):
    req = urllib.request.Request(url.rstrip("/") + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))


def sentence(rng):
    return (f"In {rng.randint(1100, 1990)}, the {rng.choice(ADJ)} {rng.choice(NOUN)} of {rng.choice(PLACE)} "
            f"{rng.choice(VERB)} {rng.randint(3, 99)} {rng.choice(THING)} near the {rng.choice(NOUN)}.")


def build_case(url, target_tokens, depth, seed, tps):
    rng = random.Random(seed)
    names = rng.sample(VAULTS, 3)
    codes = [f"{rng.choice(CODEW)}-{rng.randint(1000, 9999)}" for _ in range(3)]
    n = int(target_tokens / tps)
    sents = [sentence(rng) for _ in range(n)]
    pos = [int(n * depth)] + [int(n * d) for d in rng.sample([x for x in (0.2, 0.35, 0.65, 0.8) if abs(x - depth) > 0.1], 2)]
    for i, p in enumerate(pos):
        sents.insert(p + i, f"The secret access code for vault {names[i]} is {codes[i]}.")
    q = f"Based only on the text above, what is the secret access code for vault {names[0]}? Reply with only the code."
    return " ".join(sents) + "\n\n" + q, codes[0], codes[1:]


def run_case(url, target, depth, seed, tps):
    prompt, gold, decoys = build_case(url, target, depth, seed, tps)
    t0 = time.time()
    try:
        r = post(url, "/v1/chat/completions", {"messages": [{"role": "user", "content": prompt}], "temperature": 0,
                 "seed": 1, "max_tokens": 40, "chat_template_kwargs": {"enable_thinking": False}})
    except Exception as e:  # noqa
        return dict(target=target, depth=depth, ok=False, error=repr(e)[:200], seconds=time.time() - t0)
    ans = (r["choices"][0]["message"].get("content") or "").strip()
    ok = gold in ans and not any(d in ans for d in decoys)
    return dict(target=target, depth=depth, ok=ok, answer=ans[:80], gold=gold, prompt_tokens=r["usage"]["prompt_tokens"],
                prefill_tok_s=round(r.get("timings", {}).get("prompt_per_second", 0)), seconds=round(time.time() - t0, 1))


def main():
    a = argparse.ArgumentParser(); a.add_argument("--url", required=True); a.add_argument("--label", required=True)
    a.add_argument("--out", required=True); a.add_argument("--workers", type=int, default=2)
    a.add_argument("--targets", default="16000,64000,120000")
    a = a.parse_args()
    rng = random.Random(1)
    sample = " ".join(sentence(rng) for _ in range(300))
    tps = len(post(a.url, "/tokenize", {"content": sample})["tokens"]) / 300.0
    cases = [(int(t), d, int(t) + int(d * 100)) for t in a.targets.split(",") for d in (0.1, 0.5, 0.9)]
    t0 = time.time()
    with ThreadPoolExecutor(a.workers) as ex:
        rows = list(ex.map(lambda c: run_case(a.url, c[0], c[1], c[2], tps), cases))
    out = dict(label=a.label, url=a.url, tokens_per_sentence=tps, wall_seconds=round(time.time() - t0), rows=rows)
    json.dump(out, open(a.out, "w"), indent=1)
    print(f"== {a.label}  wall {out['wall_seconds']}s  ({tps:.1f} tok/sentence)")
    for r in rows:
        print(f"  ~{r['target'] // 1000:>3d}k depth {int(r['depth'] * 100):>2d}%  "
              + ("PASS" if r["ok"] else "FAIL") + "  "
              + (f"prompt={r['prompt_tokens']} prefill={r['prefill_tok_s']} tok/s {r['seconds']}s ans={r['answer']!r}"
                 if "error" not in r else f"ERROR {r['error']}"))
    print(f"  passed {sum(1 for r in rows if r['ok'])}/{len(rows)}")


if __name__ == "__main__":
    main()
