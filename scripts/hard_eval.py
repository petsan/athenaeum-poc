#!/usr/bin/env python3
"""Harder deterministic eval for quantization comparison (stdlib only; companion to quant_eval.py).

    python3 hard_eval.py run --url http://127.0.0.1:8080 --label q4 --out q4.json [--samples 3 --temp 0.7]
    python3 hard_eval.py compare q4.json q8.json

60 items, thinking ON, answer-graded by code (truth is computed, never model-judged):
  logic    5-person ordering puzzles, constraints added until the solution is unique
  trace    random Python programs (loops, dicts, sorting); truth via exec
  chain    8-step integer arithmetic with //, %, squaring; truth via eval
  strings  sequences of string operations on a random word
Scope: still small; with --samples N each item is sampled N times (temp>0) so noise is visible.
"""
from __future__ import annotations
import argparse, contextlib, io, itertools, json, random, re, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

SEED = 20261003
NAMES = ["Ana", "Ben", "Cleo", "Dev", "Eli", "Fay", "Gus"]
SUFFIX = "\n\nThink it through, then end with a final line exactly of the form `ANSWER: <answer>`."


def _holds(perm, c):
    pp = {p: i + 1 for i, p in enumerate(perm)}
    k, a, b = c
    return {"left": lambda: pp[a] < pp[b], "adj": lambda: abs(pp[a] - pp[b]) == 1,
            "notend": lambda: pp[a] not in (1, 5), "notpos": lambda: pp[a] != b}[k]()


def _clue(c):
    k, a, b = c
    return {"left": f"{a} is somewhere before {b}.", "adj": f"{a} and {b} are in adjacent positions.",
            "notend": f"{a} is not in position 1 or 5.", "notpos": f"{a} is not in position {b}."}[k]


def logic(rng):
    people = rng.sample(NAMES, 5)
    sol = people[:]
    rng.shuffle(sol)
    alive = list(itertools.permutations(people))
    cons = []
    while len(alive) > 1:
        k = rng.choice(["left", "adj", "left", "adj", "notend", "notpos"])
        a, b = rng.sample(people, 2)
        c = (k, a, b if k in ("left", "adj") else rng.randint(1, 5))
        if not _holds(sol, c):
            continue
        nxt = [p for p in alive if _holds(p, c)]
        if len(nxt) < len(alive):
            alive = nxt
            cons.append(c)
    who = rng.choice(people)
    q = (f"Five people ({', '.join(people)}) stand in a line, positions 1 to 5. Clues:\n"
         + "\n".join(f"- {_clue(c)}" for c in cons) + f"\n\nIn which position is {who}? Answer with the number.")
    return q, str(sol.index(who) + 1)


def trace(rng):
    n, k, m = rng.randint(5, 9), rng.randint(2, 4), rng.randint(3, 7)
    code = (f"d = {{}}\nxs = list(range({n}))\nfor i, x in enumerate(xs):\n"
            f"    key = (x * {k}) % {m}\n    d[key] = d.get(key, 0) + x * i\n"
            f"ys = sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))\n"
            f"out = [a + b for a, b in ys][{rng.randint(0, 1)}:]\nprint(sum(out), len(out), out[0])")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        exec(code, {})
    return f"What does this Python program print (exactly)?\n```python\n{code}\n```", buf.getvalue().strip()


def chain(rng):
    v = rng.randint(20, 90)
    expr, steps = str(v), [f"Start with {v}."]
    for _ in range(8):
        op = rng.choice(["add", "mul", "sub", "floordiv", "mod", "sq"])
        if op == "add":
            n = rng.randint(3, 99); expr = f"({expr}+{n})"; steps.append(f"Add {n}.")
        elif op == "sub":
            n = rng.randint(3, 99); expr = f"({expr}-{n})"; steps.append(f"Subtract {n}.")
        elif op == "mul":
            n = rng.randint(2, 9); expr = f"({expr}*{n})"; steps.append(f"Multiply by {n}.")
        elif op == "floordiv":
            n = rng.randint(2, 9); expr = f"({expr}//{n})"; steps.append(f"Integer-divide (floor) by {n}.")
        elif op == "mod":
            n = rng.randint(7, 97); expr = f"({expr}%{n})"; steps.append(f"Take the remainder mod {n}.")
        else:
            expr = f"(({expr})**2)"; steps.append("Square it.")
    return ("Apply these steps in order and give the final integer (floor division rounds toward minus infinity).\n"
            + " ".join(steps)), str(eval(expr))


