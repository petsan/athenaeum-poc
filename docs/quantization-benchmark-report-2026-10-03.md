# Quantization benchmark report — Qwen3.8-27B, Qwen3-Coder-Next, Llama-3.3-70B

**Date:** 2026-10-03 · **Hosts:** proxmox-02 (3× Quadro GV100 32GB) and proxmox-03 (4× Quadro M6000 24GB)
**Question:** for each model, which quantization gives the best balance of quality and speed on our hardware?

---

## 1. The short answer

| Model | Recommended quant | Why | Avoid |
|---|---|---|---|
| **Qwen3.8-27B** (dense) | **Q4_K_M** (15.7 GiB) | ~48% faster than Q8_0, only +0.2% perplexity | Q8_0 — costs speed, buys nothing; Q6_K ≈ Q8_0 in quality |
| **Qwen3-Coder-Next** (MoE) | **Q6_K** (61 GiB) for quality, **Q4_K_M** (45 GiB) when VRAM or speed matters | Q6_K shows no measurable loss and is only ~7% slower; Q4_K_M loses ~1.1% | Q3_K_M (+5.0%); Q8_0 (79 GiB, no better than Q6_K) |
| **Llama-3.3-70B** (dense) | **Q6_K** (54 GiB) | +0.4% perplexity; Q4_K_M is 38% faster but loses 4.3% | Q3_K_M (+15%, and oddly *slower* than Q4_K_M); Q8_0 (slowest, +0.4% better) |

"Acceptable" was defined as **at most about 1% perplexity loss against that model's own Q8_0**.

**Which host for what:** proxmox-02 is roughly **8–10× faster at prompt processing and 3–4× faster at generation** than proxmox-03. Use proxmox-02 for everything interactive. proxmox-03 is practical for **Qwen3-Coder-Next (25–30 tok/s)** and tolerable for Qwen3.8-27B (~8 tok/s); a 70B model there runs at about 3 tok/s and isn't useful.

---

## 2. What was measured

For every model × quant (4 quants each: Q3-class, Q4_K_M, Q6_K, Q8_0), on both hosts:

- **Speed** — `llama-bench`, mean of 2 runs: prompt processing (pp512, pp2048) and token generation (tg128), no speculative decoding. Two GPU layouts where the file fits one card: single GPU, and all GPUs (layer split).
- **Quality** — perplexity on the wikitext-2 test set (64 windows × 512 tokens), run once on proxmox-02 because it depends on the weights, not the GPU. Lower is better. Δ is relative to the same model's Q8_0.

Same llama.cpp commit (`fc07d78`) on both hosts. Models come from one publisher per ladder (bartowski for Coder-Next and Llama; lmstudio-community for Qwen3.8) so quants are comparable. **Exception:** Qwen3.8's lowest quant is unsloth's dynamic `UD-Q3_K_XL`, a different quantization method, so that row is not a like-for-like comparison.

---

## 3. Results

### 3.1 Quality (perplexity, lower is better)

| Model | Q3-class | Q4_K_M | Q6_K | Q8_0 (reference) |
|---|---|---|---|---|
| Qwen3.8-27B | 6.635 (+1.8%)* | 6.532 (+0.2%) | 6.516 (0.0%) | 6.517 |
| Qwen3-Coder-Next | 7.704 (+5.0%) | 7.417 (+1.1%) | 7.309 (−0.4%) | 7.335 |
| Llama-3.3-70B | 4.859 (+15.0%) | 4.405 (+4.3%) | 4.241 (+0.4%) | 4.225 |

\* different quantization method (see above). Differences under about 0.5% are within noise: Coder-Next's Q6_K scored *better* than its own Q8_0.

**Pattern:** the Qwen models tolerate Q4 very well; Llama-3.3-70B does not (+4.3% at Q4, +15% at Q3). Qwen3.8-27B is effectively lossless from Q4_K_M upward.

### 3.2 Speed on proxmox-02 (3× GV100) — tokens per second

| Model | Quant | Size (GiB) | Prompt (pp512) | Generation (tg128) |
|---|---|---|---|---|
| Qwen3.8-27B | Q3 (UD) | 12.2 | 697 | 30.8 |
| | Q4_K_M | 15.7 | 757 | 28.8 |
| | Q6_K | 20.9 | 811 | 22.2 |
| | Q8_0 | 27.1 | 850 | 19.5 |
| Qwen3-Coder-Next | Q3_K_M | 34.1 | 447 | 70.4 |
| | Q4_K_M | 45.4 | 416 | 79.8 |
| | Q6_K | 61.3 | 410 | 74.5 |
| | Q8_0 | 79.0 | 426 | 73.3 |
| Llama-3.3-70B | Q3_K_M | 31.9 | 327 | 10.6 |
| | Q4_K_M | 39.6 | 319 | 13.1 |
| | Q6_K | 53.9 | 284 | 9.5 |
| | Q8_0 | 69.8 | 272 | 7.9 |

(Qwen3.8-27B figures are single-GPU; the other models need several GPUs. Using all three GPUs for the 27B changed little.)

### 3.3 Speed on proxmox-03 (4× M6000, Maxwell) — tokens per second

| Model | Quant | Prompt (pp512) | Generation (tg128) |
|---|---|---|---|
| Qwen3.8-27B | Q3 (UD) / Q4_K_M / Q6_K / Q8_0 | 70 / 76 / 81 / 78 | 8.3 / 8.3 / 6.0 / 7.7 |
| Qwen3-Coder-Next | Q3_K_M / Q4_K_M / Q6_K / Q8_0 | 146 / 159 / 169 / 168 | 22.9 / 27.0 / 25.1 / 29.6 |
| Llama-3.3-70B | Q3_K_M / Q4_K_M / Q6_K / Q8_0 | 27 / 27 / 29 / 28 | 2.9 / 3.5 / 2.5 / 3.2 |

