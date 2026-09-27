#!/usr/bin/env bash
# Run this ON THE PROXMOX HOST, as root, after create-model-vms.sh and
# download-models-to-host.sh. Mounts the host's model store read-only into
# every model-lab guest in manifest.tsv, at /opt/models:
#
#   mp0: /mnt/pve/glacier-01/models,mp=/opt/models,ro=1
#
# Why here and not in create-model-vms.sh: a bind mount of a host path can
# only be set by root@pam, never by the project's scoped API token (by
# design; see infra/proxmox/README.md). Read-only, so a guest can't alter
# or delete a model another guest (or a later rebuild) depends on.
#
# The guests are unprivileged, so they see the files as owned by "nobody";
# download-models-to-host.sh makes them world-readable for that reason.
# A running guest is restarted so the mount takes effect.
#
# Usage:
#   ./mount-model-store.sh [manifest.tsv]
#   MODEL_STORE=/some/other/dir ./mount-model-store.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

[[ $EUID -eq 0 ]] || { echo "Run as root." >&2; exit 1; }
MANIFEST="${1:-manifest.tsv}"
STORE="${MODEL_STORE:-/mnt/pve/glacier-01/models}"
[[ -d "$STORE" ]] || { echo "$STORE is missing -- run download-models-to-host.sh first." >&2; exit 1; }

while IFS=$'\t' read -r label vmid hostname ip mac cores mem_mb disk_gb hf_repo hf_file; do
    [[ "$label" =~ ^#.*$ || -z "$label" ]] && continue
    if ! pct config "$vmid" >/dev/null 2>&1; then
        echo "$label ($vmid): no such guest -- run create-model-vms.sh first" >&2
        continue
    fi
    [[ -f "$STORE/${hf_repo##*/}/$hf_file" ]] || echo "$label: warning, $STORE/${hf_repo##*/}/$hf_file not downloaded yet" >&2
    pct set "$vmid" -mp0 "$STORE,mp=/opt/models,ro=1"
    if pct status "$vmid" | grep -q running; then
        pct reboot "$vmid"
    fi
    echo "$label ($vmid): $STORE mounted read-only at /opt/models"
done < "$MANIFEST"
