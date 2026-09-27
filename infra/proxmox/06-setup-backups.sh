#!/usr/bin/env bash
# Run this ON THE PROXMOX HOST, as root. Sets up the simplest viable
# backup: a daily vzdump snapshot of the given guests, written to a
# DIFFERENT storage than where the live disks are, self-pruned to the last
# N copies so it never grows unbounded. Since 2026-09-27 the default target
# is `glacier-01`, a separate 7.2 TB disk, not `local` (the host's system
# disk): losing the thin pool under the guests (known-bugs.md #37) showed
# the backups are what everything else is restored from.
#
# This is NOT off-host/off-site backup -- a whole-host failure (disk
# death, host destroyed) loses both the live guests and these backups
# together. It protects against: accidental guest deletion, a botched
# `pct destroy`, loss or corruption of the thin pool holding the live
# disks, or "I need yesterday's state back" -- not against losing the
# physical machine. Say so explicitly if stronger (off-host) protection is
# actually needed; that's materially more infrastructure than this.
#
# Also installed: the timer runs 10 minutes after every boot as well as
# daily (known-bugs.md #20: this host is normally off at 03:30), and a
# failed run leaves a marker that every host login reports, along with
# any newest archive older than two days (known-bugs.md #37: the failed
# backup the day before the pool was lost went unnoticed).
#
# Idempotent: safe to re-run (overwrites the unit files, re-enables).
#
# Usage:
#   BACKUP_VMIDS="104 106" BACKUP_STORAGE=glacier-01 ./06-setup-backups.sh
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "Run as root." >&2; exit 1; }
command -v vzdump >/dev/null 2>&1 || { echo "vzdump not found -- run this on a Proxmox host." >&2; exit 1; }

VMIDS="${BACKUP_VMIDS:-104 106}"
STORAGE="${BACKUP_STORAGE:-glacier-01}"
SCRIPT_DIR="$(dirname "${BASH_SOURCE[0]}")"

echo "== ensure '$STORAGE' storage allows backup content =="
# Deliberately NOT using jq here -- it's guaranteed on the guests we
# explicitly installed it on, NOT guaranteed on the Proxmox host itself.
# grep/sed on raw JSON is uglier but has zero extra dependencies, which
# matters more for a script that needs to "just work" on any fresh host.
current=$(pvesh get "/storage/$STORAGE" --output-format json | grep -o '"content":"[^"]*"' | cut -d'"' -f4)
if [[ -z "$current" ]]; then
    echo "Could not determine current content types for '$STORAGE' -- check manually:" >&2
    echo "  pvesh get /storage/$STORAGE" >&2
    exit 1
fi
if [[ "$current" != *backup* ]]; then
    pvesh set "/storage/$STORAGE" --content "${current},backup"
    echo "added 'backup' to $STORAGE's content types (was: $current)"
else
    echo "$STORAGE already allows backup content ($current)"
fi
# a directory storage keeps vzdump archives in <path>/dump
storage_path=$(pvesh get "/storage/$STORAGE" --output-format json | grep -o '"path":"[^"]*"' | cut -d'"' -f4 || true)
[[ -n "$storage_path" ]] || { echo "'$STORAGE' has no path; this script expects a directory storage." >&2; exit 1; }
dump_dir="$storage_path/dump"

echo "== install systemd units =="
# Substitute the VMID list and storage into the service unit rather than
# hardcoding them -- BACKUP_VMIDS lets this script back up whatever this
# host is actually running when it's re-run for a different project set.
sed "s|^ExecStart=.*|ExecStart=/usr/bin/vzdump ${VMIDS} --storage ${STORAGE} --mode snapshot --compress zstd --prune-backups keep-last=7|" \
    "${SCRIPT_DIR}/systemd/pve-athenaeum-backup.service" > /etc/systemd/system/pve-athenaeum-backup.service
cp "${SCRIPT_DIR}/systemd/pve-athenaeum-backup.timer" /etc/systemd/system/pve-athenaeum-backup.timer
cp "${SCRIPT_DIR}/systemd/pve-athenaeum-backup-failed.service" /etc/systemd/system/pve-athenaeum-backup-failed.service

echo "== login warning (failed or stale backups) =="
sed "s|^STORAGE_DIR=.*|STORAGE_DIR=\"\${ATHENAEUM_BACKUP_DIR:-${dump_dir}}\"|" \
    "${SCRIPT_DIR}/motd/99-athenaeum-backup" > /etc/update-motd.d/99-athenaeum-backup
chmod 755 /etc/update-motd.d/99-athenaeum-backup
echo "installed; checks $dump_dir"

systemctl daemon-reload
systemctl enable pve-athenaeum-backup.timer
systemctl restart pve-athenaeum-backup.timer   # picks up a changed timer (OnBootSec)

echo
echo "Scheduled. Next run:"
systemctl list-timers pve-athenaeum-backup.timer --no-pager

echo
echo "Running one backup now to verify it actually works, not just that it's scheduled..."
systemctl start pve-athenaeum-backup.service || true
systemctl status --no-pager pve-athenaeum-backup.service || true
echo
echo "Resulting archives:"
ls -lh "$dump_dir" 2>/dev/null || pvesm list "$STORAGE" --content backup
echo
echo "Login warning, as it would print now (empty means all is well):"
/etc/update-motd.d/99-athenaeum-backup
