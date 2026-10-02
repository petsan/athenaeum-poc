# proxmox-02 — open work (handoff list, written 2026-09-28)

> **UPDATE 2026-10-02 — read `docs/progress.md` §44 first.** Since this file was written: GPU VMs 202 (Qwen3.8-27B) and 203 (Muse-Glimmer-30B + Ternary-Bonsai-27B) were built, all three GPUs are now assigned, host RAM is ~4GB free, preflight scenario 4 (§6 below) is **done**, the cap is 100% (§9 below), and one unattended reboot showed VMs/pool/ARC/llama-servers coming back (§3 below is therefore *partly* observed — still do it attended). Verification endpoints for §0: `curl http://192.168.0.{97:8080,96:8080,95:8080,95:8081}/health`. Backups (§2) are still the top open item.


Written so a cold session can pick up without the conversation. Facts here were observed in the bring-up session unless marked **(inferred)** or **(not tested)**. Context: `README.md` in this directory, `docs/progress.md` §41 and §26, `known-bugs.md` #21–25.

## 0. Before anything: verify current state, don't trust this file

- `ping 192.168.0.99`; `ssh -i ~/.ssh/proxmox02 root@192.168.0.99` (Bash tool, not PowerShell — `known-bugs.md` #24).
- On the host: `zpool list fast-z1` (ONLINE?), `qm status 201`, `lspci -nnk -d 10de:1dba | grep -c vfio-pci` (3?), `systemctl --failed`.
- `curl -s -o /dev/null -w "%{http_code}\n" http://192.168.0.97:8080/health` (200?).
- The host may be powered off; if so that's normal — ask the user to power it on.

## 1. (Done: committed as 3f83a97 on 2026-10-02) Decide about the uncommitted work

Nothing from the bring-up is committed. Changed: `CLAUDE.md`, `README.md`, `deployment-playbook.md`, `docs/progress.md`, `elastic_workers.yaml`, `infra/proxmox/README.md`, `known-bugs.md`, `security-review-sandbox.md`, `src/athenaeum_brain/agents.py` (the `[-200:]` fix); new: `infra/proxmox/proxmox-02/`. The other `M` files in `git status` are file-mode-only flips (0755→0644, no content change) and the `.jpg` is unrelated — don't sweep them into the commit. Ask before committing/pushing.

## 2. Backups — highest priority, none exist on proxmox-02

- `fast-z1` is RAIDZ1: survives one drive failing, **not** deletion, corruption, a bad `zpool` command, or losing the box. VM 201 and `/srv/athenaeum` are unprotected.
- `infra/proxmox/06-setup-backups.sh` was written for `proxmox01`'s guests; not run here. Check what it hardcodes (node name, guest IDs, `local` storage) before reusing.
- Options to weigh with the user: (a) `vzdump` VM 201 to `local` (host root fs is ~98GB — a 64GB sparse VM disk compresses well, but check size); (b) ZFS snapshots of `fast-z1/athenaeum` (nothing installed for this yet); (c) anything off-host — the 4TB SATA SSD, once working, could be a separate-device target but is still the same machine.
- Whatever is built: include an `OnBootSec=~10min` trigger, because this host is not always on (`known-bugs.md` #20). That same fix is still **unapplied on proxmox01** too (§26).
- State the scope plainly in docs when done: on-host backups don't cover losing the host.

## 3. Cold-boot drill — only the vfio binding has been observed surviving a reboot

Reboot the host, then check, and record results in `docs/progress.md` (§26 says "closed" only once observed):
- `fast-z1` imported automatically and `/srv/athenaeum` mounted; `cat /sys/module/zfs/parameters/zfs_arc_max` = 8589934592.
- VM 201 started by itself (`onboot: 1`) — and **the GV100 initialized in the guest** (`nvidia-smi -L` inside it). Note Proxmox printed a harmless-looking "failed to reset PCI device" (GV100 has no per-device reset; reset method is `bus`); a *second* start after the VM has run once is the untested case.
- `systemctl is-active llama-server` in the VM and `/health` = 200.
- Host `systemctl --failed` empty; network up (the cable was the cause of the earlier scare).

## 4. The 4TB SATA SSD — never detected

- The chipset SATA controller (`00:17.0`) was in `lspci -tv` at first boot and later missing entirely **(inferred: disabled in BIOS)**. In BIOS (F7 Advanced Mode) find the SATA controller setting under PCH storage/SATA config; set Enabled, AHCI. Confirm `lspci -s 00:17.0` and `lsblk` on the host. Also check the SATA data and power cables.
- Then decide its role with the user (bulk model weights? backup target? separate pool?). Identify it by `/dev/disk/by-id` serial and size; **never wipe it without the user confirming the exact device**. `11-create-fast-pool.sh` shows the guard pattern (refuses OS disk / mounted / held disks, needs `CONFIRM_WIPE=yes`).

## 5. BIOS settings recommended but never confirmed

ASPM off (PCH DMI, DMI Link, PEG, Native ASPM); CSM off; Secure Boot off / Other OS. Confirmed by the user: VT-d, ACS Control, Above 4G Decoding. "First VGA 4G Decode" left at default. Low urgency; record actual values when next in BIOS.

## 6. Fix `scripts/preflight_check.py` scenario 4 for cgroups v2 (`known-bugs.md` #25)

- `scenario_fork_containment` (~line 187–196) only checks `/sys/fs/cgroup/pids` (v1), so it reports FAIL on any v2-only host even though `tests/test_sandbox.py::test_scenario_4_fork_containment_via_cgroups` passes there.
- Mirror what `sandbox.py` does (`_cgroup_pids_version()`, `_make_pids_cgroup()`; v2 needs `pids` in the parent's `cgroup.subtree_control`). Then re-run preflight on proxmox-02 **and** in LXC 104 on proxmox01, update `security-review-sandbox.md` §7.4, close #25.
- `execution_sandbox.enabled` stays `false` regardless.

## 7. Scoped Proxmox access for proxmox-02 — deliberately not done

Nothing needs it yet (Athenaeum runs on the host; root SSH is used). If it becomes needed: parameterize `infra/proxmox/00-bootstrap-identity.sh` first (it defaults `NODE` to `proxmox01` and hardcodes `/storage/local-thin-multi`; proxmox-02's storages are `local`, `local-lvm`, `fast-z1`), run it on the host as root, keep the token secret out of chat and out of git (gitignored env file), then optionally register with `02-register-project.sh` (needs proxmox01's tools container `192.168.0.151`, i.e. proxmox01 powered on). Least privilege: grow the role only when a real permission error demands it.

## 8. Newly possible work — worth raising with the user, not assumed

- **Tasks 21/22 (GPU-vs-CPU output equivalence)** were listed as "genuinely blocked — no GPU". A real GPU-backed server (VM 201) and CPU servers (proxmox01 model-lab) now serve the same model; this may be unblocked. **(not investigated)** — check `acceptance-criteria.md` for what those tasks actually require before claiming so.
- **Two more GV100s (`67:00`, `68:00`) are bound to vfio and unused.** `68:00` is the boot-display GPU (`boot_vga=1`) — avoid it for passthrough unless the host framebuffer is disabled. `1f:00` is used by VM 201. `67:00` is a clean candidate for another VM. A 32B model at Q4 should fit in one 32GB GV100 **(estimate, not tested)** — the repo has a one-off OLMo 3 32B guest on proxmox01 (`192.168.0.167`, was down during the session).
- **The "auto-update mechanism" decision in §26** (auto `git pull` on a guest vs Docker+watchtower) assumed Athenaeum runs in a guest; it now can run on the host — reconsider with the user before building either. Current install is a `git archive HEAD` copy plus two hand-copied files; re-copy from the repo rather than editing on the host.
- **`RLIMIT_CPU` under `unshare --fork` passed on proxmox-02 but failed in proxmox01's LXC** (both kernel 7.0.14, builds `-19` vs `-17`). Not isolated: bare host vs container vs build vs `util-linux`. An LXC on proxmox-02 would separate the first two variables. Don't change `sandbox.py`'s wall-clock-kill-as-primary design on this evidence.

## 9. Housekeeping / accuracy

- `CLAUDE.md` "Current status" still says the cold-boot drill hasn't been done for the *proxmox01* stack, but `docs/progress.md` §26 records it as done 2026-09-22 (with the backup-timer gap found). Reconcile.
- Host leftovers: `/root/11-create-fast-pool.sh`, `/root/20-create-gpu-model-vm.sh`, `/root/athenaeum_poc.pub`, `/root/vm-images/` (334MB Debian cloud image), `/srv/athenaeum/test-run-*.log`. The scripts are in the repo; the image is what `20-` reuses if present.
- The dedicated root key `~/.ssh/proxmox02` is passphrase-less. Revoke by deleting its line in `/root/.ssh/authorized_keys` on the host when no longer wanted. VM 201 trusts the `athenaeum_poc` key for `debian`.
- Network: `192.168.0.99` (host) and `.97` (VM 201) were chosen because ARP showed nothing there; neither was checked against the router's DHCP pool. Confirm/reserve them. `.199` is used as a deliberately dead address by tests — never assign it.
- Resource budget (cap raised to 100% on 2026-09-28, §42: 20 threads, ~62GB total — but leave headroom for the host OS + ZFS ARC since Athenaeum runs on this host): VM 201 uses 6 threads / 16GB. Recheck live numbers before adding guests.
- The Amfeltec Squid shares one x16 uplink to the CPU with the GPU at `1f:00` (measured PLX topology); revisit only if heavy NVMe I/O and that GPU's host traffic contend.

## 10. Working notes for the next session

- Remote commands: Bash tool with quoted heredocs; PowerShell mangles ssh quoting and prepends a BOM (`known-bugs.md` #24). This Windows machine has no local Python; run Python on a host/guest.
- Athenaeum on proxmox-02: `cd /srv/athenaeum && python3 -m pytest -q` (≈3 min; live-model tests depend on proxmox01's model-lab guests `192.168.0.161`–`.166` being up). Not pip-installed: use pytest or `PYTHONPATH=src`.
- VM rebuild: `20-create-gpu-model-vm.sh` then `21-provision-gpu-model-vm.sh driver`, wait for reboot, `... serve` (~10 min plus model download).
- A user message mid-session was pure keystroke noise and was ignored; if something similar reappears, ask rather than guess.
