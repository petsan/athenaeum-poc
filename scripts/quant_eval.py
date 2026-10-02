#!/usr/bin/env python3
"""Small, deterministic quantization-comparison eval for an OpenAI-compatible
llama-server (stdlib only; no network beyond the target URL).

Why this exists: Q4_K_M and Q8_0 of the same model were being compared by
feel. This gives both the identical, seeded, auto-graded items so the
difference (or lack of one) is measured, not asserted.

    python3 quant_eval.py run --url http://192.168.0.96:8080 --label q4 --out q4.json
    python3 quant_eval.py run --url http://192.168.0.96:8080 --label q8 --out q8.json
    python3 quant_eval.py compare q4.json q8.json

Categories (all graded by code, never by a model):
  arithmetic   multi-step word problems, numeric answer, thinking ON
  classify     support-message intent, fixed label set, thinking OFF
  extract      free text -> JSON fields, per-field exact match, thinking OFF
  format       instruction/format following with programmatic checks, thinking OFF

HONEST SCOPE: ~48 items, one greedy run each. A difference of a few items is
inside noise; the report prints counts and disagreements, not a verdict.
It is NOT a measure of general quality, only of these four narrow skills.
"""
from __future__ import annotations
import argparse, json, random, re, sys, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

SEED = 20261002
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


# ---------------------------------------------------------------- items ----

def _arithmetic(rng):
    items = []
    for _ in range(3):  # change
        a, b = rng.randint(2, 9), rng.randint(3, 12)
        x, y = rng.randint(2, 6), rng.randint(1, 4)
        total = a * x + b * y
        while total >= 100:
            x -= 1; total = a * x + b * y
        items.append((f"A shop sells pens at ${a} each and notebooks at ${b} each. Maria buys {x} pens "
                      f"and {y} notebooks and pays with a $100 bill. How many dollars of change does she get? "
                      f"End your answer with 'ANSWER: <number>'.", 100 - total))
    for _ in range(3):  # percent (integer by construction: p=100k, a,b multiples of 10)
        k, a, b = rng.randint(2, 9), rng.choice([10, 20, 30, 40]), rng.choice([10, 20, 30, 50])
        m, n = 10 - a // 10, 10 + b // 10
        items.append((f"An item costs ${100 * k}. It is discounted by {a}%, and then the discounted price is "
                      f"increased by {b}%. What is the final price in dollars? "
                      f"End your answer with 'ANSWER: <number>'.", k * m * n))
    for _ in range(3):  # age
        y, n, k = rng.randint(4, 15), rng.randint(2, 4), rng.randint(2, 6)
        x = n * y
        items.append((f"Tom is {n} times as old as his daughter. In {k} years, the sum of their ages will be "
                      f"{x + y + 2 * k}. How old is the daughter now? End your answer with 'ANSWER: <number>'.", y))
    for _ in range(3):  # divisible count
        lo = rng.randint(10, 200); hi = lo + rng.randint(150, 600); m = rng.choice([7, 9, 11, 13])
        cnt = hi // m - (lo - 1) // m
        items.append((f"How many integers from {lo} to {hi}, inclusive, are divisible by {m}? "
                      f"End your answer with 'ANSWER: <number>'.", cnt))
    return [("arithmetic", p, str(a), {"think": True, "max_tokens": 6000}) for p, a in items]


CLASSIFY_LABELS = ["billing", "technical", "shipping", "account", "other"]
CLASSIFY_ITEMS = [
    ("I was charged twice for my order this month, please refund one.", "billing"),
    ("Why did my card get billed $49 when my plan is $29?", "billing"),
    ("Can I get an invoice for last quarter's payments?", "billing"),
    ("The app crashes every time I open the settings page.", "technical"),
    ("I get a 500 error when I try to upload a PDF.", "technical"),
    ("The website is extremely slow and keeps timing out for me.", "technical"),
    ("My package was supposed to arrive Tuesday and it still hasn't shown up.", "shipping"),
    ("The tracking page says delivered but nothing is at my door.", "shipping"),
    ("Can you change the delivery address for the parcel that's in transit?", "shipping"),
    ("I forgot my password and the reset email never arrives.", "account"),
    ("Please delete my account and all my data.", "account"),
    ("How do I change the email address on my profile?", "account"),
    ("Do you have any plans to open an office in Berlin?", "other"),
    ("Just wanted to say your support team was lovely, thanks!", "other"),
    ("Is your company hiring a data analyst?", "other"),
    ("My invoice shows the wrong company name and the app won't let me edit it.", "billing"),
]


