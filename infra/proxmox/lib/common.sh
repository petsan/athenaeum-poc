#!/usr/bin/env bash
# Shared helpers for infra/proxmox/*.sh. Source this, don't execute it.
#
# Every script in this directory that talks to the Proxmox API expects an
# env file (see infra/proxmox/README.md) already sourced, providing at
# least: PROXMOX_HOST, PROXMOX_PORT, PROXMOX_NODE, PROXMOX_TOKEN_ID,
# PROXMOX_TOKEN_SECRET.

: "${PROXMOX_HOST:?set PROXMOX_HOST (see infra/proxmox/README.md)}"
: "${PROXMOX_NODE:?set PROXMOX_NODE}"
: "${PROXMOX_TOKEN_ID:?set PROXMOX_TOKEN_ID}"
: "${PROXMOX_TOKEN_SECRET:?set PROXMOX_TOKEN_SECRET}"

PVE_API="https://${PROXMOX_HOST}:${PROXMOX_PORT:-8006}/api2/json"
PVE_AUTH_HEADER="Authorization: PVEAPIToken=${PROXMOX_TOKEN_ID}=${PROXMOX_TOKEN_SECRET}"

pve_api() {
    # pve_api METHOD PATH [curl-args...]
    local method="$1" path="$2"; shift 2
    curl -sk -X "$method" -H "$PVE_AUTH_HEADER" "$@" "${PVE_API}${path}"
}

pve_wait_task() {
    # pve_wait_task UPID -- polls until stopped; echoes exitstatus; returns
    # non-zero if it wasn't "OK" or a benign "WARNINGS: N" (e.g. LXC
    # create's own "Systemd 252 detected, you may need to enable nesting"
    # on every debian-12-standard template create -- true, harmless, and
    # not something guest creation should fail on; caught while creating
    # the model-lab guests, where this previously aborted VMID 110's
    # creation script after the guest itself was already created fine).
    local upid="$1" encoded status resp exitstatus
    encoded=$(printf '%s' "$upid" | sed 's/:/%3A/g')
    for _ in $(seq 1 90); do
        resp=$(pve_api GET "/nodes/${PROXMOX_NODE}/tasks/${encoded}/status")
        status=$(echo "$resp" | jq -r '.data.status')
        if [[ "$status" == "stopped" ]]; then
            exitstatus=$(echo "$resp" | jq -r '.data.exitstatus')
            echo "task finished: $exitstatus"
            [[ "$exitstatus" == "OK" || "$exitstatus" == WARNINGS:* ]] || return 1
            return 0
        fi
        sleep 2
    done
    echo "task did not finish within timeout: $upid" >&2
    return 1
}

pve_lxc_exists() {
    local vmid="$1"
    pve_api GET "/nodes/${PROXMOX_NODE}/lxc/${vmid}/status/current" 2>/dev/null | jq -e '.data.vmid' >/dev/null 2>&1
}
