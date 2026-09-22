#!/usr/bin/env bash
# Installs llama.cpp (built from source -- more portable than betting on a
# specific prebuilt release asset name for this CPU) and downloads ONE
# model's GGUF onto an already-created guest, then runs it as a systemd
# service on port 8080. Run once per guest (loop over the manifest, or
# call directly for a single model).
#
# Usage (single guest):
#   SSH_PRIVATE_KEY_PATH=~/.ssh/athenaeum_poc \
#   ./setup-llama-and-download.sh 192.168.0.160 allenai/OLMo-2-0425-1B-Instruct-GGUF olmo-2-0425-1b-instruct-q4_k_m.gguf olmo2-1b
#
# Usage (all guests in manifest.tsv):
#   SSH_PRIVATE_KEY_PATH=~/.ssh/athenaeum_poc ./setup-all.sh
set -euo pipefail

IP="${1:?usage: setup-llama-and-download.sh IP HF_REPO HF_FILE LABEL}"
HF_REPO="${2:?}"
HF_FILE="${3:?}"
LABEL="${4:?}"
KEY="${SSH_PRIVATE_KEY_PATH:-$HOME/.ssh/athenaeum_poc}"
PORT="${LLAMA_PORT:-8080}"

echo "=== $LABEL @ $IP -- installing llama.cpp + downloading $HF_REPO/$HF_FILE ==="

ssh -i "$KEY" -o StrictHostKeyChecking=accept-new "root@${IP}" bash -s <<REMOTE
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

echo "--- apt deps ---"
apt-get update -qq
apt-get install -y -qq build-essential cmake git python3-pip python3-venv >/dev/null

if [ ! -d /opt/llama.cpp ]; then
    echo "--- cloning llama.cpp ---"
    git clone --depth 1 https://github.com/ggml-org/llama.cpp /opt/llama.cpp
fi

echo "--- building (CPU-only, this takes a few minutes) ---"
cmake -B /opt/llama.cpp/build -S /opt/llama.cpp -DCMAKE_BUILD_TYPE=Release
cmake --build /opt/llama.cpp/build --config Release -j\$(nproc)

echo "--- huggingface-cli ---"
pip install --break-system-packages -q -U "huggingface_hub[cli]"

echo "--- downloading ${HF_FILE} (resumable if interrupted) ---"
mkdir -p /opt/models
huggingface-cli download "${HF_REPO}" "${HF_FILE}" --local-dir /opt/models

echo "--- systemd unit ---"
cat > /etc/systemd/system/llama-server.service <<UNIT
[Unit]
Description=llama.cpp server -- ${LABEL} (Athenaeum model-lab candidate)
After=network.target

[Service]
ExecStart=/opt/llama.cpp/build/bin/llama-server --model /opt/models/${HF_FILE} --host 0.0.0.0 --port ${PORT} -c 4096 --threads \$(nproc)
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now llama-server
sleep 2
systemctl is-active llama-server
REMOTE

echo "=== $LABEL ready: http://${IP}:${PORT} (OpenAI-compatible /v1/chat/completions + llama.cpp's own /completion) ==="
