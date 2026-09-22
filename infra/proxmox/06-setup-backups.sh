#!/usr/bin/env bash
# Run this ON THE PROXMOX HOST, as root. Sets up the simplest viable
# backup: a daily vzdump snapshot of the given guests, written to a
# DIFFERENT storage (`local`, the host's root filesystem) than where the
# live disks actually are (`local-thin-multi`), self-pruned to the last
# N copies so it never grows unbounded.
#
# This is NOT off-host/off-site backup -- a whole-host failure (disk
# death, host destroyed) loses both the live guests and these backups
# together. It protects against: accidental guest deletion, a botched
# `pct destroy`, LVM-thin pool corruption affecting only the live copy,
# or "I need yesterday's state back" -- not against losing the physical
# machine. Say so explicitly if stronger (off-host) protection is
# actually needed; that's materially more infrastructure than this.
#
# Idempotent: safe to re-run (overwrites the unit files, re-enables).
#
# Usage:
#   BACKUP_VMIDS="104 106" ./06-setup-backups.sh
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "Run as root." >&2; exit 1; }
command -v vzdump >/dev/null 2>&1 || { echo "vzdump not found -- run this on a Proxmox host." >&2; exit 1; }

VMIDS="${BACKUP_VMIDS:-104 106}"
SCRIPT_DIR="$(dirname "${BASH_SOURCE[0]}")"

echo "== ensure 'local' storage allows backup content =="
current=$(pvesh get /storage/local --output-format json | jq -r '.content')
if [[ "$current" != *backup* ]]; then
    pvesh set /storage/local --content "${current},backup"
    echo "added 'backup' to local storage's content types (was: $current)"
else
    echo "local storage already allows backup content"
fi

echo "== install systemd units =="
# Substitute the VMID list into the service unit rather than hardcoding
# 104/106 forever -- BACKUP_VMIDS lets this script back up whatever this
# host is actually running when it's re-run for a different project set.
sed "s/^ExecStart=.*/ExecStart=\/usr\/bin\/vzdump ${VMIDS} --storage local --mode snapshot --compress zstd --prune-backups keep-last=7/" \
    "${SCRIPT_DIR}/systemd/pve-athenaeum-backup.service" > /etc/systemd/system/pve-athenaeum-backup.service
cp "${SCRIPT_DIR}/systemd/pve-athenaeum-backup.timer" /etc/systemd/system/pve-athenaeum-backup.timer

systemctl daemon-reload
systemctl enable --now pve-athenaeum-backup.timer

echo
echo "Scheduled. Next run:"
systemctl list-timers pve-athenaeum-backup.timer --no-pager

echo
echo "Running one backup now to verify it actually works, not just that it's scheduled..."
systemctl start pve-athenaeum-backup.service
systemctl status --no-pager pve-athenaeum-backup.service
echo
echo "Resulting archives:"
ls -lh /var/lib/vz/dump/ 2>/dev/null || pvesm list local --content backup
