# Model Candidate Lab

Six isolated LXC guests, one per LLM candidate, for A/B/C comparison ahead
of picking the Local Model Serving Layer's real backend (`body-design.md`
Section 4.5). Deliberately **not** the production swap-based router (one
box, models loaded/unloaded elastically) -- that's a real, useful pattern,
but it's the wrong shape for *comparing* candidates: isolated VMs mean no
cross-model interference, genuinely simultaneous querying, and a clean
"drop this one" story once a decision is made. The swap-based router
remains the intended shape for production once a backend is actually
chosen; standing these up doesn't commit to skipping it.

## Why these aren't sized like the standard tiers

`docs/infra-topology.md`'s XSmall/Medium/Large/XLarge tiers are sized for
production roles (Medium = one real backend for one Master Agent, 4 vCPU).
These six are testing/comparison boxes -- lighter (2 vCPU for anything
≤3.8B, 4 vCPU for the one 7B model) since raw production throughput isn't
the goal yet. Rather than add a fifth formal tier for a possibly one-off
evaluation exercise, `create-model-vms.sh` uses the `GUEST_CORES`/
`GUEST_MEM_MB` override flags `03-create-project-guest.sh` already
supports. If "small test box" turns out to be a recurring shape, promote
it to a real tier then -- not speculatively now.

## Resource footprint (checked against the live host, not assumed)

All six running simultaneously: **14 vCPU, 34GB RAM, ~25GB disk** --
comfortably inside the 50% cap's ~17 vCPU of real headroom (20-thread
budget minus guests 104/106), verified via `pve-ops status`/`storage` at
the time this was written (419GB RAM free, 1091GB disk free -- neither is
remotely the constraint; vCPU is).

## The six candidates

See `manifest.tsv` for the full VMID/IP/MAC/sizing table. **Verified
against live Hugging Face API listings on 2026-09-23** (not just recalled
from training knowledge) -- both the exact GGUF filenames and each
repo's license tag were actually fetched and checked. All six are
apache-2.0 (OLMo, Qwen, Granite, Mistral) or mit (Phi).

**One real catch this verification surfaced, worth remembering:**
Qwen2.5-3B-Instruct -- the original plan -- is NOT apache-2.0. It's under
the restrictive "Qwen Research License" (non-commercial), unlike the
0.5B/1.5B/7B Qwen2.5 sizes, which are. Swapped for Qwen2.5-1.5B-Instruct
(confirmed apache-2.0) rather than silently keeping a candidate that
fails the "legally fully modifiable" criterion. Lesson: a model family
sharing one license across all its sizes is an assumption, not a fact --
check every size actually intended for use, not just the family's
flagship. A second, smaller correction: the official `ibm-granite`
GGUF repo required auth (401) and OLMo's GGUF filename casing differed
from the first guess (`OLMo-2-...` not `olmo-2-...`) -- both caught by
querying the API rather than trusting the first plausible-looking repo
name.

## Running it

1. **Create the guests** (needs curl+jq -- run from the tools container,
   `192.168.0.151`, or anywhere else that has them):
   ```
   source .proxmox.env   # or wherever the token secret lives
   PROXMOX_HOST=192.168.0.100 PROXMOX_NODE=proxmox01 \
   PROXMOX_TOKEN_ID='claude@pve!athenaeum' PROXMOX_POOL=athenaeum-poc \
   SSH_PUBKEY_PATH=~/.ssh/athenaeum_poc.pub \
     ./create-model-vms.sh
   ```
2. **Install llama.cpp and download weights** on each (a few minutes per
   guest -- build from source, then a multi-GB download):
   ```
   SSH_PRIVATE_KEY_PATH=~/.ssh/athenaeum_poc ./setup-all.sh
   ```
   Or one at a time: `./setup-llama-and-download.sh <ip> <hf_repo> <hf_file> <label>`.
3. **Compare.** Each guest serves an OpenAI-compatible API on port 8080
   (`llama-server`, from `llama.cpp` itself). `setup-all.sh` prints a
   one-liner to fan the same prompt out to all six and compare responses.

## Cleanup

These are marked `Expected lifetime: Temporary` in each guest's own Notes
field (`pct config <vmid>`) -- once the backend decision is made, destroy
the ones that didn't win: `pve-ops -p athenaeum destroy <vmid>` per
guest, or the equivalent `pct stop <vmid> && pct destroy <vmid>` on the
host. Nothing here is wired into `onboot`-persistent, backed-up
infrastructure the way 104/106 are -- these are disposable by design.
