#!/usr/bin/env bash
# Run ON proxmox-02 as root. Creates a Debian 12 VM with ONE GV100 passed
# through, to host a GPU-backed llama.cpp model server (the elastic-worker
# pattern from body-design.md Section 4.3 / src/athenaeum_body/elastic_workers.py:
# the tests use it when it answers, and fall back to CPU when it doesn't).
#
# This script only creates and boots the VM. Guest provisioning (NVIDIA
# driver, CUDA build of llama.cpp, model download, systemd unit) is
# 21-provision-gpu-model-vm.sh, run from an operator machine over SSH.
#
# Usage:
#   IP=192.168.0.97 PUBKEY_FILE=/root/athenaeum_poc.pub ./20-create-gpu-model-vm.sh
#
# Tunables (env): VMID (201), NAME, GATEWAY, GPU_PCI (0000:1f:00 -- all
# functions of that slot), CORES (6), MEM_MB (16384), DISK (64G), STORAGE (fast-z1).
set -euo pipefail

VMID="${VMID:-201}"
NAME="${NAME:-athenaeum-gpu-gv100}"
IP="${IP:?set IP (e.g. 192.168.0.97)}"
GATEWAY="${GATEWAY:-192.168.0.1}"
GPU_PCI="${GPU_PCI:-0000:1f:00}"
CORES="${CORES:-6}"
MEM_MB="${MEM_MB:-16384}"
DISK="${DISK:-64G}"
STORAGE="${STORAGE:-fast-z1}"
ONBOOT="${ONBOOT:-0}"   # user decision 2026-10-02: GPU VMs do NOT autostart with the host; set ONBOOT=1 to opt in
PUBKEY_FILE="${PUBKEY_FILE:?set PUBKEY_FILE (a public key to authorize for user 'debian')}"
IMG_URL="${IMG_URL:-https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-genericcloud-amd64.qcow2}"
IMG_DIR=/root/vm-images

[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 1; }
[ -r "$PUBKEY_FILE" ] || { echo "cannot read $PUBKEY_FILE" >&2; exit 1; }
qm status "$VMID" >/dev/null 2>&1 && { echo "VM $VMID already exists" >&2; exit 1; }

echo "== GPU guards for ${GPU_PCI} =="
dev="/sys/bus/pci/devices/${GPU_PCI}.0"
[ -e "$dev" ] || { echo "no PCI device ${GPU_PCI}.0" >&2; exit 1; }
[ "$(basename "$(readlink -f "$dev/driver")")" = vfio-pci ] || { echo "REFUSING: ${GPU_PCI}.0 is not bound to vfio-pci (run 10-gpu-passthrough.sh and reboot)" >&2; exit 1; }
if [ "$(cat "$dev/boot_vga")" != 0 ]; then
    [ "${ALLOW_BOOT_VGA:-0}" = 1 ] || { echo "REFUSING: ${GPU_PCI}.0 is the boot display GPU; pick another slot (or set ALLOW_BOOT_VGA=1 only after confirming the host needs no console on it -- /proc/fb empty, vfio-pci bound)" >&2; exit 1; }
    echo "WARNING: passing through the boot-display GPU (ALLOW_BOOT_VGA=1)"
fi
echo "ok: bound to vfio-pci, not the boot GPU"

echo "== image =="
mkdir -p "$IMG_DIR"
img="$IMG_DIR/$(basename "$IMG_URL")"
[ -s "$img" ] || curl -fL --retry 3 -o "$img" "$IMG_URL"
ls -lh "$img"

echo "== create VM $VMID ($NAME) =="
# OVMF's default 64-bit PCI window is 32GB, too small for a GV100's large BAR;
# X-PciMmio64Mb widens it (value is in MB).
qm create "$VMID" \
    --name "$NAME" --machine q35 --bios ovmf --ostype l26 \
    --cpu host --cores "$CORES" --memory "$MEM_MB" --balloon 0 \
    --scsihw virtio-scsi-single --net0 virtio,bridge=vmbr0,firewall=0 \
    --efidisk0 "${STORAGE}:1,efitype=4m,pre-enrolled-keys=0" \
    --agent 1 --onboot "$ONBOOT" --serial0 socket --vga std \
    --tags "athenaeum;gpu" \
    --description "Athenaeum GPU-backed llama.cpp model server (one GV100 passed through).
Purpose: elastic GPU worker for model-backed tests; falls back to CPU guests when down.
Lifetime: long-lived on proxmox-02; rebuild via infra/proxmox/proxmox-02/20-*.sh + 21-*.sh.
Created: $(date -u +%Y-%m-%dT%H:%MZ)"
qm set "$VMID" --args "-fw_cfg name=opt/ovmf/X-PciMmio64Mb,string=131072"
qm set "$VMID" --hostpci0 "${GPU_PCI},pcie=1"

echo "== import + size disk =="
qm importdisk "$VMID" "$img" "$STORAGE" >/dev/null
vol="$(qm config "$VMID" | awk -F': ' '/^unused0/{print $2}')"
[ -n "$vol" ] || { echo "disk import produced no unused0 volume" >&2; exit 1; }
qm set "$VMID" --scsi0 "${vol},discard=on,iothread=1,ssd=1" --boot order=scsi0
qm resize "$VMID" scsi0 "$DISK"

echo "== cloud-init =="
# scsi1, NOT ide2: Debian's genericcloud kernel has no SATA/AHCI driver, so a
# cloud-init drive on the q35 machine's default ide2 bus is never seen and the
# VM boots as "localhost" with no SSH key (found the hard way, 2026-09-28).
qm set "$VMID" --scsi1 "${STORAGE}:cloudinit" \
    --ciuser debian --sshkeys "$PUBKEY_FILE" \
    --ipconfig0 "ip=${IP}/24,gw=${GATEWAY}" --nameserver "$GATEWAY"

echo "== start =="
qm start "$VMID"
echo "started. Wait ~1 min, then: ssh -i <key> debian@${IP}"
