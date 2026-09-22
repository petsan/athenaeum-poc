#!/usr/bin/env bash
# Standalone guest-creation script -- deliberately does NOT depend on the
# tools container existing, so it still works for disaster recovery if
# the tools container itself is what needs rebuilding. Same logic as
# `pve-ops create`, just runnable from anywhere with curl/jq/ssh and a
# valid project env file (this repo's own .proxmox.env, or any project's
# equivalent).
#
# Usage:
#   source ../../.proxmox.env   # or whichever project's env file
#   SSH_PUBKEY_PATH=~/.ssh/athenaeum_poc.pub \
#   GUEST_VMID=104 GUEST_HOSTNAME=athenaeum-preflight \
#   GUEST_IP=192.168.0.150 GUEST_MAC=BC:24:11:AA:BB:CC \
#     ./03-create-project-guest.sh
#
# Brainbox tier (optional, see docs/infra-topology.md for the full
# rationale): set GUEST_TIER to xsmall|medium|large|xlarge to pick sane
# vCPU/RAM/disk defaults for that role. GUEST_CORES/GUEST_MEM_MB/
# GUEST_DISK_GB, if set, always win over the tier default. Omitting
# GUEST_TIER keeps the original 2vCPU/2GB/8GB defaults this script always
# had, so existing callers (e.g. LXC 104's own rebuild) are unaffected.
#   GUEST_TIER=medium GUEST_VMID=110 GUEST_HOSTNAME=athenaeum-agent-md-physics \
#   GUEST_IP=192.168.0.152 GUEST_MAC=BC:24:11:AA:BB:CD \
#     ./03-create-project-guest.sh
#
# For a guest that needs real nested unshare/mount/cgroups (sandbox-style
# testing), this script creates it unprivileged first -- you must then
# run the destroy+recreate-with-flags dance from deployment-playbook.md
# Section 6 yourself, directly on the host as root@pam. That combination
# cannot be done via API by design (needs Sys.Modify, which this
# project's scoped token intentionally does not have).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source lib/common.sh

VMID="${GUEST_VMID:?set GUEST_VMID}"
HOSTNAME="${GUEST_HOSTNAME:?set GUEST_HOSTNAME}"
IP="${GUEST_IP:?set GUEST_IP}"
MAC="${GUEST_MAC:?set GUEST_MAC}"
GATEWAY="${PROXMOX_GATEWAY:-192.168.0.1}"
POOL="${PROXMOX_POOL:?set PROXMOX_POOL}"
STORAGE="${GUEST_STORAGE:-local-thin-multi}"
SSH_PUBKEY_PATH="${SSH_PUBKEY_PATH:?set SSH_PUBKEY_PATH}"
GUEST_PURPOSE="${GUEST_PURPOSE:-general Athenaeum project workload}"
GUEST_LIFETIME="${GUEST_LIFETIME:-long-lived; rebuilt via this script when needed, not destroyed casually}"

# Tier defaults per docs/infra-topology.md Section 2. The untiered default
# (empty GUEST_TIER) matches this script's original 2vCPU/2GB/8GB shape.
case "${GUEST_TIER:-}" in
    "")       TIER_CORES=2;  TIER_MEM_MB=2048;  TIER_DISK_GB=8  ;;
    xsmall)   TIER_CORES=1;  TIER_MEM_MB=2048;  TIER_DISK_GB=8  ;;
    medium)   TIER_CORES=4;  TIER_MEM_MB=16384; TIER_DISK_GB=16 ;;
    large)    TIER_CORES=8;  TIER_MEM_MB=40960; TIER_DISK_GB=32 ;;
    xlarge)   TIER_CORES=16; TIER_MEM_MB=81920; TIER_DISK_GB=64 ;;
    *)
        echo "Unknown GUEST_TIER '${GUEST_TIER}' -- expected one of xsmall|medium|large|xlarge (or unset)" >&2
        exit 1
        ;;
