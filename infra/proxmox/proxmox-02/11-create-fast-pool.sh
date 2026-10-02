#!/usr/bin/env bash
# Run ON proxmox-02 as root. Creates the RAIDZ1 ZFS pool `fast-z1` from the
# four Samsung 950 PRO 512GB NVMe drives (the Amfeltec Squid carrier card in
# PCIe slot 7), caps ZFS's RAM cache, and registers the pool with Proxmox.
#
# DESTRUCTIVE: wipes every disk named on the command line. Refuses to run
# unless CONFIRM_WIPE=yes, and refuses any disk that is mounted, held by
# another device, or hosts / or /boot/efi. Always pass /dev/disk/by-id paths
# (nvmeXn1 names and PCI bus numbers changed when the Squid was added).
#
# Usage:
#   CONFIRM_WIPE=yes ./11-create-fast-pool.sh \
#     /dev/disk/by-id/nvme-Samsung_SSD_950_PRO_512GB_S2GMNX0H905304E \
#     /dev/disk/by-id/nvme-Samsung_SSD_950_PRO_512GB_S2GMNX0H701844X \
#     /dev/disk/by-id/nvme-Samsung_SSD_950_PRO_512GB_S2GMNX0H705539L \
#     /dev/disk/by-id/nvme-Samsung_SSD_950_PRO_512GB_S2GMNX0H705553H
#
# Tunables (env): POOL (fast-z1), ARC_MAX_BYTES (8 GiB), ZVOL_BLOCKSIZE (64k).
set -euo pipefail

POOL="${POOL:-fast-z1}"
ARC_MAX_BYTES="${ARC_MAX_BYTES:-8589934592}"
ZVOL_BLOCKSIZE="${ZVOL_BLOCKSIZE:-64k}"

[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 1; }
[ "$#" -ge 3 ] || { echo "need at least 3 /dev/disk/by-id paths for raidz1" >&2; exit 1; }
[ "${CONFIRM_WIPE:-}" = "yes" ] || { echo "set CONFIRM_WIPE=yes -- this erases: $*" >&2; exit 1; }
zpool list -H -o name 2>/dev/null | grep -qx "$POOL" && { echo "pool $POOL already exists" >&2; exit 1; }

root_disks="$( { lsblk -nsr -o NAME "$(findmnt -no SOURCE /boot/efi)"; lsblk -nsr -o NAME "$(findmnt -no SOURCE /)"; } | grep -E '^nvme[0-9]+n[0-9]+$|^sd[a-z]+$' || true)"
[ -n "$root_disks" ] || { echo "could not determine the OS disk; refusing to continue" >&2; exit 1; }

echo "== safety checks =="
real=()
for d in "$@"; do
    [ -e "$d" ] || { echo "no such device: $d" >&2; exit 1; }
    r="$(readlink -f "$d")"; base="$(basename "$r")"
    echo "$base  <-  $d"
    if echo "$root_disks" | grep -qx "$base"; then echo "REFUSING: $base hosts / or /boot/efi" >&2; exit 1; fi
    if [ -n "$(lsblk -no MOUNTPOINTS "$r" | tr -d ' \n')" ]; then echo "REFUSING: $base has a mounted filesystem" >&2; exit 1; fi
    if [ "$(ls "/sys/block/$base/holders" 2>/dev/null | wc -l)" != 0 ]; then echo "REFUSING: $base is held by another device" >&2; exit 1; fi
    real+=("$r")
done

echo "== wiping =="
for r in "${real[@]}"; do
    wipefs -a "$r" >/dev/null
    sgdisk --zap-all "$r" >/dev/null 2>&1 || true
    blkdiscard -f "$r" 2>/dev/null || echo "  (blkdiscard unsupported on $r, continuing)"
done
partprobe 2>/dev/null || true
udevadm settle

echo "== creating $POOL (raidz1, ashift=12) =="
zpool create -f \
    -o ashift=12 -o autotrim=on \
    -O compression=lz4 -O atime=off -O xattr=sa -O acltype=posixacl -O dnodesize=auto \
    -O mountpoint=none \
    "$POOL" raidz1 "$@"

# Code and state live on the redundant pool rather than the single OS NVMe.
zfs create -o mountpoint=/srv/athenaeum "$POOL/athenaeum"

echo "== capping ZFS ARC at ${ARC_MAX_BYTES} bytes =="
echo "options zfs zfs_arc_max=${ARC_MAX_BYTES}" > /etc/modprobe.d/zfs.conf
echo "$ARC_MAX_BYTES" > /sys/module/zfs/parameters/zfs_arc_max
update-initramfs -u -k all >/dev/null 2>&1

echo "== registering with Proxmox =="
if pvesm status --storage "$POOL" >/dev/null 2>&1; then
    echo "storage $POOL already registered"
else
    pvesm add zfspool "$POOL" --pool "$POOL" --content images,rootdir --sparse 1 --blocksize "$ZVOL_BLOCKSIZE"
fi

zpool status "$POOL"
zfs list -o name,used,avail,mountpoint -r "$POOL"
echo "arc_max now: $(cat /sys/module/zfs/parameters/zfs_arc_max)"
