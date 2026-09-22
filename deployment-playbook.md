# Deployment Playbook: Proxmox (`proxmox01`)

**Purpose:** everything needed to stand up scoped, working access to this Proxmox host for a **new** project, from zero to a verified SSH-reachable test guest with a full test suite runnable on it — without re-discovering the gotchas that cost real time and tokens the first time (see `known-bugs.md` entries 17–18 for the full incident writeups this playbook is distilled from).

**How to use this file:** point Claude at this playbook plus one filled-in config file (template in Section 1) and one SSH key (Section 4). Everything else below is a mechanical procedure, not a design decision — follow it in order.

---

## 0. Before anything: hard constraints (apply regardless of project)

- **Resource cap:** default to 50% of the host's real CPU/RAM for any new VM/LXC, verified against actual specs (Section 2), not assumed. This is a testing-phase default — confirm with the user before assuming a higher cap applies (it may, once a project is "going live"; that's a per-project decision, not a host default).
- **Never deploy workloads directly on the Proxmox host OS.** Everything goes inside a VM or LXC.
- **Never commit secrets.** The config file in Section 1 holds a live API token secret — it is gitignored from the first commit of any new project, never typed into chat, never pasted into a document that gets published.

---

## 1. The one config file

Create `.proxmox.env` in the new project's repo root (gitignore it immediately — see Section 1.1) and fill in every value as you complete the matching numbered section below:

```
# --- Section 2: host identity ---
PROXMOX_HOST=192.168.0.100
PROXMOX_PORT=8006
PROXMOX_NODE=proxmox01

# --- Section 3: scoped identity (fill in after creating these) ---
PROXMOX_USER=claude@pve
PROXMOX_TOKEN_ID=claude@pve!<project-name>
PROXMOX_TOKEN_SECRET=<uuid, shown once at creation, paste immediately>
PROXMOX_ROLE=ClaudeAgent-<project-name>
PROXMOX_POOL=<project-name>-poc

# --- Section 5: storage ---
PROXMOX_STORAGE=local-thin-multi
PROXMOX_TEMPLATE_STORAGE=local

# --- Section 6: standing test guest ---
PROXMOX_VMID=<next free id, from /cluster/nextid>
PROXMOX_GUEST_HOSTNAME=<project-name>-preflight
PROXMOX_GUEST_IP=192.168.0.<pick unused, e.g. 150>
PROXMOX_GUEST_GATEWAY=192.168.0.1
PROXMOX_GUEST_MAC=BC:24:11:<pick 3 unused bytes>

# --- Section 4: SSH ---
SSH_KEY_PATH=~/.ssh/<project-name>_poc
```

### 1.1 Gitignore it immediately, first commit

```
echo ".proxmox.env" >> .gitignore
echo ".env" >> .gitignore
git add .gitignore
```
Do this before creating `.proxmox.env` itself, in the same breath — never let it exist as an untracked-but-visible file for even one commit cycle.

---

## 2. Confirm real host specs (don't trust placeholder numbers in any design doc)

Once you have *any* working API token (even a low-privilege one, or ask the user to run this on the host directly):
```
pveum user token list <token-owning-user>   # sanity check the token exists, isn't expired
```
Then, once the token has `Sys.Audit` on the node (Section 3):
```
GET /nodes/{PROXMOX_NODE}/status
```
Record CPU (model, socket/core/thread count), total RAM, kernel version, PVE version. As of the last deployment here: **2× Xeon E5-2690 v2, 40 threads, ~504GB RAM, PVE 9.2.20, kernel `7.0.14-17-pve`.** Re-check if this playbook is reused more than a few months after that date — hardware doesn't usually change, but don't assume.

---

## 3. Create scoped identity: user, role, pool, token, ACLs

