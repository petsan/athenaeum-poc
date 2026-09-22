# Proxmox Infrastructure as Code

This directory is the executable counterpart to `deployment-playbook.md` (repo root) — every step in that playbook that can be scripted, is scripted here. If Claude is unavailable and something on `proxmox01` needs rebuilding, these scripts plus that playbook are the full recipe; nothing about this setup depends on a live Claude session to reproduce.

## What lives where

| Script | Runs where | Needs |
|---|---|---|
| `00-bootstrap-identity.sh` | **On the Proxmox host**, as `root@pam` | Creates a project's user/role/pool/token/ACLs from nothing. Can't be done via API (needs `Sys.Modify`). |
| `01-create-tools-container.sh` | Anywhere with `curl`/`jq`/`ssh` (Windows git-bash, the tools box itself, the host) | An existing project's token with guest-creation rights. Creates the **one shared** tools container (`athenaeum-tools`, currently `192.168.0.151`, VMID 106) — reused across projects, not recreated per-project. |
| `02-register-project.sh` | Same as above | Onboards a project's credentials onto the (already-running) tools container so `pve-ops -p <project>` works from there. |
| `03-create-project-guest.sh` | Same as above | Creates a project's own working guest (e.g. `athenaeum-preflight`, VMID 104). Deliberately doesn't depend on the tools container existing — works even if that's what needs rebuilding. Accepts `GUEST_TIER={xsmall,medium,large,xlarge}` (see `docs/infra-topology.md`) to pick sane vCPU/RAM/disk defaults for a brainbox worker; omit it for the original 2vCPU/2GB/8GB shape. `GUEST_CORES`/`GUEST_MEM_MB`/`GUEST_DISK_GB` always override the tier default if set. |
| `04-persist-docker-forward-fix.sh` | **On the Proxmox host**, as root | Installs the systemd unit that reapplies the `DOCKER-USER` bridge fix (`known-bugs.md` #18) after every reboot and every Docker restart. Without this, guest networking silently breaks again on every reboot. |
| `05-verify.sh` | Same as 01–03 | Health checks: API permissions, ping, SSH, internet egress from inside the guest. |
| `06-setup-backups.sh` | **On the Proxmox host**, as root | Simplest viable backup: a daily `vzdump` snapshot of the given guests, written to `local` (the host's root filesystem — physically different storage than `local-thin-multi`, where the live disks are), self-pruned to the last 7 copies. See the tradeoffs section below before assuming this is enough protection. |
| `rebuild-all.sh` | Same as 01–03 | Orchestrates 01 → 02 → 03 → 05 for one project. Does **not** run 00 or 04 — those need `root@pam` on the host and are one-time-per-host, not per-rebuild. |
| `lib/common.sh` | sourced by the others | Shared `curl`/`jq` API helpers. |
| `systemd/pve-docker-bridge-fix.service` | installed by `04-` | The actual unit file, versioned here as the source of truth. |
| `tools-cli/pve-ops` | deployed by `01-` onto the tools container | The CLI itself — see below. Edit **this** copy and redeploy; don't hand-edit the one running on the container. |

## Three ways this survives without Claude

**1. A host reboot / accidental power-off.** Both guests (`athenaeum-preflight` and `athenaeum-tools`) have `onboot: 1` set, so Proxmox starts them automatically when the host boots — no script needed for that part. What does NOT survive a reboot on its own is the Docker `FORWARD`-chain fix; `04-persist-docker-forward-fix.sh` installs a systemd unit specifically so that part survives too. **Run `04-` once per host, not once per project** — check `systemctl status pve-docker-bridge-fix.service` after any host reboot if guest networking ever seems broken again; that's the first thing to check per `known-bugs.md` #18, not the last.

**2. A guest gets accidentally deleted, or its live disk gets corrupted, but the host itself and its `local` storage are fine.** `06-setup-backups.sh` covers this: a daily `vzdump` snapshot of each guest, written to `local` (physically separate from `local-thin-multi`, where the live disks are), self-pruned to the last 7 copies so it never grows unbounded. Restore with `pct restore <vmid> local:backup/vzdump-lxc-<vmid>-<timestamp>.tar.zst --storage local-thin-multi` — this gets the guest's actual *data* back, not just an empty guest matching the same recipe.

**3. A genuinely wiped/destroyed Proxmox install (including its backups), or you just don't have a recent backup.** Run the scripts in order: `00-` (host, root@pam) → `01-` → `02-` → `03-` → `05-` (→ `04-` and `06-`, host, root). This is what `rebuild-all.sh` automates for everything except the host-only steps — it gets you a working guest matching the recipe, but without #2's actual prior data, since there was none to restore.

**What this does NOT cover: losing the whole physical host.** The backups from `06-` live on the *same machine* as the guests they're backing up — a disk failure, theft, or destruction of `proxmox01` itself loses the live guests and their backups together. That's a meaningfully different, bigger piece of infrastructure (off-host/off-site replication) than what's built here, and wasn't asked for — flag it explicitly if it's actually needed rather than assuming this setup already covers it.

## The `pve-ops` CLI: multi-project by design

One tools container, many projects. Each project gets its own file under `/opt/athenaeum-tools/keys/<project>.env` on the tools container (pushed there by `02-register-project.sh`), holding that project's own scoped token and SSH key — projects never share credentials with each other, only the box and the CLI binary.

```
pve-ops -p athenaeum status
pve-ops -p athenaeum guests
pve-ops -p athenaeum ssh 192.168.0.150 'echo hi'
pve-ops projects                    # list what's registered
pve-ops -p someotherproject create 110 someguest 192.168.0.160 BC:24:11:AA:BB:CE
```

`athenaeum-ops` (no `-p` flag needed, defaults implied by the name) is kept as a symlink to the same binary for anything that referenced the earlier, Athenaeum-only version of this tool.

To onboard a **new** project onto the existing tools container:
1. `00-bootstrap-identity.sh <new-project>` on the host (creates its own user/role/pool/token — reuses `claude@pve`, adds a new role/pool/token alongside the existing ones, doesn't touch Athenaeum's).
2. Fill in that project's own `.proxmox.env` (same template as `deployment-playbook.md` Section 1).
3. `02-register-project.sh <new-project> <its .proxmox.env> <its ssh key> 192.168.0.151`.
4. `pve-ops -p <new-project> status` to confirm.

## Current live inventory (as of last rebuild)

| VMID | Hostname | IP | Purpose | Privileged? |
|---|---|---|---|---|
| 104 | `athenaeum-preflight` | 192.168.0.150 | Athenaeum's sandbox-testing guest | Yes (`nesting=1,keyctl=1`) |
| 106 | `athenaeum-tools` | 192.168.0.151 | Shared tools/ops box (this CLI lives here) | No |

Keep this table current — it's the fastest way to know what should exist before assuming something is missing or extra.
