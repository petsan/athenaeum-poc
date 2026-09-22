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

See `manifest.tsv` for the full VMID/IP/MAC/sizing table. All are
Apache 2.0 (OLMo, Qwen, Granite, Mistral) or MIT (Phi) licensed --
verify each model card still says that before downloading, license terms
aren't something to trust from memory. `manifest.tsv`'s `hf_repo`/`hf_file`
columns are a best-effort guess at current GGUF quantization repos, not
independently verified against a live Hugging Face listing -- if a
download 404s, find the current repo/file on huggingface.co and edit the
manifest, don't assume the model itself is unavailable.

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
