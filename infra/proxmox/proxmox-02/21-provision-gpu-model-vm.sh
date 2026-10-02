#!/usr/bin/env bash
# Run from an OPERATOR machine (needs ssh), against the VM created by
# 20-create-gpu-model-vm.sh. Two phases because the NVIDIA kernel module needs
# a reboot before anything can use the GPU:
#
#   VM_IP=192.168.0.97 SSH_KEY=~/.ssh/athenaeum_poc ./21-provision-gpu-model-vm.sh driver
#   (wait for the VM to come back)
#   VM_IP=192.168.0.97 SSH_KEY=~/.ssh/athenaeum_poc ./21-provision-gpu-model-vm.sh serve
#
# driver: enables Debian non-free, installs the packaged NVIDIA driver (DKMS)
#         + CUDA toolkit + build tools, reboots the VM.
# serve:  verifies nvidia-smi, builds llama.cpp's llama-server with CUDA for
#         the GV100 (compute capability 7.0), downloads the model, installs a
#         systemd unit on :8080.
#
# Flags carried over from infra/proxmox/model-lab/setup-llama-and-download.sh:
# --no-jinja (OLMo 3's chat template crashes llama-server's parser at startup;
# callers only use raw /completion anyway).
set -euo pipefail

VM_IP="${VM_IP:?set VM_IP}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/athenaeum_poc}"
PORT="${LLAMA_PORT:-8080}"
HF_REPO="${HF_REPO:-bartowski/allenai_Olmo-3-7B-Instruct-GGUF}"
HF_FILE="${HF_FILE:-allenai_Olmo-3-7B-Instruct-Q4_K_M.gguf}"
CUDA_ARCH="${CUDA_ARCH:-70}"   # GV100 = Volta = sm_70
CTX="${CTX:-4096}"                        # llama-server -c (context tokens)
LLAMA_ARGS="${LLAMA_ARGS---no-jinja}"   # extra llama-server flags; chat models want jinja, so pass LLAMA_ARGS="" or e.g. "--jinja"
LLAMA_REPO="${LLAMA_REPO:-https://github.com/ggml-org/llama.cpp}"  # Bonsai needs https://github.com/PrismML-Eng/llama.cpp
SERVICE_LABEL="${SERVICE_LABEL:-${HF_FILE}}"
LLAMA_DIR="${LLAMA_DIR:-/opt/llama.cpp}"    # separate dir per build when one VM runs two llama.cpp variants
UNIT="${UNIT:-llama-server}"             # systemd unit name; distinct per server in a shared VM
CMAKE_EXTRA="${CMAKE_EXTRA:-}"            # extra cmake flags, e.g. the PrismML fork needs -DCUDAToolkit_ROOT=/usr -DCUDAToolkit_INCLUDE_DIR=/usr/include on Debian's split toolkit layout
PHASE="${1:?usage: $0 driver|serve}"

rssh() { ssh -i "$SSH_KEY" -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=20 "debian@${VM_IP}" "$@"; }

case "$PHASE" in
driver)
    rssh 'sudo bash -s' <<'REMOTE'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
sed -i 's/^Components: main$/Components: main contrib non-free non-free-firmware/' /etc/apt/sources.list.d/debian.sources
grep -q non-free /etc/apt/sources.list.d/debian.sources || { echo "failed to enable non-free" >&2; exit 1; }
apt-get update -qq
apt-get install -y -qq "linux-headers-$(uname -r)" build-essential cmake git curl python3-pip dkms >/dev/null
apt-get install -y nvidia-kernel-dkms nvidia-smi libcuda1 nvidia-cuda-toolkit 2>&1 | tail -5
dkms status
echo "driver phase done; rebooting"
(sleep 2; systemctl reboot) &
REMOTE
    ;;
serve)
    rssh 'sudo bash -s' <<REMOTE
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

echo "--- nvidia-smi"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv

if [ ! -d ${LLAMA_DIR} ]; then
    git clone --depth 1 ${LLAMA_REPO} ${LLAMA_DIR}
fi
echo "--- building llama-server (CUDA sm_${CUDA_ARCH}); this takes a while"
export CUDACXX=/usr/lib/nvidia-cuda-toolkit/bin/nvcc
cmake -B ${LLAMA_DIR}/build -S ${LLAMA_DIR} -DCMAKE_BUILD_TYPE=Release \
    -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=${CUDA_ARCH} -DLLAMA_CURL=OFF ${CMAKE_EXTRA}
cmake --build ${LLAMA_DIR}/build --config Release --target llama-server -j\$(nproc)

echo "--- model download"
pip install --break-system-packages -q -U "huggingface_hub[cli]"
mkdir -p /opt/models
export PATH=\$PATH:/root/.local/bin:/usr/local/bin
hf download "${HF_REPO}" "${HF_FILE}" --local-dir /opt/models

cat > /etc/systemd/system/${UNIT}.service <<UNIT
[Unit]
Description=llama.cpp GPU server -- ${SERVICE_LABEL} (Athenaeum elastic GPU worker, GV100)
After=network.target

[Service]
ExecStart=${LLAMA_DIR}/build/bin/llama-server --model /opt/models/${HF_FILE} --host 0.0.0.0 --port ${PORT} -c ${CTX} --n-gpu-layers 999 ${LLAMA_ARGS}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now ${UNIT}
sleep 5
systemctl is-active ${UNIT}
REMOTE
    echo "ready: http://${VM_IP}:${PORT}  (check: curl http://${VM_IP}:${PORT}/health)"
    ;;
*)
    echo "unknown phase '$PHASE' (driver|serve)" >&2; exit 1 ;;
esac