Run on the host (or ask the user to — none of this needs a working token yet, it's bootstrapping the token itself):

```bash
# 1. User (realm MUST be pve, not pam -- pam maps to a real Linux system user)
pveum user add claude@pve

# 2. Resource pool -- everything this project creates lives here, nowhere else
pveum pool add <project-name>-poc

# 3. Role -- start minimal, this is the actual set of privileges that has
#    proven sufficient for token->pool->storage->node->container lifecycle
#    work on this host; extend only as a specific API call demands it
#    (each extension will tell you exactly which privilege is missing).
pveum role add ClaudeAgent-<project-name> -privs \
  "Datastore.AllocateSpace,Datastore.Audit,Pool.Audit,SDN.Use,Sys.Audit,VM.Allocate,VM.Config.CDROM,VM.Config.CPU,VM.Config.Cloudinit,VM.Config.Disk,VM.Config.HWType,VM.Config.Memory,VM.Config.Network,VM.Config.Options,VM.PowerMgmt"

# 4. API token -- name it after the project, keep Privilege Separation ON
pveum user token add claude@pve <project-name> --privsep 1
#    >>> COPY THE SECRET SHOWN HERE INTO .proxmox.env IMMEDIATELY, IT NEVER SHOWS AGAIN <<<
```

### 3.1 THE critical gotcha: grant every ACL to BOTH the token AND the user

**On this host, a Privilege-Separated token's effective permissions are the *intersection* of the token's own grants and the underlying user's grants — not the token's grants alone.** Granting only the token silently resolves to zero effective permissions (`/access/permissions` returns an empty map) even though `pveum acl list` looks completely correct. This contradicts general Proxmox documentation; it was verified empirically on this host (`known-bugs.md`-adjacent finding from the first deployment session) and has held true across every subsequent grant since.

**Every single ACL grant below must be issued twice** — once for the token, once for the user:

```bash
pveum acl modify /pool/<project-name>-poc --tokens 'claude@pve!<project-name>' --roles ClaudeAgent-<project-name>
pveum acl modify /pool/<project-name>-poc --users claude@pve --roles ClaudeAgent-<project-name>

pveum acl modify /nodes/proxmox01 --tokens 'claude@pve!<project-name>' --roles ClaudeAgent-<project-name>
pveum acl modify /nodes/proxmox01 --users claude@pve --roles ClaudeAgent-<project-name>

pveum acl modify /storage/local-thin-multi --tokens 'claude@pve!<project-name>' --roles ClaudeAgent-<project-name>
pveum acl modify /storage/local-thin-multi --users claude@pve --roles ClaudeAgent-<project-name>

pveum acl modify /storage/local --tokens 'claude@pve!<project-name>' --roles ClaudeAgent-<project-name>
pveum acl modify /storage/local --users claude@pve --roles ClaudeAgent-<project-name>

# vmbr0 is managed as an SDN zone on this host, not a plain bridge --
# creating any guest with a network interface needs this specifically,
# discovered only via the exact error "Permission check failed (/sdn/zones/localnetwork/vmbr0, SDN.Use)"
pveum acl modify /sdn/zones/localnetwork/vmbr0 --tokens 'claude@pve!<project-name>' --roles ClaudeAgent-<project-name>
pveum acl modify /sdn/zones/localnetwork/vmbr0 --users claude@pve --roles ClaudeAgent-<project-name>
```

**Verify before moving on** — don't trust `pveum acl list`, query the actual resolved permission set:
```
GET /access/permissions?path=/pool/<project-name>-poc
```
Should return a non-empty privilege map. If empty, one of the two grants above is missing.

---

## 4. SSH key (the one key file)

```bash
mkdir -p ~/.ssh
ssh-keygen -t ed25519 -f ~/.ssh/<project-name>_poc -N "" -C "claude-code@<project-name>-poc"
```
Passphrase-less by design — this is what lets Claude authenticate non-interactively without a human relaying every command. Tradeoff, stated plainly: anything with filesystem access to this key can reach the guest as root over SSH. Acceptable for a throwaway test guest on isolated storage; reconsider (passphrase + agent, or a non-root user, or `authorized_keys` command restrictions) if the guest ever holds anything sensitive.

The public key gets installed into the guest in Section 6 — there's no guest to install it into yet at this point in the playbook.

---

## 5. Storage

`local-thin-multi` (or whatever LVM-thin/ZFS pool is dedicated to this host) holds guest disks (`rootdir,images` content type). `local` holds templates (`vztmpl` content type) — check what's already downloaded before assuming a fetch is needed:
```
pveam list local
```
If the template you need isn't there and the host has internet egress (verify with Section 7 first if unsure), `pveam download local <template-name>`.

If a project genuinely needs its **own dedicated** storage pool separate from other projects sharing the host, say so explicitly when scoping Section 3 — don't default to assuming isolation that wasn't actually granted.

---

## 6. Standing test guest — the template that's proven to work

```bash
pct create <VMID> local:vztmpl/debian-12-standard_12.12-1_amd64.tar.zst \
  --hostname <project-name>-preflight \
  --cores 2 --memory 2048 \
  --rootfs local-thin-multi:8 \
  --net0 name=eth0,bridge=vmbr0,ip=<STATIC_IP>/24,gw=192.168.0.1,firewall=0,hwaddr=<PINNED_MAC> \
  --pool <project-name>-poc \
  --unprivileged 0 --features nesting=1,keyctl=1
pct start <VMID>
```

Notes on every non-obvious flag, each one earned the hard way:
- **Static IP, not DHCP.** DHCP never got a reply on this network in the original deployment session — root cause was never fully isolated (possibly unrelated to anything in this playbook), and static sidesteps it entirely. Pick an IP outside your router's DHCP range if you know it, to avoid future collision.
- **`hwaddr=` pinned, always.** Omitting it means Proxmox generates a new random MAC on *every* `pct set -net0 ...` call, which breaks ARP/neighbor caches on every machine that's ever talked to the guest (including the Proxmox host itself) and manifests as total unreachability until caches are manually flushed. Pin it once, at creation, and never omit it on any later `pct set -net0`.
- **`firewall=0`.** Per-NIC firewall defaults to a restrictive posture that blocks DHCP/inbound-unsolicited traffic with no rules configured. Turn it off unless the project specifically needs guest-level firewalling, in which case configure actual rules, don't leave it enabled-with-nothing-allowed.
- **`unprivileged=0 --features nesting=1,keyctl=1`** — only if the project needs real nested `unshare`/`mount`/cgroups capability inside the guest (e.g. testing a sandboxing mechanism, running Docker-in-LXC). For an ordinary application workload, prefer the safer default (`unprivileged=1`, omit `--features`). The full privileged+nesting+keyctl combination needs `Sys.Modify` on `/`, which the scoped token deliberately does not have — **only `root@pam` running `pct create`/`pct set` directly on the host can set this combination**; don't try to grant the token enough privilege to do it itself, that defeats the scoping in Section 3. `unprivileged` is immutable after creation — changing it means destroy + recreate.

---

## 7. The mandatory day-1 fix: check `iptables -L FORWARD` before assuming anything else is broken

**Do this immediately after the guest is up, before spending any time on DHCP/ARP/firewall debugging if connectivity looks wrong:**
```
iptables -L FORWARD -n -v
```
If this host runs Docker for anything (check with `docker ps` or `systemctl status docker`), Docker sets `FORWARD`'s default policy to `DROP` and only allows traffic tied to its own managed interfaces. Because `bridge-nf-call-iptables` is active, this silently catches **all** bridged IP traffic through `vmbr0` — any guest talking to its gateway, or another LAN machine talking to a guest — while leaving ARP completely untouched.

**The fingerprint that means "it's this, stop looking elsewhere": ARP resolves fine (`ip neigh show` shows a resolved MAC), but ICMP/TCP across the bridge gets zero response.** Host↔guest traffic (pinging the guest *from the Proxmox host itself*) will work fine regardless — that's the host's own INPUT/OUTPUT chain, not FORWARD, and is a misleading "things are mostly fine" signal. Don't trust it as evidence the guest's networking is healthy.

**Fix, one rule, in the chain Docker guarantees it will never overwrite:**
```
iptables -I DOCKER-USER -i vmbr0 -o vmbr0 -j ACCEPT
```
Not yet confirmed to persist across a host reboot (check whether `iptables-persistent`/`netfilter-persistent` is installed; if not, this rule needs re-applying after any reboot of the Proxmox host — check for it early in any session that starts after a suspected reboot).

If this host does *not* run Docker, this whole section is moot — but check `iptables -L FORWARD -n -v` anyway before chasing Proxmox-level theories; the general lesson (verify the actual kernel filter table before assuming the problem is at the layer you're already looking at) applies regardless of the specific cause.

---

## 8. Install the public key, verify SSH

```
pct exec <VMID> -- bash -c "mkdir -p /root/.ssh && chmod 700 /root/.ssh && echo '<contents of ~/.ssh/<project-name>_poc.pub>' >> /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys"
```
Then, from wherever Claude is actually running:
```
ssh -i ~/.ssh/<project-name>_poc -o StrictHostKeyChecking=accept-new root@<STATIC_IP> "echo SSH_WORKS && hostname"
```
If this fails after Section 7's fix is applied, check basic reachability first (`ping <STATIC_IP>` from wherever you're SSHing from) before assuming it's SSH-specific — most failures at this stage turn out to be Section 6 or 7, not SSH configuration itself.

**Rebuilding an existing guest (destroy + recreate, e.g. to get back to a clean filesystem):** a fresh guest generates fresh SSH host keys even when it reuses the same IP/MAC, so the client-side SSH client will refuse to connect with a "REMOTE HOST IDENTIFICATION HAS CHANGED" warning. This is expected, not an actual MITM, *provided you just destroyed and recreated that guest yourself* — confirm that before clearing it. Clear the stale entry before retrying: `ssh-keygen -R <STATIC_IP> -f ~/.ssh/known_hosts`.

Also: **`unprivileged` cannot be changed with `pct set` after creation — it errors `unable to modify read-only option: 'unprivileged'`.** To change it, the guest must be destroyed and recreated with the correct value passed to `pct create` from the start (`pct stop <VMID> && pct destroy <VMID>`, then re-run the Section 6 `pct create` with the flag you actually want). Don't try to "fix up" an existing guest's privilege mode in place — this was gotten wrong once even with this exact constraint already documented above, worth a second explicit callout here at the point where the mistake actually happens.

---

## 9. Verification checklist before calling the environment "ready"

- [ ] `GET /access/permissions?path=/pool/<project-name>-poc` returns a non-empty privilege map (Section 3.1)
- [ ] `ping <STATIC_IP>` succeeds from the Proxmox host
- [ ] `ping <STATIC_IP>` succeeds from wherever Claude actually runs (not just the host — this is the check that would have caught the Docker FORWARD-chain issue immediately instead of after hours of Proxmox-level debugging)
- [ ] `ping 8.8.8.8` succeeds *from inside the guest* (internet egress, needed for package installs)
- [ ] `ssh -i <SSH_KEY_PATH> root@<STATIC_IP> "echo ok"` succeeds non-interactively
- [ ] Project's actual test suite copied over and run for real, as root, inside the guest — not mocked, not skipped because "the fix looked right." If the project needs `unshare`/`chroot`/cgroups capability to test anything meaningfully (sandboxing, isolation), confirm Section 6 used the privileged+nesting variant, or those tests will fail or silently take a degraded fallback path.

---

## 10. What this playbook does not cover

- Provisioning a *second* guest for the same project (repeat Section 6 with a new VMID/IP/MAC; Sections 1–5 and 7 are one-time per project).
- Production sizing/resource-cap decisions beyond the Section 0 default — that's a per-project, per-deployment-phase decision, not a host-level default this playbook should encode.
- Any application-level configuration inside the guest once it's reachable — this playbook's job ends at "verified SSH access to a correctly-networked, correctly-scoped guest," not at "the application is deployed and running."
