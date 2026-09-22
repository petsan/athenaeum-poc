# Brainbox Infrastructure Topology

**Purpose of this file:** the sizing convention and shared-memory architecture for
the LXC guests ("brainboxes") that will host Brain workers, mocks, and simulators
on `proxmox01`, as the Brain backlog moves from in-process toy agents to
independently deployable, scalable compute. Companion to `deployment-playbook.md`
(how any guest gets stood up) and `infra/proxmox/README.md` (the scripts) — this
file is the *what and why* of the topology those scripts will implement, not a
restatement of either.

**Status:** design-only as of 2026-09-22. No guests of this shape exist yet;
the standing guests today (104 `athenaeum-preflight`, 106 `athenaeum-tools`)
predate this convention and aren't retrofitted into it.

---

## 1. Constraint this whole document works inside

- **This *Proxmox host* has no GPU capacity, still.** Everything in the tier
  table below remains CPU/system-RAM only — no change there. **Updated
  2026-09-23:** a real GPU path now exists, but deliberately *outside* this
  host entirely — `infra/elastic-workers/` implements body-design.md §4.3's
  "opportunistic compute... never a dependency" as a pool of
  independently-owned machines (starting with one Windows desktop's RTX
  3070 Ti) that register themselves in `elastic_workers.yaml` and can go
  online/offline at the operator's will. `elastic_workers.py`'s
  `ElasticGPUBackend` health-checks every worker fresh before every call,
  and `ModelServingLayer.request()` falls back to the CPU guests
  transparently the instant one goes dark — proven, not just designed
  (see `docs/brain-session-log.md`). This tier table still governs
  *Proxmox-hosted* guests specifically; the elastic pool is a genuinely
  separate topology, not a stretched XLarge tier pretending to be a GPU
  slot.
- **Hard cap raised 2026-09-23 (explicit user decision, was 50%):** at most
  80% of the host's real CPU/RAM for anything created here (`CLAUDE.md`),
  confirmed specs: 2× Xeon E5-2690 v2 = 40 threads, ~503GB RAM →
  **budget ceiling of 32 threads / ~402GB across every guest**, not per
  guest. As of that same date, nine guests (104, 106, plus the seven
  model-lab guests — see `infra/proxmox/model-lab/`) allocate ~19 vCPU of
  that. Effective remaining headroom is **~13 vCPU / ~370GB** — always
  check the live number (`pve-ops status`/API) before planning against
  this figure, since it changes as guests come and go; don't trust this
  paragraph over the real host.

---

## 2. Size tiers

| Tier | vCPU | RAM | Role | Steady-state budget |
|---|---|---|---|---|
| **XSmall** | 1 | 1–2GB | Mocks/simulators, deterministic toy agents (the Mathematics/Logic/Engineering pattern already in `agents.py`), orchestration/routing workers, anything with no model backend loaded | Cheap — many can run concurrently |
| **Medium** | 4 | 16GB | One real CPU-quantized model backend (~3–7B Q4 GGUF via `llama.cpp`) serving exactly one Master Agent | 2–3 concurrent |
| **Large** | 8 | 32–48GB | A bigger quantized model (~13B class) for an agent needing more capability, or a bundled multi-agent host running several agents behind one process | 1 at a time |
| **XLarge** | 16 | 64–96GB | Reserved, not routine. The largest CPU-only experiment this host can plausibly run. Alone it consumes about half of the 80% cap | At most one, spun up deliberately, never part of default topology |

A fully-loaded steady-state mix (e.g. 4× XSmall + 2× Medium + 1× Large =
4+8+8 = 20 vCPU, 4+32+40 = 76GB) fits comfortably inside the ~13 vCPU / ~370GB
current headroom on RAM but is CPU-bound first — vCPU, not RAM, is the tighter
constraint on this host, worth checking explicitly before scaling out rather
than assuming RAM will run out first. (That example mix's 20 vCPU actually
exceeds current real headroom, ~13 vCPU as of 2026-09-23 — illustrative of
the tier shapes, not a plan that fits today without retiring something else
first; always check the live number.)

