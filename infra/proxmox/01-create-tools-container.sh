#!/usr/bin/env bash
# Creates (or, if it already exists, just verifies + re-syncs) the ONE
# shared, project-agnostic tools container. There should only ever be one
# of these per Proxmox host -- it's meant to be reused by every future
# project, not recreated per-project. Run 02-register-project.sh
# afterward (once per project) to onboard a project's credentials onto it.
#
# Requires: an env file sourced first (see infra/proxmox/README.md) with
# PROXMOX_HOST/PORT/NODE/TOKEN_ID/TOKEN_SECRET, plus a token that already
# has VM.Allocate/Datastore.AllocateSpace/SDN.Use on the target
# pool/storage/sdn-zone (i.e. 00-bootstrap-identity.sh already ran for
# AT LEAST one project -- the tools container itself needs to live in
# some pool; reuse an existing one or create a dedicated "shared-tools"
# pool first).
#
# Usage:
#   TOOLS_VMID=106 TOOLS_IP=192.168.0.151 TOOLS_MAC=BC:24:11:AA:BB:CD \
#   TOOLS_POOL=athenaeum-poc SSH_PUBKEY_PATH=~/.ssh/athenaeum_poc.pub \
#     ./01-create-tools-container.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source lib/common.sh

VMID="${TOOLS_VMID:-106}"
HOSTNAME="${TOOLS_HOSTNAME:-athenaeum-tools}"
IP="${TOOLS_IP:?set TOOLS_IP, e.g. 192.168.0.151}"
MAC="${TOOLS_MAC:?set TOOLS_MAC, e.g. BC:24:11:AA:BB:CD -- must be unique on the LAN}"
GATEWAY="${TOOLS_GATEWAY:-192.168.0.1}"
POOL="${TOOLS_POOL:?set TOOLS_POOL -- which resource pool the tools box lives in}"
STORAGE="${TOOLS_STORAGE:-local-thin-multi}"
SSH_PUBKEY_PATH="${SSH_PUBKEY_PATH:?set SSH_PUBKEY_PATH -- public key to inject as root's authorized_keys}"

DESCRIPTION="${TOOLS_DESCRIPTION:-Athenaeum shared tools container (pve-ops CLI).
Purpose: multi-project Proxmox API tooling, shared across every project on this host -- not recreated per-project.
Expected lifetime: persistent (see infra/proxmox/README.md's onboot/backup coverage).
Created: $(date -u +%Y-%m-%dT%H:%MZ) via infra/proxmox/01-create-tools-container.sh}"

if pve_lxc_exists "$VMID"; then
    echo "LXC $VMID already exists -- not recreating. (Destroy it first if you actually want a from-scratch rebuild.)"
    echo "Re-syncing Notes/description..."
    pve_api PUT "/nodes/${PROXMOX_NODE}/lxc/${VMID}/config" --data-urlencode "description=${DESCRIPTION}" >/dev/null
else
    echo "Creating tools container $VMID ($HOSTNAME, $IP, $MAC)..."
    resp=$(pve_api POST "/nodes/${PROXMOX_NODE}/lxc" \
        --data-urlencode "vmid=${VMID}" \
        --data-urlencode "ostemplate=local:vztmpl/debian-12-standard_12.12-1_amd64.tar.zst" \
        --data-urlencode "hostname=${HOSTNAME}" \
        --data-urlencode "cores=1" \
        --data-urlencode "memory=1024" \
        --data-urlencode "rootfs=${STORAGE}:8" \
        --data-urlencode "net0=name=eth0,bridge=vmbr0,ip=${IP}/24,gw=${GATEWAY},firewall=0,hwaddr=${MAC}" \
        --data-urlencode "pool=${POOL}" \
        --data-urlencode "unprivileged=1" \
        --data-urlencode "onboot=1" \
        --data-urlencode "description=${DESCRIPTION}" \
        --data-urlencode "ssh-public-keys=$(cat "$SSH_PUBKEY_PATH")")
    pve_wait_task "$(echo "$resp" | jq -r '.data')"
    echo "Starting..."
    pve_wait_task "$(pve_api POST "/nodes/${PROXMOX_NODE}/lxc/${VMID}/status/start" | jq -r '.data')"
    echo "Waiting for SSH to come up..."
    for _ in $(seq 1 30); do
        ssh -i "${SSH_PRIVATE_KEY_PATH:-${SSH_PUBKEY_PATH%.pub}}" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=3 \
            "root@${IP}" "true" 2>/dev/null && break
        sleep 2
    done
fi

echo "Installing base tooling (curl, jq, ssh client)..."
SSH_PRIVATE_KEY_PATH="${SSH_PRIVATE_KEY_PATH:-${SSH_PUBKEY_PATH%.pub}}"
ssh -i "$SSH_PRIVATE_KEY_PATH" -o StrictHostKeyChecking=accept-new "root@${IP}" \
    "apt-get update -qq && apt-get install -y -qq curl jq openssh-client && mkdir -p /opt/athenaeum-tools/keys /opt/athenaeum-tools/bin"

echo "Deploying CLI (pve-ops)..."
scp -i "$SSH_PRIVATE_KEY_PATH" "$(dirname "${BASH_SOURCE[0]}")/tools-cli/pve-ops" "root@${IP}:/opt/athenaeum-tools/bin/pve-ops"
ssh -i "$SSH_PRIVATE_KEY_PATH" "root@${IP}" \
    "chmod +x /opt/athenaeum-tools/bin/pve-ops && ln -sf /opt/athenaeum-tools/bin/pve-ops /usr/local/bin/pve-ops && ln -sf /opt/athenaeum-tools/bin/pve-ops /usr/local/bin/athenaeum-ops"

echo "Tools container ready at ${IP}. Next: run 02-register-project.sh for each project that should be manageable from here."
