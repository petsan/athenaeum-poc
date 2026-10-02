# proxmox-02 — build record

A second, separate Proxmox host (not clustered with `proxmox01`), built 2026-09-28 as a GPU compute box. Everything here was done by hand in one session; this file plus `10-` and `11-` in this directory are the recipe for rebuilding it.

## Hardware

| | |
|---|---|
| Board | ASUS WS C422 SAGE/10G (BIOS 2.17.1246) |
| CPU | Intel Xeon W-2155, 10 cores / 20 threads |
| RAM | 64GB DDR4-2933 |
| GPUs | 3× NVIDIA Quadro GV100 32GB (`10de:1dba`, audio `10de:10f2`), slots 1, 3, 5 |
| OS disk | Samsung 960 PRO 2TB NVMe (LVM: 96G root, 8G swap, ~1.7T `local-lvm` thin pool) |
| Fast pool | 4× Samsung 950 PRO 512GB NVMe on an Amfeltec Squid carrier (slot 7) -> ZFS `fast-z1`, RAIDZ1, ~1.31T usable |
| Not yet installed | a 4TB SATA SSD (planned; nothing depends on it) |
| Network | 192.168.0.99/24, gw/DNS 192.168.0.1, hostname `proxmox-02.home.arpa`, on-board Intel X550 10GbE |
| PVE | 9.2.20, kernel 7.0.14-19-pve (same PVE version as `proxmox01`) |

## BIOS settings that matter

Confirmed by the operator: VT-d **Enabled**, ACS Control **Enabled**, Above 4G Decoding **Enabled**. VMX must be on (KVM runs the VM). **Recommended but not confirmed as set:** ASPM options (PCH DMI, DMI Link, PEG, Native ASPM) Disabled; Secure Boot off / OS type Other OS; CSM off (it was temporarily enabled while getting the installer USB to boot). It boots UEFI (GRUB via shim, not systemd-boot — root is ext4/LVM, so `proxmox-boot-tool` is not in use). "First VGA 4G Decode" was left at its default; changing it was never tested.

**Gotcha that cost real time:** after adding hardware the onboard SATA controller (`00:17.0`) vanished from the PCI list — most likely disabled in BIOS at some point (inferred from its absence, not confirmed in the BIOS screen) — check *SATA controller: Enabled / AHCI* before assuming a new SATA drive is dead. Separately, the machine looked hung after the GPU rebind because the network cable had been unplugged during the reboot; check the cable before theorizing.

## PCIe topology (measured, not from a spec sheet)

The board uses PLX switches. One PEX 8747 (bus 17) feeds slot 7 (the Squid, which has its own PEX 8732 -> 4 NVMe) **and** one GPU; a second PEX 8747 (bus 65) feeds the other two GPUs. So two GPUs share one x16 uplink to the CPU, and the third GPU shares its uplink with the Squid. All three GPUs train at Gen3 x16. **Every GPU and every NVMe is in its own IOMMU group** (ACS Control did its job; no ACS-override kernel patch needed). PCI bus numbers changed when the Squid was added — always use vendor:device IDs and `/dev/disk/by-id`, never `nvmeXn1` or bus numbers, in config.

## Scripts (run on the host, as root)

| Script | What |
|---|---|
| `10-gpu-passthrough.sh` | blacklists nouveau/nvidia on the host, binds the three GV100s to `vfio-pci` by ID. Needs a reboot. |
| `11-create-fast-pool.sh` | **destructive** (needs `CONFIRM_WIPE=yes`): builds `fast-z1` (RAIDZ1, `ashift=12`, `autotrim=on`, lz4, `atime=off`, `xattr=sa`), caps ZFS ARC at 8GiB, registers the storage with `volblocksize=64k` (chosen for RAIDZ1 space efficiency over the 16k default), and creates the `fast-z1/athenaeum` dataset at `/srv/athenaeum`. |
| `20-create-gpu-model-vm.sh` | creates VMID 201 (`athenaeum-gpu-gv100`, `192.168.0.97`): Debian 12 cloud image, q35 + OVMF, 6 vCPU / 16GB / 64GB on `fast-z1`, one GV100 passed through. Refuses a GPU that isn't on `vfio-pci` or is the boot-display GPU. Two non-obvious settings, both learned the hard way: `X-PciMmio64Mb` widened to 128GB (OVMF's default 64-bit window is too small for a GV100's BAR) and the cloud-init drive on `scsi1` (`known-bugs.md` #22). |
| `21-provision-gpu-model-vm.sh` | run from an operator machine over SSH, two phases (`driver`, then `serve`): NVIDIA 535 DKMS driver + CUDA 11.8 toolkit, reboot, then a CUDA (`sm_70`) build of `llama-server` and the OLMo 3 7B Q4_K_M model as a systemd service on `:8080`. |

## GPU model server (VMID 201)

Registered in the repo-root `elastic_workers.yaml` as `proxmox02-gv100`, so `elastic_workers.py` health-checks it live on every call and the model-backed code uses it when it answers, falling back to the CPU model-lab guests when it doesn't. Measured: ~97 tok/s generation, PCIe Gen3 x16 to the guest, ~6.6GB of 32GB VRAM used. Uses 6 of 20 threads and 16GB of 62GB — well inside the 80% cap (16 threads / ~50GB). Login: `debian@192.168.0.97` with the `athenaeum_poc` key (passwordless sudo, cloud-init default). Its own SSH host key is new, so clear any stale `known_hosts` entry if the VM is rebuilt.

