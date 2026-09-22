#!/usr/bin/env bash
# Orchestrates a from-scratch rebuild of this project's Proxmox
# footprint: the shared tools container (if it doesn't already exist)
# and this project's own guest, then verifies both. Does NOT run the two
# steps that need root@pam directly on the host (00-bootstrap-identity.sh
# and 04-persist-docker-forward-fix.sh) -- run those yourself first if
# starting from truly nothing (a wiped host, or a brand new project).
#
# Usage (from this directory, with this project's .proxmox.env already
# filled in one level up, matching deployment-playbook.md Section 1):
#   source ../../.proxmox.env
#   ./rebuild-all.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

: "${PROXMOX_TOKEN_SECRET:?source your project's .proxmox.env first}"
: "${PROXMOX_GUEST_IP:?set in .proxmox.env}"
: "${PROXMOX_GUEST_MAC:?set in .proxmox.env}"
: "${PROXMOX_GUEST_HOSTNAME:?set in .proxmox.env}"
: "${PROXMOX_VMID:?set in .proxmox.env}"
: "${SSH_KEY_PATH:?set in .proxmox.env}"

echo "=== 1. Shared tools container ==="
TOOLS_VMID="${TOOLS_VMID:-106}" \
TOOLS_IP="${TOOLS_IP:-192.168.0.151}" \
TOOLS_MAC="${TOOLS_MAC:-BC:24:11:AA:BB:CD}" \
TOOLS_POOL="${PROXMOX_POOL}" \
SSH_PUBKEY_PATH="${SSH_KEY_PATH}.pub" \
SSH_PRIVATE_KEY_PATH="${SSH_KEY_PATH}" \
    ./01-create-tools-container.sh

echo "=== 2. Register this project on the tools container ==="
./02-register-project.sh "$(basename "$(pwd)/../..")" "../../.proxmox.env" "$SSH_KEY_PATH" "${TOOLS_IP:-192.168.0.151}" || true

echo "=== 3. This project's own guest ==="
GUEST_VMID="$PROXMOX_VMID" GUEST_HOSTNAME="$PROXMOX_GUEST_HOSTNAME" \
GUEST_IP="$PROXMOX_GUEST_IP" GUEST_MAC="$PROXMOX_GUEST_MAC" \
SSH_PUBKEY_PATH="${SSH_KEY_PATH}.pub" \
    ./03-create-project-guest.sh || echo "(guest may already exist -- see message above)"

echo "=== 4. Verify ==="
GUEST_IP="$PROXMOX_GUEST_IP" SSH_KEY="$SSH_KEY_PATH" ./05-verify.sh

echo
echo "Reminder: if this is a genuinely fresh host, you still need to have run"
echo "(as root@pam, directly on the host, BEFORE this script):"
echo "  00-bootstrap-identity.sh <project-name>"
echo "  04-persist-docker-forward-fix.sh"
echo "And if this project's guest needs privileged+nesting, that destroy+"
echo "recreate step from deployment-playbook.md Section 6 is also host-only."