def strings(rng):
    w = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(rng.randint(8, 11)))
    cur, steps = w, [f'Start with the string "{w}".']
    for _ in range(5):
        op = rng.choice(["rev", "rot", "swap", "drop", "dup", "up"])
        if op == "rev":
            cur = cur[::-1]; steps.append("Reverse it.")
        elif op == "rot":
            n = rng.randint(1, 4); cur = cur[n:] + cur[:n]; steps.append(f"Move the first {n} characters to the end.")
        elif op == "swap":
            cur = "".join(cur[i + 1] + cur[i] if i + 1 < len(cur) else cur[i] for i in range(0, len(cur), 2))
            steps.append("Swap each consecutive pair of characters (positions 1-2, 3-4, ...; a leftover last character stays).")
        elif op == "drop":
            cur = cur[::2]; steps.append("Keep only the characters at odd positions (1st, 3rd, 5th, ...).")
        elif op == "dup":
            cur = cur + cur[:3]; steps.append("Append a copy of its first 3 characters.")
        else:
            cur = cur.upper(); steps.append("Uppercase it.")
    return "Apply these operations in order and give the final string.\n" + " ".join(steps), cur


def build_items():
    rng, items = random.Random(SEED), []
    for cat, fn in (("logic", logic), ("trace", trace), ("chain", chain), ("strings", strings)):
        for _ in range(15):
            q, a = fn(rng)
            items.append(dict(id=len(items), category=cat, prompt=q + SUFFIX, expected=a))
    return items


def grade(it, text):
    m = re.findall(r"ANSWER:\s*(.+)", text or "")
    got = m[-1].strip().strip("`*\"' .") if m else None
    if it["category"] == "trace" and got is not None:
        got = re.sub(r"\s+", " ", got)
    return (1.0 if got == it["expected"] else 0.0), f"got={got!r}"


def call(url, it, temp, seed):
    body = {"messages": [{"role": "user", "content": it["prompt"]}], "temperature": temp, "seed": seed,
            "max_tokens": 12000, "chat_template_kwargs": {"enable_thinking": True}}
    req = urllib.request.Request(url.rstrip("/") + "/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    t0 = time.time()
    try:
        r = json.load(urllib.request.urlopen(req, timeout=1800))
    except (urllib.error.URLError, TimeoutError) as e:
        return dict(error=str(e), seconds=time.time() - t0)
    ch = r["choices"][0]
    return dict(text=ch["message"].get("content") or "", finish=ch.get("finish_reason"),
                completion_tokens=r["usage"]["completion_tokens"], seconds=time.time() - t0)


def cmd_run(a):
    items = build_items()
    jobs = [(it, s) for it in items for s in range(a.samples)]
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        res = list(ex.map(lambda j: call(a.url, j[0], a.temp if a.samples > 1 else 0, 1 + j[1]), jobs))
    rows = []
    for (it, s), r in zip(jobs, res):
        sc, d = grade(it, r.get("text")) if "error" not in r else (0.0, "error")
        rows.append(dict(id=it["id"], sample=s, category=it["category"], expected=it["expected"],
                         score=sc, detail=d, **r))
    out = dict(label=a.label, url=a.url, seed=SEED, samples=a.samples, temp=a.temp,
               wall_seconds=time.time() - t0, rows=rows)
    json.dump(out, open(a.out, "w"), indent=1)
    summarize(out)


def summarize(d):
    print(f"== {d['label']} (wall {d['wall_seconds']:.0f}s, samples={d['samples']}, "
          f"temp={d['temp'] if d['samples'] > 1 else 0})")
    tot = n = 0
    for c in ("logic", "trace", "chain", "strings"):
        rs = [r for r in d["rows"] if r["category"] == c]
        s = sum(r["score"] for r in rs)
        tot += s; n += len(rs)
        print(f"  {c:8s} {s:5.1f}/{len(rs):<3d} ({100 * s / len(rs):5.1f}%)  "
              f"tokens={sum(r.get('completion_tokens', 0) for r in rs)}  "
              f"truncated={sum(1 for r in rs if r.get('finish') == 'length')}  "
              f"errors={sum(1 for r in rs if 'error' in r)}")
    print(f"  {'TOTAL':8s} {tot:5.1f}/{n:<3d} ({100 * tot / n:5.1f}%)")


def cmd_compare(a):
    A, B = (json.load(open(p)) for p in (a.a, a.b))
    summarize(A); summarize(B)
    pa, pb = {}, {}
    for d, p in ((A, pa), (B, pb)):
        for r in d["rows"]:
            p.setdefault(r["id"], []).append(r["score"])
    diff = [(i, sum(pa[i]), sum(pb[i])) for i in pa if sum(pa[i]) != sum(pb[i])]
    print(f"\nitems whose score differs: {len(diff)} of {len(pa)}  "
          f"({A['label']} better: {sum(1 for _, x, y in diff if x > y)}, "
          f"{B['label']} better: {sum(1 for _, x, y in diff if y > x)})")
    print("A near-even split is noise; only a lopsided one (e.g. 9-1) suggests a real gap.")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    s = p.add_subparsers(dest="cmd", required=True)
    r = s.add_parser("run")
    r.add_argument("--url", required=True); r.add_argument("--label", required=True)
    r.add_argument("--out", required=True); r.add_argument("--workers", type=int, default=2)
    r.add_argument("--samples", type=int, default=1); r.add_argument("--temp", type=float, default=0.7)
    r.set_defaults(fn=cmd_run)
    c = s.add_parser("compare")
    c.add_argument("a"); c.add_argument("b"); c.set_defaults(fn=cmd_compare)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
