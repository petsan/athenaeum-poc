# Athenaeum

Slow, deep-reasoning, memory-resident knowledge system: **Body** (infrastructure, `src/athenaeum_body/`) and **Brain** (cognition, `src/athenaeum_brain/`, seven Master Agents). This repo is a proof-of-work, not the finished system. **Full previous CLAUDE.md (long history) is archived at `docs/archive/CLAUDE-md-full-2026-10-03.md` — read only if needed.**

## Read first
1. `docs/progress.md` — checkpoint. **§44 + §46 = current infra state**; §26 = open-work checklist.
2. `known-bugs.md` (27 entries; check before sandbox/CAS/demo/Proxmox-networking work — networking: `iptables -L FORWARD` first).
3. `docs/body-design.md`, `docs/brain-design.md`, `security-review-sandbox.md` (required before touching `sandbox.py`), `deployment-playbook.md` + `infra/proxmox/` (executable setup scripts; `infra/proxmox/proxmox-02/` has the GPU-VM, download, benchmark-support and config-backup scripts).

## Principles
Verify empirically, don't trust notes (hosts are often powered off — check real state first) · least privilege, expand only on a concrete error · root-cause, don't work around (minimal repros) · infra and decisions live in the repo, not in chat · state scope honestly (fixed ≠ tested ≠ reasoned) · confirm before hard-to-reverse or outward-facing actions · keep `docs/progress.md` and this file current, briefly.

## Hard constraints
- CPU/RAM cap: **100%** of a host (explicit user decisions; leave headroom on hosts that also run Athenaeum).
- Athenaeum may be installed directly on a Proxmox host OS (rule removed 2026-09-28; risk remains).
- `execution_sandbox.enabled` stays **false** unless every scenario in `security-review-sandbox.md` passes via `scripts/preflight_check.py` on that host.
- **No paid or metered external services** (enforced in `config.py`).
- Before calling a task done: run `pytest -q` (248/248 on proxmox-02's host) and update `docs/progress.md`.

## User rules (2026-10-03)
- **Never push models or images** unless told (`.gitignore` blocks `*.gguf *.safetensors *.bin` and image types; the architecture jpg is local-only in `docs/images/`).
- **Git: keep branches separate.** GitHub `master` holds a different line of work (2026-09-27, 177 files) — do **not** merge or force-push it. Push ours with `git push origin master:ops/proxmox-02-03-2026-10`. Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- **VMIDs:** proxmox-01 = 100–199, proxmox-02 = 200–299, proxmox-03 = 300–399.
- **IP plan (gradual):** same `192.168.0.0/24`. Hosts `proxmox-NN` → `.(100+NN)` (`.101–.110`); **guests `.200–.254`**; new guests use `.200+`, never `.100–.110`. Not yet compliant: proxmox-01 `.100`, proxmox-02 `.99`, proxmox-03 `.97`; VM 202 `.96`, VM 301 `.94`, tools container `.151`, LXC 104 `.150`, model-lab `.161–.167`. Migrating touches cloud-init/netplan, `model_lab_registry.py`, `elastic_workers.yaml`, `pve-ops`, script defaults, docs, known_hosts. **Remind the user (after the benchmarks): keep the router DHCP pool away from `.100–.110` and `.200–.254`.**
- **Backups = configuration only** (`infra/proxmox/proxmox-02/40-backup-config.sh` → `config-backup/`, in git). Models are re-downloadable; all VMs except 202 are ephemeral — delete finished test VMs without asking.
- **Dropped by the user:** proxmox-01 backup-timer test; LM Studio remote check. **Undecided:** registering models in `elastic_workers.yaml` (leave alone).
- Rebooting a host / creating VMs that take another VM's GPU may be blocked by the permission classifier — don't retry around it; give the user the command (`! ssh -i … `).
- **Be economical** (user, 2026-10-03): few tool calls, short replies, no unrequested extras.

## Access (private keys on the Windows dev machine, `~/.ssh/`; plain `ssh` is rejected)
proxmox-01 `root@192.168.0.100` `-i proxmox_temp_root` · tools container `root@192.168.0.151` `-i athenaeum_poc` (`pve-ops`; token env `/opt/athenaeum-tools/keys/athenaeum.env`, never read) · proxmox-02 `root@192.168.0.99` `-i proxmox02` · proxmox-03 `root@192.168.0.97` `-i proxmox03` · GPU VMs `debian@<ip>` `-i athenaeum_poc`. Use the Bash tool (git-bash), not PowerShell, for remote scripts (`known-bugs.md` #24). No local Python: run Python on a host/VM.

## Current state (2026-10-03)
- **proxmox-01** (`.100`): routinely powered off; LXC 104 (`.150`) + 106 (`.151`) + six model-lab llama.cpp guests `.161–.166` (liveness unverified since 2026-09-28). Backup timer `OnBootSec=10min` installed, never observed (test dropped).
- **proxmox-02** (`.99`, 3×GV100 32GB, 64GB, ZFS `fast-z1`): only **VM 202** (`.96`, 3 GPUs, 45.5GiB RAM, `onboot 0`) with services `llama-server` (Qwen3.8-27B Q4_K_M, GPU0, `:8080`) and `llama-server-q8` (Q8_0, GPUs 1+2, `:8081`), MTP speculative decoding, 131k tokens/slot × 2 slots — **both services are currently STOPPED for benchmarking** (`sudo systemctl start llama-server llama-server-q8`). Models: ZFS dataset `fast-z1/models` at `/srv/models` (476GB quant ladder), NFS-exported read-only to `10.10.10.0/24`. Athenaeum lives on the host at `/srv/athenaeum`. VMs 201/203 destroyed.
- **proxmox-03** (`.97`, 4×M6000 24GB, 125GB, 512GB NVMe `local-lvm`): `vfio-pci` claims all GPUs at boot; **VM 301** (`.94`, 4 GPUs, needs `rombar=0` — OVMF hangs otherwise) is running only for the benchmark — **delete it when done**. Passthrough proven both as 4-in-1 and 1-per-VM.
- **10G link** proxmox-02 `nic0` ↔ proxmox-03 `nic1`, bridge `vmbr1`, `10.10.10.2` / `.3` (VMs `.12` / `.13`), 9.4 Gbit/s measured.
- **Benchmark (`docs/progress.md` §46, raw in `docs/eval-results/quant-ladder-2026-10-03/`):** speed + perplexity done for 3 models × 4 quants × 2 hosts. Preliminary pick (≤~1% PPL loss vs Q8): Qwen3.8-27B → Q4_K_M; Coder-Next → Q4_K_M (or Q6_K); Llama-3.3-70B → Q6_K. **Open: optional harder task-accuracy eval (user to decide), restart VM 202's servers, delete VM 301, router reminder.** Tools: `scripts/{quant_eval,long_context_eval,speed_bench,concurrency_bench,bench_quants}.py`.
- Brain/Body software: all seven agents + sandbox + evaluation infrastructure implemented (see `docs/progress.md`); real model backends exist (llama.cpp guests, elastic GPU workers).

## Start of a new session
Read `docs/progress.md` §44/§46, then **check real state** (ping hosts, `qm list`, `systemctl is-active` on VM 202) before trusting any note above.
