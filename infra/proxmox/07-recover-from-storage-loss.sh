#!/usr/bin/env bash
# Run this ON THE PROXMOX HOST, as root. Recovers guests whose disks were
# on a storage that has been lost or rebuilt (2026-09-27: the thin pool
# behind `local-thin-multi` was destroyed and its disks reused for a new,
# empty pool, `local-thin-multi-01`; every Athenaeum guest pointed at
# disks that no longer existed). It automates what was done by hand then:
#
#   1. check the replacement storage exists, is active, and holds container disks;
#   2. give the project's API identity the same role on it as on the old one;
#   3. find every guest whose disk is missing ("broken");
#   4. restore each broken guest from its newest good vzdump backup onto the
#      replacement storage (the old config is saved first), then start it;
#   5. list broken guests with no backup: those are rebuilt from their recipe
#      (for the model-lab guests, infra/proxmox/model-lab/), not restored;
#   6. optionally retire the old storage entry and its ACLs, once nothing uses it.
#
# It never creates or wipes disks, LVM volume groups, or thin pools: which
# physical disks back a pool is the owner's decision. Create the pool and
# its storage entry first (e.g. `pvesm add lvmthin <id> --vgname <vg>
# --thinpool <pool> --content rootdir,images`), then run this.
#
# DRY RUN BY DEFAULT: without --apply it only reports what it would do.
# A healthy guest is never restored over unless ALLOW_HEALTHY=1.
#
# Usage:
#   TARGET_STORAGE=local-thin-multi-01 ./07-recover-from-storage-loss.sh           # report
#   TARGET_STORAGE=local-thin-multi-01 ./07-recover-from-storage-loss.sh --apply   # do it
#
# Settings (environment):
#   TARGET_STORAGE    required; the lvmthin (or other rootdir-capable) storage to restore onto
#   RESTORE_VMIDS     guests to consider, in start order (default: "106 104", the tools box first)
#   BACKUP_DIRS       where to look for archives (default: "/var/lib/vz/dump /mnt/pve/glacier-01/dump")
#   OLD_STORAGE       the lost storage's id; if set, its entry and ACLs are removed once no guest uses it
#   REMOVE_VMIDS      broken guests with no backup whose stale configs to move out of /etc/pve (kept in
#                     the recovery dir), e.g. the model-lab guests before rebuilding them. Only these:
#                     other projects' guests on the host are reported, never touched.
#   GRANT_ACL=1       grant ROLE on TARGET_STORAGE to PROJECT_USER and PROJECT_TOKEN (default 1)
#   ROLE, PROJECT_USER, PROJECT_TOKEN   default ClaudeAgent, claude@pve, claude@pve!athenaeum
set -euo pipefail

APPLY=0
[[ "${1:-}" == "--apply" ]] && APPLY=1
[[ $EUID -eq 0 ]] || { echo "Run as root." >&2; exit 1; }
command -v pct >/dev/null 2>&1 || { echo "pct not found -- run this on a Proxmox host." >&2; exit 1; }

TARGET="${TARGET_STORAGE:?set TARGET_STORAGE to the replacement storage id}"
VMIDS="${RESTORE_VMIDS:-106 104}"
BACKUP_DIRS="${BACKUP_DIRS:-/var/lib/vz/dump /mnt/pve/glacier-01/dump}"
ROLE="${ROLE:-ClaudeAgent}"
PROJECT_USER="${PROJECT_USER:-claude@pve}"
PROJECT_TOKEN="${PROJECT_TOKEN:-claude@pve!athenaeum}"
RECOVERY_DIR="/root/recovery-$(date +%Y%m%d-%H%M%S)"

run() {   # print every change; make it only with --apply
    echo "  + $*"
    if [[ $APPLY -eq 1 ]]; then "$@"; fi
}