def _classify():
    out = []
    for text, label in CLASSIFY_ITEMS:
        prompt = ("Classify the customer message into exactly one of these labels: "
                  + ", ".join(CLASSIFY_LABELS) + ".\nReply with only the label, lowercase, nothing else.\n\n"
                  f"Message: {text}")
        out.append(("classify", prompt, label, {"think": False, "max_tokens": 200}))
    return out


def _extract(rng):
    origins = ["Boston", "Denver", "Seattle", "Austin", "Miami", "Chicago", "Portland", "Atlanta"]
    names = ["Priya Natarajan", "Tomás Ortega", "Hannah Weiss", "Kwame Mensah", "Li Wei", "Sofia Rossi"]
    items = []
    for i in range(12):
        o, d = rng.sample(origins, 2)
        yr, mo, dy = 2027, rng.randint(1, 12), rng.randint(1, 28)
        n, price, name = rng.randint(1, 6), rng.choice([150, 200, 275, 320, 450, 600]), rng.choice(names)
        suffix = "th" if 10 <= dy % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(dy % 10, "th")
        if i % 2:
            when = f"{MONTHS[mo - 1]} {dy}{suffix}, {yr}"
        else:
            when = f"{dy} {MONTHS[mo - 1]} {yr}"
        text = (f"Hi there! I'd like {n} seat{'s' if n > 1 else ''} from {o} to {d} on {when}, "
                f"and I can't go above ${price} per ticket. The booking is under {name}. Thanks!")
        gold = {"origin": o, "destination": d, "date": f"{yr:04d}-{mo:02d}-{dy:02d}",
                "passengers": n, "max_price": price, "name": name}
        prompt = ("Extract the booking request as JSON with exactly these keys: origin, destination, "
                  "date (YYYY-MM-DD), passengers (integer), max_price (integer, dollars), name. "
                  "Reply with only the JSON object.\n\n" + text)
        items.append(("extract", prompt, json.dumps(gold), {"think": False, "max_tokens": 400}))
    return items


def _format():
    return [
        ("format", "Reply with exactly three words and nothing else.", "words3", {"think": False, "max_tokens": 100}),
        ("format", "Reply with only YES or NO in capitals: is 91 a prime number?", "NO", {"think": False, "max_tokens": 100}),
        ("format", "Output a JSON array containing the first five prime numbers and nothing else.", "[2, 3, 5, 7, 11]", {"think": False, "max_tokens": 200}),
        ("format", "List exactly three colors, one per line, with no numbering, bullets, or other text.", "lines3", {"think": False, "max_tokens": 100}),
        ("format", "Answer in all lowercase letters with no punctuation: what is the capital of France?", "lower_paris", {"think": False, "max_tokens": 100}),
        ("format", "Reply with only the digits of the answer: what is 12 times 12?", "144", {"think": False, "max_tokens": 100}),
        ("format", "Reply with only the word banana, in uppercase.", "BANANA", {"think": False, "max_tokens": 100}),
        ("format", "Write one sentence of exactly eight words about autumn. Reply with only the sentence.", "words8", {"think": False, "max_tokens": 150}),
    ]


def build_items():
    rng = random.Random(SEED)
    items = _arithmetic(rng) + _classify() + _extract(rng) + _format()
    return [dict(id=i, category=c, prompt=p, expected=e, opts=o) for i, (c, p, e, o) in enumerate(items)]


# -------------------------------------------------------------- grading ----

def _json_from(text):
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S).strip()
    for cand in (t, t[t.find("{"): t.rfind("}") + 1], t[t.find("["): t.rfind("]") + 1]):
        try:
            return json.loads(cand)
        except Exception:
            pass
    return None


def grade(item, text):
    """Returns (score 0..1, detail). Score is fraction of correct fields for extract, else 0/1."""
    cat, exp, t = item["category"], item["expected"], (text or "").strip()
    if cat == "arithmetic":
        m = re.findall(r"ANSWER:\s*\$?(-?[\d,]+(?:\.\d+)?)", t)
        got = m[-1].replace(",", "") if m else None
        return (1.0 if got is not None and float(got) == float(exp) else 0.0), f"got={got}"
    if cat == "classify":
        got = re.sub(r"[^a-z]", "", t.lower())
        return (1.0 if got == exp else 0.0), f"got={got!r}"
    if cat == "extract":
        obj, gold = _json_from(t), json.loads(exp)
        if not isinstance(obj, dict):
            return 0.0, "invalid-json"
        ok = sum(1 for k, v in gold.items() if obj.get(k) == v or str(obj.get(k)) == str(v))
        return ok / len(gold), "fields=%d/%d" % (ok, len(gold))
    # format
    lines = [l for l in t.splitlines() if l.strip()]
    if exp == "words3":
        ok = len(t.split()) == 3
    elif exp == "words8":
        ok = len(t.split()) == 8 and "\n" not in t
    elif exp == "lines3":
        ok = len(lines) == 3 and all(re.fullmatch(r"[A-Za-z ]+", l.strip()) for l in lines)
    elif exp == "lower_paris":
        ok = "paris" in t and t == t.lower() and not re.search(r"[^\w\s]", t)
    elif exp == "[2, 3, 5, 7, 11]":
        ok = _json_from(t) == [2, 3, 5, 7, 11]
    else:
        ok = t.strip(" .\"'") == exp
    return (1.0 if ok else 0.0), f"got={t[:60]!r}"


