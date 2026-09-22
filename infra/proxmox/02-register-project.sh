#!/usr/bin/env bash
# Onboards one project's credentials onto the (already-existing) shared
# tools container, so `pve-ops -p <project> ...` works from there. Run
# once per project -- safe to re-run to refresh a rotated token/key.
#
# Usage:
#   ./02-register-project.sh <project-name> <project-env-file> <project-ssh-private-key> <tools-container-ip>
#
# Example:
#   ./02-register-project.sh athenaeum ../../.proxmox.env ~/.ssh/athenaeum_poc 192.168.0.151
#
# <project-env-file> is that project's local .proxmox.env (the one this
# repo's own deployment-playbook.md Section 1 describes) -- this script
# reformats it into the pve-ops schema, it does not assume the two are
# already identical.
set -euo pipefail

PROJECT="${1:?usage: $0 <project-name> <project-env-file> <project-ssh-key> <tools-ip>}"
PROJECT_ENV_FILE="${2:?}"
PROJECT_SSH_KEY="${3:?}"
TOOLS_IP="${4:?}"
TOOLS_SSH_KEY="${TOOLS_SSH_KEY:-$PROJECT_SSH_KEY}"

[[ -f "$PROJECT_ENV_FILE" ]] || { echo "No such file: $PROJECT_ENV_FILE" >&2; exit 1; }
[[ -f "$PROJECT_SSH_KEY" ]] || { echo "No such file: $PROJECT_SSH_KEY" >&2; exit 1; }
[[ -f "${PROJECT_SSH_KEY}.pub" ]] || { echo "No such file: ${PROJECT_SSH_KEY}.pub" >&2; exit 1; }

# shellcheck source=/dev/null
source "$PROJECT_ENV_FILE"

TMP_ENV="$(mktemp)"
trap 'rm -f "$TMP_ENV"' EXIT
cat > "$TMP_ENV" <<EOF
PROXMOX_HOST=${PROXMOX_HOST}
PROXMOX_PORT=${PROXMOX_PORT:-8006}
PROXMOX_NODE=${PROXMOX_NODE}
PROXMOX_TOKEN_ID=${PROXMOX_TOKEN_ID}
PROXMOX_TOKEN_SECRET=${PROXMOX_TOKEN_SECRET}
PROXMOX_POOL=${PROXMOX_POOL}
PROXMOX_GATEWAY=${PROXMOX_GUEST_GATEWAY:-192.168.0.1}
EOF

echo "Pushing ${PROJECT}.env and SSH key to tools container ${TOOLS_IP}..."
ssh -i "$TOOLS_SSH_KEY" "root@${TOOLS_IP}" "mkdir -p /opt/athenaeum-tools/keys"
scp -i "$TOOLS_SSH_KEY" "$TMP_ENV" "root@${TOOLS_IP}:/opt/athenaeum-tools/keys/${PROJECT}.env"
scp -i "$TOOLS_SSH_KEY" "$PROJECT_SSH_KEY" "${PROJECT_SSH_KEY}.pub" "root@${TOOLS_IP}:/opt/athenaeum-tools/keys/"
ssh -i "$TOOLS_SSH_KEY" "root@${TOOLS_IP}" \
    "chmod 600 /opt/athenaeum-tools/keys/${PROJECT}.env /opt/athenaeum-tools/keys/$(basename "$PROJECT_SSH_KEY") && \
     chmod 644 /opt/athenaeum-tools/keys/$(basename "$PROJECT_SSH_KEY").pub && \
     chown -R root:root /opt/athenaeum-tools"

echo "Done. From the tools container (or via 'pve-ops -p ${PROJECT} ssh ${TOOLS_IP} ...'):"
echo "  pve-ops -p ${PROJECT} status"