esac
CORES="${GUEST_CORES:-$TIER_CORES}"
MEM="${GUEST_MEM_MB:-$TIER_MEM_MB}"
DISK="${GUEST_DISK_GB:-$TIER_DISK_GB}"

if [ -n "${GUEST_TIER:-}" ]; then
    echo "Tier '${GUEST_TIER}': requesting ${CORES} vCPU / ${MEM}MB RAM / ${DISK}GB disk."
    echo "Reminder (docs/infra-topology.md Sec.1): 50% host cap = 20 vCPU / 252GB total across ALL guests here, not per guest -- check current usage (pve-ops or the Proxmox UI) before stacking multiple Medium/Large/XLarge boxes."
fi

if pve_lxc_exists "$VMID"; then
    echo "LXC $VMID already exists. Stop+destroy it first if you want a clean rebuild:" >&2
    echo "  (this script refuses to silently destroy an existing guest)" >&2
    exit 1
fi

DESCRIPTION="${GUEST_DESCRIPTION:-Athenaeum project guest (${HOSTNAME}).
Purpose: ${GUEST_PURPOSE}
Expected lifetime: ${GUEST_LIFETIME}
Tier: ${GUEST_TIER:-untiered (2vCPU/2GB/8GB default)}
Created: $(date -u +%Y-%m-%dT%H:%MZ) via infra/proxmox/03-create-project-guest.sh}"

echo "Creating $VMID ($HOSTNAME, $IP, $MAC) in pool $POOL on $STORAGE..."
resp=$(pve_api POST "/nodes/${PROXMOX_NODE}/lxc" \
    --data-urlencode "vmid=${VMID}" \
    --data-urlencode "ostemplate=local:vztmpl/debian-12-standard_12.12-1_amd64.tar.zst" \
    --data-urlencode "hostname=${HOSTNAME}" \
    --data-urlencode "cores=${CORES}" \
    --data-urlencode "memory=${MEM}" \
    --data-urlencode "rootfs=${STORAGE}:${DISK}" \
    --data-urlencode "net0=name=eth0,bridge=vmbr0,ip=${IP}/24,gw=${GATEWAY},firewall=0,hwaddr=${MAC}" \
    --data-urlencode "pool=${POOL}" \
    --data-urlencode "unprivileged=1" \
    --data-urlencode "onboot=1" \
    --data-urlencode "description=${DESCRIPTION}" \
    --data-urlencode "ssh-public-keys=$(cat "$SSH_PUBKEY_PATH")")
pve_wait_task "$(echo "$resp" | jq -r '.data')"

echo "Starting..."
pve_wait_task "$(pve_api POST "/nodes/${PROXMOX_NODE}/lxc/${VMID}/status/start" | jq -r '.data')"

echo "Created and started. Verify:"
echo "  ssh -i <key> root@${IP} 'echo ok'"
echo
echo "If this guest needs privileged+nesting (sandbox-style testing), now"
echo "run on the Proxmox host as root@pam:"
echo "  pct stop ${VMID} && pct destroy ${VMID}"
echo "  pct create ${VMID} local:vztmpl/debian-12-standard_12.12-1_amd64.tar.zst \\"
echo "    --hostname ${HOSTNAME} --cores ${CORES} --memory ${MEM} --rootfs ${STORAGE}:${DISK} \\"
echo "    --net0 name=eth0,bridge=vmbr0,ip=${IP}/24,gw=${GATEWAY},firewall=0,hwaddr=${MAC} \\"
echo "    --pool ${POOL} --unprivileged 0 --features nesting=1,keyctl=1"
echo "  pct start ${VMID}"
echo "  pct exec ${VMID} -- bash -c \"mkdir -p /root/.ssh && chmod 700 /root/.ssh && echo '\$(cat "$SSH_PUBKEY_PATH")' >> /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys\""
echo "  pct set ${VMID} --description \"$DESCRIPTION\"   # the destroy+recreate above drops the Notes field -- reapply it"