---

## 3. Shared memory and context

The question this section actually answers: when multiple brainboxes are
running, what (if anything) do they share, and how? The answer follows
directly from a decision `brain-design.md` §4.4 already made — proposal-only
writes through a single commit boundary — which means brainboxes were never
meant to hold independent copies of committed state in the first place. There
is no replication problem to solve here, because there's nothing to
replicate:

- **Canonical memory** — Belief Graph, Provenance Ledger, Question Ledger,
  Reputability store — **stays centralized** on the Body engine, one LXC,
  using the existing content-addressed storage (`storage/content_addressed.py`,
  `storage/checkpoint.py`). Brainboxes never hold a local copy of committed
  state. They query it over the network (extending the existing `api.py`
  rather than inventing a new protocol) and submit proposals back — the same
  shape as today's in-process `round_handler` call, just over a wire instead
  of a function call.
- **Per-deliberation working context** — a model's KV-cache, an agent's
  in-flight reasoning for one active round — is genuinely per-box and
  **ephemeral by design**, not shared. This is intentional, not a gap: a
  fresh deliberation round is supposed to rebuild its context from the
  canonical graph each time (§3.2's "no cross-talk yet" framing round design),
  not inherit another box's leftover cache.
- **Model weights** are the one thing worth literally sharing rather than
  duplicating per box: one read-only, content-addressed weight store (reusing
  the existing registry/tamper-detection mechanism from `model_serving.py`)
  mounted read-only into every Medium/Large guest, so a given GGUF file lives
  on disk once, not once per worker.

Net effect: brainboxes are stateless compute that can be killed and respawned
freely. The only thing expensive to lose is the central store, which is
exactly what the existing hash-chained checkpoint design already protects
against corruption and partial writes — this topology adds no new class of
state that isn't already covered by that guarantee.

---

## 4. Naming and template convention

Extends the existing standing-guest pattern
(`infra/proxmox/03-create-project-guest.sh`) rather than replacing it: one
templated create path taking a `--tier {xsmall,medium,large,xlarge}` flag
that maps to the table in §2, tagged into the `athenaeum-poc` resource pool
(as today) so `pve-ops` can list/filter by tier, and named so purpose is
legible from `pct list` alone: `athenaeum-worker-xs-<n>` for XSmall
mocks/orchestration, `athenaeum-agent-<tier>-<domain>` for a tier hosting a
specific Master Agent's model backend (e.g. `athenaeum-agent-md-physics`).

Not yet decided, deliberately left open until there's a concrete first
Medium/Large deployment to build against rather than guessed at in the
abstract: the exact mount mechanism for the shared read-only weight store
(NFS from the Body host vs. a Proxmox-level bind mount vs. something else),
and whether the Body engine host itself is a new dedicated guest or repurposes
an existing one. Both get decided when Phase 5 (Engineering agent + Model
Fitness, per `progress.md`) actually needs a Medium-tier box to deploy onto,
not before — matching this project's own stated principle of not building
speculative infrastructure ahead of a real need for it.

---

## 5. Explicitly out of scope here

- ~~A GPU tier — not designed until GPU nodes are actually online...~~
  **Partially done, 2026-09-23**: a real, working GPU path exists via
  `infra/elastic-workers/`, but deliberately as an *elastic pool outside
  this Proxmox host*, not a Proxmox-hosted GPU tier — see §1. A genuine
  Proxmox-hosted GPU tier (a card physically in `proxmox01` with real
  PCIe passthrough) is still undesigned and still blocked on that
  hardware actually existing in that chassis.
- Auto-scaling / orchestration logic (deciding *when* to spin a tier up or
  down) — this document defines the shapes of the boxes, not the policy for
  provisioning them; that's a separate decision for whenever real load
  justifies it.
- ~~Raising the 50% resource cap — out of scope...~~ **Done, 2026-09-23**:
  raised to 80% by explicit user decision — see `CLAUDE.md`'s hard
  constraints and §1 above for the recomputed budget.
