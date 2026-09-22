#!/usr/bin/env bash
# Run this ON THE PROXMOX HOST, as root@pam (or another admin with
# Sys.Modify/User.Modify) -- creating a user/role/token/pool is exactly
# the kind of privileged action this project's own scoped tokens are
# deliberately NOT allowed to do, so there is no API-only path for this
# step. This is Section 3 of deployment-playbook.md, as a script instead
# of copy-pasted commands.
#
# Idempotent: safe to re-run. Existing user/role/pool/token are left
# alone (won't overwrite an existing token's secret -- if you need a new
# secret, delete the token first with `pveum user token remove`).
#
# Usage:
#   ./00-bootstrap-identity.sh <project-name> [pool-name]
#
# Example:
#   ./00-bootstrap-identity.sh myproject
#   -> creates claude@pve, role ClaudeAgent-myproject, pool myproject-poc,
#      token claude@pve!myproject
set -euo pipefail

PROJECT="${1:?usage: $0 <project-name> [pool-name]}"
POOL="${2:-${PROJECT}-poc}"
ROLE="ClaudeAgent-${PROJECT}"
TOKEN_ID="${PROJECT}"
NODE="${PROXMOX_NODE:-proxmox01}"

command -v pveum >/dev/null 2>&1 || { echo "pveum not found -- run this ON the Proxmox host." >&2; exit 1; }

echo "== user =="
pveum user list --output-format json | jq -e '.[] | select(.userid=="claude@pve")' >/dev/null 2>&1 \
    && echo "claude@pve already exists, skipping" \
    || pveum user add claude@pve

echo "== pool =="
pveum pool list --output-format json | jq -e --arg p "$POOL" '.[] | select(.poolid==$p)' >/dev/null 2>&1 \
    && echo "pool $POOL already exists, skipping" \
    || pveum pool add "$POOL"

echo "== role =="
# Full privilege list, including VM.Audit -- this project's role was
# initially created WITHOUT VM.Audit and silently broke bulk guest
# listing (empty array, no error) until caught and fixed. Don't repeat
# that omission on a fresh bootstrap.
PRIVS="Datastore.AllocateSpace,Datastore.Audit,Pool.Audit,SDN.Use,Sys.Audit,VM.Allocate,VM.Audit,VM.Config.CDROM,VM.Config.CPU,VM.Config.Cloudinit,VM.Config.Disk,VM.Config.HWType,VM.Config.Memory,VM.Config.Network,VM.Config.Options,VM.PowerMgmt"
pveum role list --output-format json | jq -e --arg r "$ROLE" '.[] | select(.roleid==$r)' >/dev/null 2>&1 \
    && { echo "role $ROLE exists, updating privileges to current set"; pveum role modify "$ROLE" -privs "$PRIVS"; } \
    || pveum role add "$ROLE" -privs "$PRIVS"

echo "== token =="
if pveum user token list claude@pve --output-format json | jq -e --arg t "$TOKEN_ID" '.[] | select(.tokenid==$t)' >/dev/null 2>&1; then
    echo "token claude@pve!${TOKEN_ID} already exists -- not recreating (secret can't be re-shown)."
    echo "If you need a fresh secret: pveum user token remove claude@pve ${TOKEN_ID}, then re-run this script."
else
    echo ">>> SAVE THIS SECRET NOW, IT IS NEVER SHOWN AGAIN <<<"
    pveum user token add claude@pve "$TOKEN_ID" --privsep 1
fi

echo "== ACL grants (both token AND user -- see known-bugs.md entry re: this host's Privilege Separation intersection quirk) =="
for path in "/pool/${POOL}" "/nodes/${NODE}" "/storage/local-thin-multi" "/storage/local" "/sdn/zones/localnetwork/vmbr0"; do
    echo "  -> $path"
    pveum acl modify "$path" --tokens "claude@pve!${TOKEN_ID}" --roles "$ROLE"
    pveum acl modify "$path" --users claude@pve --roles "$ROLE"
done

echo
echo "Done. Verify with:"
echo "  curl -sk -H \"Authorization: PVEAPIToken=claude@pve!${TOKEN_ID}=<secret>\" https://<host>:8006/api2/json/access/permissions?path=/pool/${POOL} | jq"
echo "Expect a non-empty privilege map. If empty, one of the ACL grants above is missing or the intersection rule wasn't satisfied."
