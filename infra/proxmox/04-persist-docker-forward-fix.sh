#!/usr/bin/env bash
# Run this ON THE PROXMOX HOST, as root. Installs a systemd unit that
# reapplies the DOCKER-USER bridge-traffic-allow rule automatically after
# every host boot AND after Docker itself restarts (which rewrites its
# own chains and would otherwise silently drop the manual rule again).
#
# Without this, every reboot of proxmox01 silently breaks guest<->
# gateway/internet/LAN reachability again -- see known-bugs.md entry 18.
# This script is exactly what "make sure Proxmox rebuilds and runs
# correctly if it gets turned off accidentally" requires on the host
# side; the guest side is `onboot: 1` on each guest (already set via the
# API, see infra/proxmox/03-create-project-guest.sh and
# 01-create-tools-container.sh).
#
# Idempotent: safe to re-run.
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "Run as root." >&2; exit 1; }

UNIT_SRC="$(dirname "${BASH_SOURCE[0]}")/systemd/pve-docker-bridge-fix.service"
UNIT_DST="/etc/systemd/system/pve-docker-bridge-fix.service"

if ! command -v docker >/dev/null 2>&1; then
    echo "docker not found on this host -- this fix is specific to hosts that run Docker alongside Proxmox."
    echo "If this host doesn't run Docker, this script and its unit are not needed here."
    exit 0
fi

cp "$UNIT_SRC" "$UNIT_DST"
systemctl daemon-reload
systemctl enable pve-docker-bridge-fix.service
systemctl start pve-docker-bridge-fix.service
systemctl status --no-pager pve-docker-bridge-fix.service

echo
echo "Verify the rule is actually in place:"
echo "  iptables -L DOCKER-USER -n -v | grep vmbr0"