### 3.4 What the numbers say

1. **Dense models: speed tracks file size.** Generation is limited by memory bandwidth, so Qwen3.8-27B drops from 28.8 tok/s (Q4) to 19.5 (Q8) as the file grows from 15.7 to 27.1 GiB. Spending more bits only pays off if quality improves, and above Q4_K_M it doesn't for this model.
2. **The MoE model barely cares.** Qwen3-Coder-Next reads only a few experts per token, so its speed is flat (70–80 tok/s on proxmox-02) whatever the quant, and it is **faster than the dense 27B**. Since speed is nearly free, choose by quality and VRAM: Q6_K.
3. **Llama-3.3-70B is the quality-sensitive one.** Q6_K is the lowest quant that stays under ~1% loss. If you trade quality for speed, Q4_K_M gives 13.1 tok/s but costs +4.3%.
4. **Lower is not always faster.** Llama Q3_K_M (10.6) runs slower than Q4_K_M (13.1), and on proxmox-03 Qwen3.8 Q6_K (6.0) is slower than Q8_0 (7.7). These are measured but not explained; the likely cause is the cost of unpacking k-quants. Don't assume a smaller quant is faster.
5. **proxmox-03 is limited by the cards, not memory.** The M6000s lack the fast integer instructions newer cards have, so prompt processing is 8–10× slower. Single-GPU vs multi-GPU made little difference.

---

## 4. Recommended deployments

| Host | Model + quant | Expected speed | Notes |
|---|---|---|---|
| proxmox-02 | **Qwen3-Coder-Next Q6_K** | ~75 tok/s | 61 GiB across the 3 GPUs; best quality-per-speed overall |
| proxmox-02 | **Qwen3.8-27B Q4_K_M** | ~29 tok/s (about 50 with MTP speculative decoding, measured earlier) | fits one GPU |
| proxmox-02 | Llama-3.3-70B Q6_K (only if a 70B is needed) | ~9.5 tok/s | Q4_K_M if speed beats a 4% quality loss |
| proxmox-03 | **Qwen3-Coder-Next Q4_K_M** | ~27 tok/s | 45 GiB; the one model that runs well on these cards |
| proxmox-03 | Qwen3.8-27B Q4_K_M | ~8 tok/s | fine for batch work, slow for chat |
| proxmox-03 | Llama-3.3-70B | ~3 tok/s | not recommended |

---

## 5. Caveats — read before relying on this

- **Perplexity is a proxy.** It was measured on 64 short windows of one text corpus. Differences under ~0.5% are noise, and perplexity can miss damage on code, structured output or long contexts.
- **Task accuracy was tested for Qwen3.8-27B only, Q4_K_M vs Q8_0 (see 5a); the rest of the ladder has none.** Separately, on 2026-10-02 a 48-item task test and a 9-case long-context retrieval test (16k–120k tokens) found **no difference between Qwen3.8-27B Q4_K_M and Q8_0** — consistent with the perplexity result, but it covers one model and easy tasks.
- **Speed numbers are without speculative decoding** (the MTP drafter gave Qwen3.8 roughly 1.6–2.1× on proxmox-02 in earlier tests). Real servers also add overhead.
- The Qwen3.8 Q3 row uses a different quantization method, so don't read its quality gap as "Q3 vs Q4".
- Odd speed orderings (see 3.4 point 4) are unexplained. Single run set per cell; no repeat-run variance was measured for the benchmark itself (earlier concurrency tests on the same server varied by ~15% between runs).

## 5a. Harder task-accuracy eval, Qwen3.8-27B Q4_K_M vs Q8_0 (2026-10-03)

`scripts/hard_eval.py`: 60 generated items (logic puzzles, Python-trace, 8-step arithmetic chains, string-operation sequences), thinking on, answers graded by code (truth computed, never model-judged), 3 samples per item at temp 0.7 (180 graded answers per model), both models on VM 202 at the same time.

| category | Q4_K_M | Q8_0 |
|---|---|---|
| logic | 45/45 | 45/45 |
| trace | 40/45 | 39/45 |
| chain | 45/45 | 45/45 |
| strings | 37/45 | 42/45 |
| **total** | **167/180 (92.8%)** | **171/180 (95.0%)** |

12 of 60 items scored differently: Q8 better on 8, Q4 better on 4. Q8 leads mainly on strings (+5); other categories are level. Truncated answers: 2 (Q4) vs 1 (Q8); no errors. **Reading:** a 2-point gap with this sample size and an 8-vs-4 split is within noise, so it does not overturn the Q4_K_M pick, but it is also not proof of equality - strings is the one category worth re-testing. Raw: `docs/eval-results/hard-eval-2026-10-03/{q4,q8}.json`. Coder-Next and Llama were not task-tested.

## 6. Suggested next steps

1. Task-accuracy eval for Coder-Next and Llama (done for Qwen3.8-27B, 5a); re-test the strings category with more samples; add code-generation-with-execution and structured-output items.
2. If Coder-Next becomes the main workhorse, test it with speculative decoding / longer contexts on proxmox-02.
3. Decide the serving layout (which model on which host) (VM 202 servers were restarted after the benchmark).

---

*Raw data:* `docs/eval-results/quant-ladder-2026-10-03/results-proxmox0{2,3}.jsonl`, `docs/eval-results/hard-eval-2026-10-03/` · *Tools:* `scripts/bench_quants.py`, `scripts/quant_eval.py`, `scripts/long_context_eval.py`, `scripts/hard_eval.py` · *Full session notes:* `docs/progress.md` §46.
