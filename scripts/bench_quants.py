#!/usr/bin/env python3
"""Quantization-ladder benchmark runner (stdlib only; run INSIDE a GPU VM).

    python3 bench_quants.py --host proxmox02 --gpu-mem-gib 32 --ngpu 3 --ppl
    python3 bench_quants.py --host proxmox03 --gpu-mem-gib 24 --ngpu 4

For each model x quant found under /mnt/models/<model>/<quant>/ it runs, per GPU layout:
  - llama-bench: prompt processing (pp512, pp2048) and token generation (tg128), mean of 2 runs
  - with --ppl (once per combo, all GPUs): llama-perplexity on wikitext-2 test, 512-token windows
GPU layouts: "single" (CUDA_VISIBLE_DEVICES=0, only when the file fits one card with ~8% headroom for
KV/compute) and "all" (every GPU, default layer split). Results are appended as JSON lines to
/var/tmp/bench/results-<host>.jsonl; finished (model, quant, layout) rows are skipped on re-run.
Perplexity is a property of the weights, not the GPU, so it is only run on one host.
"""
import argparse, glob, json, os, re, subprocess, time

MODELS = {
    "qwen3.8-27b": ["Q3_K_XL_UD", "Q4_K_M", "Q6_K", "Q8_0"],
    "qwen3-coder-next": ["Q3_K_M", "Q4_K_M", "Q6_K", "Q8_0"],
    "llama-3.3-70b": ["Q3_K_M", "Q4_K_M", "Q6_K", "Q8_0"],
}
ROOT, BIN, OUT = "/mnt/models", "/opt/llama.cpp/build/bin", "/var/tmp/bench"
WIKI = f"{OUT}/wikitext-2-raw/wiki.test.raw"


def sh(cmd, env=None, timeout=3600):
    e = dict(os.environ, **(env or {}))
    p = subprocess.run(cmd, capture_output=True, text=True, env=e, timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def done_keys(path):
    if not os.path.exists(path):
        return set()
    return {(r["model"], r["quant"], r["layout"], r["kind"]) for r in map(json.loads, open(path)) if r.get("ok")}


def main():
    a = argparse.ArgumentParser()
    a.add_argument("--host", required=True); a.add_argument("--gpu-mem-gib", type=float, required=True)
    a.add_argument("--ngpu", type=int, required=True); a.add_argument("--ppl", action="store_true")
    a.add_argument("--models", default=""); a.add_argument("--chunks", type=int, default=64)
    a = a.parse_args()
    res = f"{OUT}/results-{a.host}.jsonl"; done = done_keys(res)
    want = [m for m in MODELS if not a.models or m in a.models.split(",")]
    for model in want:
        for quant in MODELS[model]:
            d = f"{ROOT}/{model}/{quant}"; files = sorted(glob.glob(d + "/*.gguf"))
            if not files:
                continue
            gib = sum(os.path.getsize(f) for f in files) / 2**30
            layouts = (["single"] if gib * 1.08 < a.gpu_mem_gib else []) + (["all"] if a.ngpu > 1 else [])
            for layout in layouts:
                env = {"CUDA_VISIBLE_DEVICES": "0"} if layout == "single" else {}
                if (model, quant, layout, "speed") not in done:
                    t0 = time.time()
                    rc, out, err = sh([f"{BIN}/llama-bench", "-m", files[0], "-ngl", "99", "-p", "512,2048",
                                       "-n", "128", "-r", "2", "-o", "json"], env)
                    row = dict(host=a.host, model=model, quant=quant, layout=layout, kind="speed", size_gib=round(gib, 2), ok=False)
                    if rc == 0:
                        try:
                            js = json.loads(out[out.index("["):])
                            row.update(ok=True, pp512=next(x["avg_ts"] for x in js if x["n_prompt"] == 512 and x["n_gen"] == 0),
                                       pp2048=next(x["avg_ts"] for x in js if x["n_prompt"] == 2048 and x["n_gen"] == 0),
                                       tg128=next(x["avg_ts"] for x in js if x["n_gen"] == 128 and x["n_prompt"] == 0))
                        except Exception as e:  # noqa
                            row["error"] = repr(e)[:200]
                    else:
                        row["error"] = (err or out)[-300:]
                    row["seconds"] = round(time.time() - t0)
                    open(res, "a").write(json.dumps(row) + "\n"); print(row, flush=True)
            if a.ppl and (model, quant, "all", "ppl") not in done:
                t0 = time.time()
                rc, out, err = sh([f"{BIN}/llama-perplexity", "-m", files[0], "-f", WIKI, "-c", "512", "-b", "512",
                                   "--chunks", str(a.chunks), "-ngl", "99"])
                m = re.search(r"Final estimate: PPL = ([\d.]+) \+/- ([\d.]+)", out + err)
                row = dict(host=a.host, model=model, quant=quant, layout="all", kind="ppl", size_gib=round(gib, 2),
                           ok=bool(m), ppl=float(m.group(1)) if m else None, ppl_err=float(m.group(2)) if m else None,
                           chunks=a.chunks, seconds=round(time.time() - t0))
                if not m:
                    row["error"] = (err or out)[-300:]
                open(res, "a").write(json.dumps(row) + "\n"); print(row, flush=True)
    print("ALL DONE", flush=True)


if __name__ == "__main__":
    main()
