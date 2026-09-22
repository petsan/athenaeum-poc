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
CORES="${GUEST_CORES:-2}"
MEM="${GUEST_MEM_MB:-2048}"
DISK="${GUEST_DISK_GB:-8}"
SSH_PUBKEY_PATH="${SSH_PUBKEY_PATH:?set SSH_PUBKEY_PATH}"

if pve_lxc_exists "$VMID"; then
    echo "LXC $VMID already exists. Stop+destroy it first if you want a clean rebuild:" >&2
    echo "  (this script refuses to silently destroy an existing guest)" >&2
    exit 1
fi

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
