#!/usr/bin/env bash
# Creates all six model-evaluation guests from manifest.tsv, using the
# existing 03-create-project-guest.sh (not reimplementing guest creation --
# this is a thin loop over it with per-model GUEST_CORES/GUEST_MEM_MB and a
# description explaining what each box is and how long it's expected to
# live). Safe to re-run: 03- itself refuses to recreate an existing VMID.
#
# Requires curl+jq (run from the tools container -- 192.168.0.151 -- or
# anywhere else that has them; this Windows dev box does not).
#
# Usage:
#   source ../../../.proxmox.env   # or scp it to wherever this runs
#   PROXMOX_HOST=192.168.0.100 PROXMOX_NODE=proxmox01 \
#   PROXMOX_TOKEN_ID='claude@pve!athenaeum' PROXMOX_POOL=athenaeum-poc \
#   SSH_PUBKEY_PATH=~/.ssh/athenaeum_poc.pub \
#     ./create-model-vms.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

MANIFEST="${1:-manifest.tsv}"

while IFS=$'\t' read -r label vmid hostname ip mac cores mem_mb disk_gb hf_repo hf_file; do
    [[ "$label" =~ ^#.*$ || -z "$label" ]] && continue
    echo "=== $label ($hostname, VMID $vmid) ==="
    GUEST_VMID="$vmid" \
    GUEST_HOSTNAME="$hostname" \
    GUEST_IP="$ip" \
    GUEST_MAC="$mac" \
    GUEST_CORES="$cores" \
    GUEST_MEM_MB="$mem_mb" \
    GUEST_DISK_GB="$disk_gb" \
    GUEST_PURPOSE="LLM candidate evaluation -- runs ${label} (via llama.cpp) for A/B/C comparison against the other five model-lab guests, ahead of picking the Local Model Serving Layer's real backend (body-design.md Section 4.5)." \
    GUEST_LIFETIME="Temporary -- expected to be destroyed once the model-backend decision is made (either this candidate is dropped, or it graduates into the real serving topology under a different name/role)." \
        ../03-create-project-guest.sh
done < "$MANIFEST"

echo
echo "All model-lab guests created. Next: run setup-llama-and-download.sh against each one (see model-lab/README.md)."
