#!/usr/bin/env bash
# Run from the operator machine (Bash tool). Pulls proxmox-02's and VM 202's CONFIGURATION
# (text only) into infra/proxmox/proxmox-02/config-backup/ so it is versioned in git.
# Scope, stated plainly: configs ONLY. NOT backed up: model files (re-downloadable), VM disks,
# ZFS data. VMs other than 202 are treated as ephemeral (user decision, 2026-10-03).
set -euo pipefail
DEST="$(cd "$(dirname "$0")" && pwd)/config-backup"
HOSTKEY="${HOSTKEY:-$HOME/.ssh/proxmox02}"; VMKEY="${VMKEY:-$HOME/.ssh/athenaeum_poc}"
HOST="${HOST:-root@192.168.0.99}"; VM="${VM:-debian@192.168.0.96}"
rm -rf "$DEST/host" "$DEST/vm202"; mkdir -p "$DEST/host" "$DEST/vm202"
ssh -i "$HOSTKEY" "$HOST" 'tar -czf - --ignore-failed-read /etc/pve/nodes/proxmox-02/qemu-server /etc/pve/storage.cfg /etc/network/interfaces /etc/modprobe.d /etc/modules /etc/default/grub /etc/hosts /etc/hostname 2>/dev/null' | tar -xzf - -C "$DEST/host"
ssh -i "$HOSTKEY" "$HOST" '{ echo "## zpool status"; zpool status fast-z1; echo; echo "## zfs local properties"; zfs get -s local all 2>/dev/null; echo; echo "## qm list"; qm list; echo; echo "## pveversion"; pveversion; uname -r; } 2>&1' > "$DEST/host/zfs-and-versions.txt"
ssh -i "$VMKEY" "$VM" 'sudo tar -czf - --ignore-failed-read /etc/systemd/system/llama-server.service /etc/systemd/system/llama-server-q8.service /etc/systemd/system/llama-server*.bak* /etc/netplan /etc/cloud/cloud.cfg.d /etc/hostname 2>/dev/null' | tar -xzf - -C "$DEST/vm202"
ssh -i "$VMKEY" "$VM" '{ echo "## llama.cpp commit"; git -c safe.directory=/opt/llama.cpp -C /opt/llama.cpp rev-parse HEAD; echo "## cmake flags"; grep -E "^(CMAKE_BUILD_TYPE|CMAKE_CUDA_ARCHITECTURES|GGML_CUDA|LLAMA_CURL)[:=]" /opt/llama.cpp/build/CMakeCache.txt; echo "## nvidia/cuda packages"; dpkg -l | awk "/nvidia|cuda/{print \$2, \$3}" | head -30; echo "## model files (names/sizes only)"; ls -lR /opt/models | grep -E "gguf|^/"; } 2>&1' > "$DEST/vm202/versions-and-models.txt"
echo "backup written to $DEST"; find "$DEST" -type f | sed "s|$DEST/||" | sort
