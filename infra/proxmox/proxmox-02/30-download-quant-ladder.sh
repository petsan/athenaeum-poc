#!/usr/bin/env bash
# Run ON proxmox-02 as root, detached:
#   setsid nohup bash 30-download-quant-ladder.sh A > /srv/models/dl-A.log 2>&1 < /dev/null &
#   setsid nohup bash 30-download-quant-ladder.sh B > /srv/models/dl-B.log 2>&1 < /dev/null &
# Two workers (A, B) so two HF streams run at once. Resumable (curl -C -), and every
# file's final size is checked against the server's Content-Length; failures are
# listed in /srv/models/dl-failures.txt. Layout: /srv/models/<model>/<quant>/<file>
# (multi-shard quants keep all shards in one directory; llama.cpp loads shard 00001).
#
# Quant ladder per model = Q3_K_M (lower), Q4_K_M, Q6_K, Q8_0 (higher). One publisher
# per model so quants are comparable: bartowski for Qwen3-Coder-Next and Llama 3.3 70B;
# lmstudio-community for Qwen3.8-27B, EXCEPT the lower quant, which only unsloth has
# (UD-Q3_K_XL, a *dynamic* quant -- a different method, so treat as confounded).
set -uo pipefail
W="${1:?worker A or B}"
ROOT=/srv/models
HF=https://huggingface.co

# model|quant|repo|path-in-repo   (path may include a subdirectory for shards)
A_LIST=(
"qwen3-coder-next|Q3_K_M|bartowski/Qwen_Qwen3-Coder-Next-GGUF|Qwen_Qwen3-Coder-Next-Q3_K_M.gguf"
"qwen3-coder-next|Q4_K_M|bartowski/Qwen_Qwen3-Coder-Next-GGUF|Qwen_Qwen3-Coder-Next-Q4_K_M.gguf"
"qwen3-coder-next|Q6_K|bartowski/Qwen_Qwen3-Coder-Next-GGUF|Qwen_Qwen3-Coder-Next-Q6_K/Qwen_Qwen3-Coder-Next-Q6_K-00001-of-00002.gguf"
"qwen3-coder-next|Q6_K|bartowski/Qwen_Qwen3-Coder-Next-GGUF|Qwen_Qwen3-Coder-Next-Q6_K/Qwen_Qwen3-Coder-Next-Q6_K-00002-of-00002.gguf"
"qwen3-coder-next|Q8_0|bartowski/Qwen_Qwen3-Coder-Next-GGUF|Qwen_Qwen3-Coder-Next-Q8_0/Qwen_Qwen3-Coder-Next-Q8_0-00001-of-00003.gguf"
"qwen3-coder-next|Q8_0|bartowski/Qwen_Qwen3-Coder-Next-GGUF|Qwen_Qwen3-Coder-Next-Q8_0/Qwen_Qwen3-Coder-Next-Q8_0-00002-of-00003.gguf"
"qwen3-coder-next|Q8_0|bartowski/Qwen_Qwen3-Coder-Next-GGUF|Qwen_Qwen3-Coder-Next-Q8_0/Qwen_Qwen3-Coder-Next-Q8_0-00003-of-00003.gguf"
)
B_LIST=(
"qwen3.8-27b|Q3_K_XL_UD|unsloth/Qwen3.8-27B-GGUF|Qwen3.8-27B-UD-Q3_K_XL.gguf"
"qwen3.8-27b|Q6_K|lmstudio-community/Qwen3.8-27B-GGUF|Qwen3.8-27B-Q6_K.gguf"
"qwen3.8-27b|Q8_0|lmstudio-community/Qwen3.8-27B-GGUF|Qwen3.8-27B-Q8_0.gguf"
"llama-3.3-70b|Q3_K_M|bartowski/Llama-3.3-70B-Instruct-GGUF|Llama-3.3-70B-Instruct-Q3_K_M.gguf"
"llama-3.3-70b|Q4_K_M|bartowski/Llama-3.3-70B-Instruct-GGUF|Llama-3.3-70B-Instruct-Q4_K_M.gguf"
"llama-3.3-70b|Q6_K|bartowski/Llama-3.3-70B-Instruct-GGUF|Llama-3.3-70B-Instruct-Q6_K/Llama-3.3-70B-Instruct-Q6_K-00001-of-00002.gguf"
"llama-3.3-70b|Q6_K|bartowski/Llama-3.3-70B-Instruct-GGUF|Llama-3.3-70B-Instruct-Q6_K/Llama-3.3-70B-Instruct-Q6_K-00002-of-00002.gguf"
"llama-3.3-70b|Q8_0|bartowski/Llama-3.3-70B-Instruct-GGUF|Llama-3.3-70B-Instruct-Q8_0/Llama-3.3-70B-Instruct-Q8_0-00001-of-00002.gguf"
"llama-3.3-70b|Q8_0|bartowski/Llama-3.3-70B-Instruct-GGUF|Llama-3.3-70B-Instruct-Q8_0/Llama-3.3-70B-Instruct-Q8_0-00002-of-00002.gguf"
)
eval "LIST=(\"\${${W}_LIST[@]}\")"
for e in "${LIST[@]}"; do
    IFS='|' read -r model quant repo path <<<"$e"
    dir="$ROOT/$model/$quant"; mkdir -p "$dir"
    f="$dir/$(basename "$path")"; url="$HF/$repo/resolve/main/$path"
    want=$(curl -sIL "$url" | tr -d '\r' | awk 'tolower($1)=="content-length:"{v=$2} END{print v}')
    echo "[$(date +%T)] $model/$quant $(basename "$path") want=$want"
    for try in 1 2 3; do
        curl -fL -C - --retry 5 -sS -o "$f" "$url" && break
        echo "  retry $try"; sleep 10
    done
    have=$(stat -c %s "$f" 2>/dev/null || echo 0)
    if [ -n "$want" ] && [ "$have" = "$want" ]; then echo "  OK $have"; else echo "  FAIL have=$have want=$want"; echo "$model/$quant $path have=$have want=$want" >> "$ROOT/dl-failures.txt"; fi
done
echo "[$(date +%T)] worker $W finished"
