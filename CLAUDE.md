# Athenaeum

A slow, deep-reasoning, memory-resident knowledge system in two halves:
**Body** (`src/athenaeum_body/`: storage, scheduling, model serving, API) and
**Brain** (`src/athenaeum_brain/`: seven Master Agents deliberating, with
reputability, model fitness and idle re-examination). Evaluation is in
`src/athenaeum_evals/`, built on evalcore (`github.com/petsan/evalcore`).
This repo is a proof of work, not the finished system.

**Start every session with `docs/progress.md` §0 "RESTART HERE".** It holds
the current state: hosts, guests, access, test counts, what's next, open
decisions and recurring pitfalls. This file holds the rules, which change
rarely. If the two disagree about state, §0 wins; if they disagree about a
rule, ask the owner.

## Owner's rules (standing until the owner changes them)

### Hands off without explicit approval
- **`LICENSE` and the README notice line** (Piorun, Inc.). Never alter them;
  the notice must stay byte-identical (check with `cmp`). A README body
  refresh is a draft until the owner reviews it (`README.draft.md`, not committed).
- **`execution_sandbox.enabled` stays `false`**, until every scenario in
  `security-review-sandbox.md` passes on the actual host, verified by
  `scripts/preflight_check.py`.
- **No paid or metered services, ever** (enforced by `disallow_paid_apis` in `config.py`).
- **Credentials:** don't read, print, copy or explore them. The reviewer
  tokens file is never committed. If auto mode refuses an action as
  credential exploration or an ACL change, don't work around it. Give the
  owner a paste-ready command and say why.
- **Other projects' guests** on a shared host are never touched
  (on proxmox-01: 101, 105, 107, 200–220, 250). On proxmox-01, don't touch
  `/dev/sdc` or `/dev/sdg`.

### Hosts and resources
- **proxmox-01 (`192.168.0.100`): no more tests of any kind** (owner,
  2026-09-28). That includes pytest, `run_evals.py`, live smoke scripts,
  benchmarks and the nightly timer, which is disabled. Access continues:
  inspection, backups and migration work are fine.
- **proxmox-02** (3× GV100, 96 GB VRAM total; 128 GB RAM; Xeon W-2155;
  10 TB NVMe) is where testing moves. Its access, test runner and model
  store are recorded in progress.md §0 once set up; until then, don't
  assume any of them.
- Deploy inside a VM or LXC, never on a Proxmox host OS.
- Guests may use at most **80% of a host's CPU and RAM**. Check the real
  specs; don't trust design-doc placeholders.
- Creating, changing and destroying *our own* guests is allowed during
  development. Anything else destructive on a host needs the owner's OK
  first.
- Model files live in the host's designated model store (proxmox-01:
  `/mnt/pve/glacier-01/models`). Verify integrity with SHA-256 against
  Hugging Face, not by file size.
- A host may be powered off between sessions; that's normal. Ping it
  first, and verify guest state rather than recalling it.

### How work is paced
- **Batches of small phases.** Each phase: implement → new tests → full
  suite on the test runner → update docs → secret-scan the staged diff →
  commit and push to `master`. At the end of a batch, run an end-to-end
  test, then plan the next batch.
- Unattended batches are approved. **Stop and ask only on:** a test
  failure you can't explain, a hard-to-reverse design gap, a change to
  what an existing test or gate means, a host that is down, or anything
  covered by "Hands off" above.
- **Update `docs/progress.md` right before handing control back to the
  owner, after every step**, not only at the end of a batch. §0 must
  always be enough to resume cold.
- Keep `known-bugs.md` (every real bug: what happened, root cause, fix,
  lesson), `docs/brain-session-log.md` (design Q&A) and this file current
  as part of finishing work, not afterwards.
- **Ask all open questions at once**, up front, each with a
  recommendation. Then work without further check-ins.
- After an intended golden-data change, re-save the evaluation baseline
  yourself, but only from an APPROVED run, and log the reason and the
  commit in progress.md.

### Git
- Default branch is `master` (the owner may say "main").
- Commit identity: the repo-local `Athenaeum POC <poc@athenaeum.local>`
  (evalcore uses the owner's GitHub noreply address). End every commit
  message with the `Co-Authored-By` line.
- evalcore is public. Tag a release for every change Athenaeum depends on,
  and pin the tag in `pyproject.toml`. evalgate-0.2.0 parity must keep
  passing.

### Reporting
- Report what was observed, not what should be true. Test counts are real
  counts, and a count different from the expected one gets explained.
- Say plainly what wasn't run or verified, and don't credit a change with
  an effect you didn't measure.

## Mechanics that bite (details and history: progress.md §0, known-bugs.md)

- The Windows workstation has **no Python** (node and git-bash only).
  Tests run on the test runner guest, synced by `tar | ssh` (it has no
  git), with the venv's Python (`/opt/athenaeum-venv/bin/python`), never
  bare `python3`. The exact commands are in §0.
- Offline mode for non-model changes: `ATHENAEUM_OFFLINE_MODELS=1`. Say
  which live-model tests weren't run.
- Kill a process only by a PID you saved and checked, never with
  `pkill -f`/`pgrep -f` on a pattern your own command line contains (#38).
  One tracked background job per task, never `&` inside a pipeline.
- `systemctl enable --now` doesn't restart a running service; use
  `restart` (#39). `systemctl is-active -q` is false while a oneshot is
  `activating`, so wait loops must compare the state string.
- Long live scripts print progress as they go: a model call can take
  10–25 s on CPU.
- A rebuilt guest has new SSH host keys (`ssh-keygen -R <ip>` first). Use
  `tar --no-same-owner` into unprivileged containers. Build llama.cpp with
  `--target llama-server`.
- Guest networking problem? Check `iptables -L FORWARD` before any other
  theory (known-bugs #18).

## Principles (each one learned the hard way here)

1. **Verify, don't trust**, not even your own notes. "Should work" isn't "works."
2. **Least privilege.** Grow a token or role one permission at a time, each
   traceable to a real denial.
3. **Root cause, not workaround.** Reproduce minimally before trusting a fix.
4. **The repo is the record.** Infrastructure lives in `infra/` and
   `deployment-playbook.md`, and decisions in `docs/`, so nothing depends
   on a conversation surviving.
5. **State scope honestly:** fixed vs. tested vs. only reasoned through.
6. **Confirm before hard-to-reverse actions** on shared state, security
   posture or credentials.

## Where things are

- `docs/progress.md`: the current state (§0) plus a chronological log.
  `docs/owner-decisions.md` holds the decision briefs.
- `docs/body-design.md`, `docs/brain-design.md`: design intent. When the
  code and the design differ, the design says what it should become.
- `known-bugs.md`: read the relevant entries before touching sandboxing,
  checkpoint storage, demo scripts or guest networking.
- `security-review-sandbox.md`: read before any change to `sandbox.py`.
- `deployment-playbook.md`, `infra/proxmox/` (scripts, recovery, model
  lab), `infra/nightly/` (the evaluation timer).
- `acceptance-criteria.md`, `schemas.md`, `tech-stack.md`: what "done"
  means, store shapes, and committed tech choices.
