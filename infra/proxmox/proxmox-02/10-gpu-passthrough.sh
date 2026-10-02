#!/usr/bin/env bash
# Run ON proxmox-02 as root. Binds the three Quadro GV100s (and their HDMI
# audio functions) to vfio-pci at boot so they can be passed through to VMs,
# and keeps the host's own drivers (nouveau/nvidia) off them.
#
# This is exactly what was applied by hand on 2026-09-28, recorded so the
# host can be rebuilt without a live session. Requires a reboot to take effect.
#
# Binds by vendor:device ID (10de:1dba GPU, 10de:10f2 audio), NOT by PCI
# address: bus numbers on this board shifted when the Amfeltec Squid carrier
# was added in slot 7 (one GPU moved 1a:00 -> 1f:00), and IDs don't.
#
# Prerequisites (BIOS, not scriptable): VT-d enabled, ACS Control enabled,
# Above 4G Decoding enabled. The PVE kernel already enables the IOMMU by
# default -- no intel_iommu= boot option was needed here (86 IOMMU groups
# present on first boot, each GV100 alone in its own group).
set -euo pipefail

[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 1; }

if grep -rqs vfio /etc/modprobe.d /etc/modules /etc/modules-load.d; then
    echo "existing vfio config found -- refusing to overwrite:" >&2
    grep -rn vfio /etc/modprobe.d /etc/modules /etc/modules-load.d >&2
    exit 1
fi

cat > /etc/modprobe.d/blacklist-nvidia-host.conf <<'EOF'
blacklist nouveau
blacklist nvidia
blacklist nvidiafb
blacklist nvidia_drm
EOF

cat > /etc/modprobe.d/vfio.conf <<'EOF'
options vfio-pci ids=10de:1dba,10de:10f2
softdep nouveau pre: vfio-pci
softdep nvidia pre: vfio-pci
EOF

printf 'vfio\nvfio_iommu_type1\nvfio_pci\n' > /etc/modules-load.d/vfio.conf

update-initramfs -u -k all
echo "written. Reboot, then verify:  lspci -nnk -d 10de:   (every function should show 'Kernel driver in use: vfio-pci')"
echo "and that each GV100 sits alone in its IOMMU group."