# ---------------------------------------------------------------- calls ----

def call(url, item):
    body = {"messages": [{"role": "user", "content": item["prompt"]}], "temperature": 0, "seed": 1,
            "max_tokens": item["opts"]["max_tokens"],
            "chat_template_kwargs": {"enable_thinking": bool(item["opts"]["think"])}}
    req = urllib.request.Request(url.rstrip("/") + "/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    t0 = time.time()
    try:
        r = json.load(urllib.request.urlopen(req, timeout=900))
    except (urllib.error.URLError, TimeoutError) as e:
        return dict(error=str(e), seconds=time.time() - t0)
    msg, ch = r["choices"][0]["message"], r["choices"][0]
    return dict(text=msg.get("content") or "", reasoning_chars=len(msg.get("reasoning_content") or ""),
                finish=ch.get("finish_reason"), completion_tokens=r["usage"]["completion_tokens"],
                seconds=time.time() - t0, tok_s=r.get("timings", {}).get("predicted_per_second"))


def cmd_run(a):
    items = build_items()
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        results = list(ex.map(lambda it: call(a.url, it), items))
    rows = []
    for it, r in zip(items, results):
        score, detail = grade(it, r.get("text")) if "error" not in r else (0.0, "error")
        rows.append(dict(id=it["id"], category=it["category"], expected=it["expected"], score=score,
                         detail=detail, **r))
    out = dict(label=a.label, url=a.url, seed=SEED, workers=a.workers, wall_seconds=time.time() - t0,
               rows=rows)
    json.dump(out, open(a.out, "w"), indent=1)
    summarize(out)


def summarize(d):
    cats = {}
    for r in d["rows"]:
        cats.setdefault(r["category"], []).append(r)
    print(f"== {d['label']}  (wall {d['wall_seconds']:.0f}s, workers={d['workers']})")
    tot = n = 0
    for c, rs in cats.items():
        s = sum(r["score"] for r in rs)
        tot += s; n += len(rs)
        toks = sum(r.get("completion_tokens", 0) for r in rs)
        empty = sum(1 for r in rs if not r.get("text"))
        trunc = sum(1 for r in rs if r.get("finish") == "length")
        print(f"  {c:11s} {s:5.1f}/{len(rs):<3d} ({100 * s / len(rs):5.1f}%)  tokens={toks}  empty={empty}  truncated={trunc}")
    print(f"  {'TOTAL':11s} {tot:5.1f}/{n:<3d} ({100 * tot / n:5.1f}%)")


def cmd_compare(a):
    A, B = (json.load(open(p)) for p in (a.a, a.b))
    summarize(A); summarize(B)
    print("\n== per-item disagreements (score differs)")
    diffs = 0
    for ra, rb in zip(A["rows"], B["rows"]):
        assert ra["id"] == rb["id"] and ra["expected"] == rb["expected"], "item sets differ"
        if abs(ra["score"] - rb["score"]) > 1e-9:
            diffs += 1
            print(f"  #{ra['id']:<3d} {ra['category']:10s} {A['label']}={ra['score']:.2f} ({ra['detail']})  "
                  f"{B['label']}={rb['score']:.2f} ({rb['detail']})  expected={str(ra['expected'])[:50]}")
    print(f"  {diffs} of {len(A['rows'])} items differ")
    same = sum(1 for ra, rb in zip(A['rows'], B['rows']) if ra.get('text') == rb.get('text'))
    print(f"  byte-identical responses: {same} of {len(A['rows'])}")
    print("\nNOTE: ~48 items, one greedy run each; differences of a few items are within noise.")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("--url", required=True); r.add_argument("--label", required=True)
    r.add_argument("--out", required=True); r.add_argument("--workers", type=int, default=2)
    r.set_defaults(fn=cmd_run)
    c = sub.add_parser("compare"); c.add_argument("a"); c.add_argument("b"); c.set_defaults(fn=cmd_compare)
    a = p.parse_args(); a.fn(a)


if __name__ == "__main__":
    main()
