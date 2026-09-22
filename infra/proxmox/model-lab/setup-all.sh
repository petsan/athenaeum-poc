#!/usr/bin/env bash
# Runs setup-llama-and-download.sh against every guest in manifest.tsv, in
# order. Each one takes a few minutes (build + download) -- expect this to
# run for a while for all six. Safe to re-run for just the ones that
# failed: llama.cpp build and huggingface-cli download are both
# idempotent/resumable.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

MANIFEST="${1:-manifest.tsv}"

while IFS=$'\t' read -r label vmid hostname ip mac cores mem_mb disk_gb hf_repo hf_file; do
    [[ "$label" =~ ^#.*$ || -z "$label" ]] && continue
    ./setup-llama-and-download.sh "$ip" "$hf_repo" "$hf_file" "$label"
done < "$MANIFEST"

echo "All model-lab guests set up. Quick comparison:"
echo "  for ip in $(awk -F'\t' '!/^#/ && NF {print $4}' "$MANIFEST"); do"
echo "    curl -s http://\$ip:8080/completion -d '{\"prompt\":\"Q: What is the capital of France?\\nA:\",\"n_predict\":16}' | jq -r .content"
echo "  done"