# A guest's disk volumes (rootfs, mpN), skipping bind mounts (host paths).
volumes_of() {
    sed -n -E 's/^(rootfs|mp[0-9]+): ([^,]+).*/\2/p' "/etc/pve/lxc/$1.conf" | grep -v '^/' || true
}

# Broken = some disk volume's storage is not active, or the storage doesn't
# list the volume. Not "its device node exists": a template's LVs are never
# activated, so that test called every healthy template broken (found in
# this script's first dry run, on another project's templates).
is_broken() {
    local vol store
    for vol in $(volumes_of "$1"); do
        store="${vol%%:*}"
        pvesm status --storage "$store" 2>/dev/null | awk 'NR>1 {print $3}' | grep -qx active || return 0
        pvesm list "$store" 2>/dev/null | awk 'NR>1 {print $1}' | grep -qxF "$vol" || return 0
    done
    return 1
}

# Newest archive for a guest whose log (if any) records a finished backup.
newest_backup() {
    local archive log
    for archive in $(ls -1 $(printf '%s/vzdump-lxc-'"$1"'-*.tar.zst ' $BACKUP_DIRS) 2>/dev/null \
                     | awk -F/ '{print $NF "\t" $0}' | sort | cut -f2 | tac); do
        log="${archive%.tar.zst}.log"
        if [[ ! -f "$log" ]] || grep -q "Finished Backup of VM $1" "$log"; then
            echo "$archive"
            return
        fi
    done
}

[[ $APPLY -eq 1 ]] && echo "== APPLYING changes ==" || echo "== DRY RUN: nothing will change (pass --apply) =="

echo "== 1. target storage '$TARGET' =="
if ! pvesm status --storage "$TARGET" 2>/dev/null | awk 'NR>1 {print $3}' | grep -qx active; then
    echo "'$TARGET' is missing or not active. Create the pool and its storage entry first." >&2
    exit 1
fi
# grep/cut on raw JSON, no jq: jq isn't guaranteed on the host (known-bugs #19)
content=$(pvesh get "/storage/$TARGET" --output-format json | grep -o '"content":"[^"]*"' | cut -d'"' -f4 || true)
if [[ "$content" != *rootdir* ]]; then
    echo "content is '${content:-unset}'; container disks need rootdir"
    run pvesm set "$TARGET" --content rootdir,images
else
    echo "active, content: $content"
fi

echo "== 2. access for $PROJECT_TOKEN =="
if [[ "${GRANT_ACL:-1}" == "1" ]]; then
    # this host needs the SAME grant on the token and its user, or the
    # token resolves to nothing (see deployment-playbook.md, section 1)
    if pveum acl list --output-format json | grep -q "\"path\":\"/storage/$TARGET\""; then
        echo "an ACL on /storage/$TARGET already exists; check it: pveum acl list | grep $TARGET"
    else
        run pveum acl modify "/storage/$TARGET" -roles "$ROLE" -users "$PROJECT_USER"
        run pveum acl modify "/storage/$TARGET" -roles "$ROLE" -tokens "$PROJECT_TOKEN"
    fi
else
    echo "skipped (GRANT_ACL=0)"
fi

echo "== 3-4. guests =="
restored=() unbacked=() removed=()
for vmid in $VMIDS; do
    if [[ ! -f "/etc/pve/lxc/$vmid.conf" ]]; then
        echo "$vmid: no config on this host; nothing to replace (restoring needs no --force)"
    elif ! is_broken "$vmid"; then
        if [[ "${ALLOW_HEALTHY:-0}" != "1" ]]; then
            echo "$vmid: disks present, healthy; left alone (ALLOW_HEALTHY=1 to restore anyway)"
            continue
        fi
        echo "$vmid: healthy, but ALLOW_HEALTHY=1: restoring over it"
    fi
    archive=$(newest_backup "$vmid")
    if [[ -z "$archive" ]]; then
        echo "$vmid: BROKEN and no good backup in: $BACKUP_DIRS"
        unbacked+=("$vmid")
        continue
    fi
    echo "$vmid: restoring from $archive"
    run mkdir -p "$RECOVERY_DIR"
    [[ -f "/etc/pve/lxc/$vmid.conf" ]] && run cp "/etc/pve/lxc/$vmid.conf" "$RECOVERY_DIR/$vmid.conf.before"
    if [[ -f "/etc/pve/lxc/$vmid.conf" ]] && pct status "$vmid" 2>/dev/null | grep -q running; then
        run pct stop "$vmid"
    fi
    run pct restore "$vmid" "$archive" --storage "$TARGET" --force
    restored+=("$vmid")
