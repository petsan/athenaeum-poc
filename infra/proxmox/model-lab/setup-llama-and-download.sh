#!/usr/bin/env bash
# Installs llama.cpp (built from source -- more portable than betting on a
# specific prebuilt release asset name for this CPU) on an already-created
# guest, and runs ONE model as a systemd service on port 8080. Run once per
# guest (loop over the manifest, or call directly for a single model).
#
# Since 2026-09-27 the guest downloads nothing: models live on the host,
# in /mnt/pve/glacier-01/models/<repo name>/ (owner's decision), put there
# by download-models-to-host.sh and mounted read-only at /opt/models by
# mount-model-store.sh. So the model is served from
# /opt/models/<repo name>/<file>, and this fails early if it isn't there.
# (Before, each guest downloaded its own copy onto its own disk, and the
# 2026-09-27 pool loss took every copy with it: known-bugs.md #37.)
#
# Usage (single guest):
#   SSH_PRIVATE_KEY_PATH=~/.ssh/athenaeum_poc \
#   ./setup-llama-and-download.sh 192.168.0.160 allenai/OLMo-2-0425-1B-Instruct-GGUF olmo-2-0425-1b-instruct-q4_k_m.gguf olmo2-1b
#
# Usage (all guests in manifest.tsv):
#   SSH_PRIVATE_KEY_PATH=~/.ssh/athenaeum_poc ./setup-all.sh
#
# --no-jinja on the systemd ExecStart (real bug, found running this
# against olmo3-7b): llama-server parses/validates a model's chat
# template at STARTUP even when it's never used -- OLMo 3's template uses
# a Jinja 'tojson' filter llama.cpp's built-in minimal parser doesn't
# support, so the server crash-looped on every boot (systemd restarting
# it every ~5s, error hidden behind a generic 503 "Loading model" unless
# you check `journalctl -u llama-server`). Since every caller here only
# ever uses the raw /completion endpoint (never /v1/chat/completions),
# the chat template is never actually needed -- --no-jinja skips parsing
# it entirely. Applied to every guest's ExecStart, not just OLMo 3's,
# since any future model's template could hit the same gap.
#
# --metrics --slots --log-timestamps --log-prefix (owner, 2026-09-27: use
# real diagnostics, not curl-and-grep): /metrics is Prometheus text (tokens
# per second, requests processing and deferred, KV-cache use); /slots shows
# what each slot is doing right now; journal lines get timestamps. Use these
# to tell "slow" from "queued" from "stuck" (known-bugs #24 looked healthy
# on /health while 45x slower).
#
# --cache-ram (known-bugs.md #24, found 2026-09-26): recent llama-server
# builds keep a prompt cache in RAM that may grow to 8192 MiB by default.
# On a guest sized for its model (4-10 GB) that cache outgrows the
# container's memory limit after enough distinct prompts, swap fills, and
# the memory-mapped weights start being evicted and re-read -- the OLMo 3
# 7B guest went ~45x slower while /health still said "ok". Callers here
# send short, mostly distinct prompts, so a small cache loses almost
# nothing. LLAMA_CACHE_RAM_MIB overrides the default.
set -euo pipefail

IP="${1:?usage: setup-llama-and-download.sh IP HF_REPO HF_FILE LABEL}"
HF_REPO="${2:?}"
HF_FILE="${3:?}"
LABEL="${4:?}"
KEY="${SSH_PRIVATE_KEY_PATH:-$HOME/.ssh/athenaeum_poc}"
PORT="${LLAMA_PORT:-8080}"
CACHE_RAM_MIB="${LLAMA_CACHE_RAM_MIB:-512}"
MODEL_PATH="/opt/models/${HF_REPO##*/}/${HF_FILE}"   # the host store, mounted read-only (see top)

echo "=== $LABEL @ $IP -- installing llama.cpp to serve $HF_REPO/$HF_FILE ==="

ssh -i "$KEY" -o StrictHostKeyChecking=accept-new "root@${IP}" bash -s <<REMOTE
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

echo "--- apt deps ---"
apt-get update -qq
apt-get install -y -qq build-essential cmake git >/dev/null

if [ ! -d /opt/llama.cpp ]; then
    echo "--- cloning llama.cpp ---"
    git clone --depth 1 https://github.com/ggml-org/llama.cpp /opt/llama.cpp
fi

echo "--- building (CPU-only, this takes a few minutes) ---"
cmake -B /opt/llama.cpp/build -S /opt/llama.cpp -DCMAKE_BUILD_TYPE=Release
# only the server: the whole tree (every tool and example) is several times
# longer to build on these CPUs, and nothing else is used here
cmake --build /opt/llama.cpp/build --config Release --target llama-server -j\$(nproc)

echo "--- model, from the host's store (mounted read-only) ---"
if [ ! -r "${MODEL_PATH}" ]; then
    echo "${MODEL_PATH} is not readable. On the host, as root: model-lab/download-models-to-host.sh, then model-lab/mount-model-store.sh" >&2
    exit 1
fi
ls -l "${MODEL_PATH}"

echo "--- systemd unit ---"
cat > /etc/systemd/system/llama-server.service <<UNIT
[Unit]
Description=llama.cpp server -- ${LABEL} (Athenaeum model-lab candidate)
After=network.target

[Service]
ExecStart=/opt/llama.cpp/build/bin/llama-server --model ${MODEL_PATH} --host 0.0.0.0 --port ${PORT} -c 4096 --threads \$(nproc) --no-jinja --cache-ram ${CACHE_RAM_MIB} --metrics --slots --log-timestamps --log-prefix
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable llama-server
# restart, not "enable --now": --now leaves an already-running server on
# its OLD unit, so a changed ExecStart (new flags) silently never applied
# (found 2026-09-27: /metrics still 501 after re-running this script)
systemctl restart llama-server
sleep 2
systemctl is-active llama-server
REMOTE

echo "=== $LABEL ready: http://${IP}:${PORT} (OpenAI-compatible /v1/chat/completions + llama.cpp's own /completion) ==="