**VM 202** (`athenaeum-gpu-qwen3-8-27b`, `192.168.0.96`, GPU `67:00`, 8 vCPU / 20GB / 96G disk) serves **Qwen3.8-27B Q8_0** (`lmstudio-community/Qwen3.8-27B-GGUF`) on `http://192.168.0.96:8080/v1`, LAN-reachable for LM Studio or any OpenAI-compatible client; ~19 tok/s, **context now 65536 with `-np 1` (VRAM 30.9/32.7GiB; see `docs/progress.md` §44 addendum for the measured sweep and the 128k q8_0 option)** (verified 2026-09-28, see `docs/progress.md` §43). Built with `20-` then `21-` (`HF_REPO`/`HF_FILE`/`CTX=16384`/`LLAMA_ARGS=--jinja`); **not registered in `elastic_workers.yaml`** and reboot-untested. **VM 203** (`athenaeum-gpu-muse-bonsai`, `192.168.0.95`, GPU `68:00` — the boot-display GPU, passed through with `ALLOW_BOOT_VGA=1` after confirming the host had no console on it; 6 vCPU / 12GB / 64G) runs two servers: **Muse-Glimmer-30B Q4_K_M** (`meta-models/Muse-Glimmer-30B-GGUF`, stock llama.cpp) on `http://192.168.0.95:8080/v1` (~30.6 tok/s) and **Ternary-Bonsai-27B PQ2_0** (`prism-ml/Ternary-Bonsai-27B-gguf`, PrismML fork in `/opt/llama.cpp-prism`, unit `llama-server-bonsai`) on `http://192.168.0.95:8081/v1` (~51.4 tok/s); VRAM 25.1/32.8GiB together. All three GPUs are now assigned. See `docs/progress.md` §43 for the failures hit (fork CMake, wrong Q2_0 layout).

## Access

Root SSH with a dedicated, passphrase-less key on the operator's Windows machine (`~/.ssh/proxmox02`, comment `claude-code@proxmox-02`) — deliberately separate from the `athenaeum_poc` key used for LXC 104. **That key is root on this host**; revoke it by deleting its line from `/root/.ssh/authorized_keys`. No scoped API token/role/pool has been created here (`00-bootstrap-identity.sh` hardcodes `proxmox01`'s storage names and node and would need parameterizing first); nothing needs one yet since Athenaeum runs directly on the host — see below.

## Athenaeum here

Installed **directly on the host OS** at `/srv/athenaeum` (on the RAIDZ1 dataset, so code and state survive one drive failure), by explicit user decision on 2026-09-28 removing the old "never on the Proxmox host" rule (`CLAUDE.md`). `python3-pytest` was the only package added. `execution_sandbox.enabled` stays `false`. The tree was copied from a `git archive HEAD` of the repo (so it contains no secrets or uncommitted files), then two working-tree changes were copied on top (`agents.py`, `elastic_workers.yaml`) — re-copy the repo rather than editing on the host. Test logs from the bring-up (`test-run-*.log`) are left in `/srv/athenaeum`. **Full suite: 248/248 passed** (3m04s, no skips, GPU worker reachable). Run it with `cd /srv/athenaeum && python3 -m pytest -q`.

Preflight (`scripts/preflight_check.py`) on this host: everything passes except scenario 4, which fails only because the script has no cgroups-v2 branch (`known-bugs.md` #25 — the real fork-containment pytest passes here). The `RLIMIT_CPU` repro under `unshare --fork` passed here, unlike the earlier `proxmox01` LXC run on kernel build `-17` — but what differs (bare host vs. container, kernel build, `util-linux`) was not isolated, so don't treat it as proof `RLIMIT_CPU` is safe to rely on (`security-review-sandbox.md` §7.4).

## Not covered / open

- No off-host backup, and **no backup of any kind is configured on this host yet** — including VM 201 (`06-setup-backups.sh` was written for `proxmox01`'s guests and not run here). `fast-z1` protects against one drive failing, not against deletion, corruption, or losing the machine. VM 201 is rebuildable from `20-`/`21-` (about 10 minutes plus a model download), which is the only recovery path today.
- **Not drilled through a cold boot:** only the `vfio-pci` binding has been seen surviving a reboot. VM 201's `onboot`, `fast-z1`'s automatic import, the ARC cap, and the `llama-server` unit were set up correctly but not observed after one.
- The Amfeltec Squid is the fourth-drive-sharing uplink noted above; a heavy NVMe workload and that GPU's host traffic compete for one x16 link.
- 4TB SATA SSD not installed; BIOS SATA controller state above needs fixing first.

> **2026-10-02 update:** VM 202 now holds **all three GPUs** (`hostpci0` `67:00`, `hostpci1` `1f:00`, `hostpci2` `68:00`) and runs Qwen3.8-27B **Q4_K_M** with MTP speculative decoding (`-c 65536 -np 2`), so VMs 201 and 203 cannot start while it runs. Undo with VM 202 stopped: `qm set 202 --delete hostpci1,hostpci2`. Config backups: `/root/backup-pve-config-20261002/` on the host. Details and measurements: `docs/progress.md` §45 addendum.

> **2026-10-02 (later):** VM 202 is the **only VM to run**: 3 GPUs, **46,592MB RAM** (all available less ~10% headroom), two llama-servers (Q4_K_M pinned to GPU 0 on `:8080`, Q8_0 on GPUs 1+2 on `:8081`, `-c 262144 -np 2` each, MTP). VMs 201 and 203 are on **cold standby** (stopped, `onboot 0`, configs untouched). Revive one: `qm shutdown 202; qm set 202 --delete hostpci1,hostpci2; qm start <id>`. VM 202 does not autostart with the host.