done
for vmid in "${restored[@]}"; do    # in RESTORE_VMIDS order: the tools box first
    run pct start "$vmid"
done

echo "== 5. broken guests with no backup =="
# every guest on the host, not only RESTORE_VMIDS, so nothing broken goes unnoticed
for conf in /etc/pve/lxc/*.conf; do
    vmid=$(basename "$conf" .conf)
    [[ " ${restored[*]} " == *" $vmid "* ]] && continue
    is_broken "$vmid" || continue
    [[ " ${unbacked[*]} " == *" $vmid "* ]] || unbacked+=("$vmid")
done
if [[ ${#unbacked[@]} -eq 0 ]]; then
    echo "none"
else
    for vmid in "${unbacked[@]}"; do
        echo "$vmid ($(sed -n 's/^hostname: //p' "/etc/pve/lxc/$vmid.conf")): rebuild from its recipe"
        if [[ " ${REMOVE_VMIDS:-} " == *" $vmid "* ]]; then
            run mkdir -p "$RECOVERY_DIR"
            run cp "/etc/pve/lxc/$vmid.conf" "$RECOVERY_DIR/$vmid.conf.removed"
            run rm "/etc/pve/lxc/$vmid.conf"
            removed+=("$vmid")
        fi
    done
    echo "model-lab guests: infra/proxmox/model-lab/ recreates them; list them in REMOVE_VMIDS to clear the stale configs first"
fi

echo "== 6. old storage =="
if [[ -n "${OLD_STORAGE:-}" ]]; then
    # Guests still using it once this run is done: restored and removed ones
    # no longer count (so a dry run predicts what --apply would find).
    remaining=()
    for conf in $(grep -l -E "^(rootfs|mp[0-9]+|scsi[0-9]+|virtio[0-9]+|sata[0-9]+|ide[0-9]+|efidisk0|tpmstate0): ${OLD_STORAGE}:" \
                  /etc/pve/lxc/*.conf /etc/pve/qemu-server/*.conf 2>/dev/null || true); do
        vmid=$(basename "$conf" .conf)
        [[ " ${restored[*]} ${removed[*]} " == *" $vmid "* ]] || remaining+=("$vmid")
    done
    if [[ ${#remaining[@]} -gt 0 ]]; then
        echo "still used by ${remaining[*]}; left in place (rebuild or list them in REMOVE_VMIDS first)"
    else
        run pvesm remove "$OLD_STORAGE"
        run pveum acl delete "/storage/$OLD_STORAGE" -roles "$ROLE" -users "$PROJECT_USER"
        run pveum acl delete "/storage/$OLD_STORAGE" -roles "$ROLE" -tokens "$PROJECT_TOKEN"
    fi
else
    echo "skipped (set OLD_STORAGE to retire the lost storage's entry)"
fi

echo
echo "== summary =="
pct list | awk -v ids=" ${VMIDS} ${unbacked[*]} " 'NR==1 || index(ids, " " $1 " ")'
[[ -d "$RECOVERY_DIR" ]] && echo "saved configs: $RECOVERY_DIR"
cat <<EOF

Next, from a workstation: infra/proxmox/05-verify.sh (API, ping, SSH, egress).
A restored guest is as of its backup: re-sync anything newer (for 104, the
code from git). If backups should cover more guests, re-run 06-setup-backups.sh.
EOF
