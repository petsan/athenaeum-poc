#!/usr/bin/env bash
# Health-check script matching deployment-playbook.md Section 9's
# verification checklist. Run after any create/rebuild to confirm things
# actually work, not just that the API calls returned success.
#
# Usage:
#   source ../../.proxmox.env
#   GUEST_IP=192.168.0.150 SSH_KEY=~/.ssh/athenaeum_poc ./05-verify.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source lib/common.sh

GUEST_IP="${GUEST_IP:?set GUEST_IP}"
SSH_KEY="${SSH_KEY:?set SSH_KEY}"
POOL="${PROXMOX_POOL:?set PROXMOX_POOL}"

pass() { echo "[PASS] $1"; }
fail() { echo "[FAIL] $1"; FAILED=1; }
FAILED=0

echo "--- permissions ---"
perms=$(pve_api GET "/access/permissions?path=/pool/${POOL}")
if [[ "$(echo "$perms" | jq -c '.data')" != "{}" ]]; then
    pass "token has non-empty permissions on /pool/${POOL}"
else
    fail "empty permission map on /pool/${POOL} -- check ACL grants (both token AND user, see the intersection-quirk note)"
fi

echo "--- ping from wherever this script is running ---"
if ping -c 2 -W 2 "$GUEST_IP" >/dev/null 2>&1 || ping -n 2 -w 2000 "$GUEST_IP" >/dev/null 2>&1; then
    pass "ping $GUEST_IP"
else
    fail "ping $GUEST_IP -- if this passes from the Proxmox host but not from here, check the Docker FORWARD-chain fix (known-bugs.md #18)"
fi

echo "--- SSH ---"
if ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5 "root@${GUEST_IP}" "echo ok" >/dev/null 2>&1; then
    pass "ssh root@${GUEST_IP}"
else
    fail "ssh root@${GUEST_IP} -- if the host key changed, this might be a legitimate rebuild (ssh-keygen -R ${GUEST_IP}), not a real failure"
fi

echo "--- internet egress from inside the guest ---"
if ssh -i "$SSH_KEY" -o ConnectTimeout=5 "root@${GUEST_IP}" "ping -c 2 -W 2 8.8.8.8" >/dev/null 2>&1; then
    pass "guest has internet egress"
else
    fail "guest has no internet egress -- check Docker FORWARD-chain fix"
fi

echo
if [[ $FAILED -eq 0 ]]; then
    echo "All checks passed."
else
    echo "One or more checks failed -- see above." >&2
    exit 1
fi
