# Known Bugs and Lessons

Every bug in this file was actually hit during development of this repo — not a hypothetical checklist. Each entry has what happened, the root cause, the fix, and the generalizable lesson, so the same class of mistake doesn't get repeated in later work on this project. Test-authoring mistakes are included alongside library bugs and marked as such, since the discipline that catches them ("did I test the right thing") is the same discipline either way.

---

## Shell and OS environment gotchas

### 1. Brace expansion silently fails under `dash`
**What happened:** `mkdir -p "$ROOT"/{usr,lib,lib64,dev,scratch}` created a single literal directory named `{usr,lib,lib64,dev,scratch}` instead of five directories, causing a confusing downstream `mount: mount point does not exist` error that looked like a path bug.
**Root cause:** `bash_tool`'s shell is `/bin/sh` → `dash`, not `bash`. Brace expansion is a bash-ism; POSIX `sh` doesn't have it, and it fails silently (no error at the point of the mistake) rather than loudly.
**Fix:** Write out explicit `mkdir` calls per directory, or explicitly invoke `bash -c '...'` when brace expansion is wanted.
**Lesson:** Never assume bash-isms (brace expansion, `[[ ]]`, arrays) work in this tool's shell. Check `readlink -f /bin/sh` once per session if in doubt, or just avoid bashisms entirely.

### 2. Scrubbing environment at the wrong layer breaks the orchestration tools themselves
**What happened:** `subprocess.run(cmd, env={}, ...)` was meant to scrub the environment visible to *untrusted sandboxed code*, but `cmd` was the full `timeout | unshare | chroot | python3` chain — wiping `PATH` broke `unshare`'s own ability to find `chroot` via `PATH` lookup, producing `unshare: failed to execute chroot: No such file or directory`.
**Root cause:** Conflated "the environment the untrusted code should see" with "the environment the orchestration commands need to find each other." They're the same `env=` parameter in a naive implementation, but they need different guarantees.
**Fix:** Give the *outer* `subprocess.run`/`Popen` call a minimal working `PATH`; scrub the environment *inside* the bootstrap script (`os.environ.clear()`), immediately before the untrusted code runs — exactly where the guarantee actually needs to hold.
**Lesson:** When a security property ("X should see nothing") is implemented by manipulating a shared mechanism (environment, permissions, namespaces), check whether anything *else* depends on that same mechanism before assuming a blanket setting is safe.

### 3. `chroot` lives in `/usr/sbin`, not `/usr/bin`
**What happened:** After fixing #2 with `PATH="/usr/bin:/bin"`, `unshare` still failed to find `chroot`.
**Root cause:** `chroot` is a `sbin` binary on this system (`which chroot` → `/usr/sbin/chroot`), and the minimal `PATH` didn't include any `sbin` directory.
**Fix:** `PATH="/usr/sbin:/usr/bin:/sbin:/bin"`.
**Lesson:** Don't guess a minimal `PATH` — run `which <every binary you invoke>` once and build the `PATH` from the actual answers, not from a generic assumption about where standard tools live.

### 4. Python's `subprocess` reports signal termination as a **negative** returncode, not the shell's `128+signal` convention
**What happened:** Status-detection logic checked `proc.returncode == 137` (the shell convention for "killed by SIGKILL", `128+9`) and never matched, so every genuinely-timed-out execution was misclassified as `"completed"`.
**Root cause:** Python's `subprocess` module represents a signal-terminated child as a *negative* returncode (`-9` for SIGKILL) — a different, unrelated convention from what `$?` shows in a shell script.
**Fix:** Check `returncode is not None and returncode < 0`, not a specific positive magic number.
**Lesson:** When translating a shell-verified behavior (`timeout -s KILL N ...; echo $?` showing `137`) into Python's `subprocess`, verify the *Python-level* representation independently — don't assume the same number carries over across that boundary.

---

## Namespace / sandbox isolation gotchas (environment-specific, not code bugs)

These aren't bugs in the sense of "code that was wrong" — they're incorrect assumptions about what a given kernel/container environment actually enforces, discovered only by testing the real behavior instead of trusting the documented/expected semantics.

### 5. `RLIMIT_NPROC` silently unenforced under a user-namespace-mapped root
**What happened:** A fork-bomb test with `resource.setrlimit(RLIMIT_NPROC, (4, 4))` set inside the sandbox allowed all 50 attempted forks to succeed — no error, no crash, just silent non-enforcement.
**Root cause:** `RLIMIT_NPROC` accounting interacts with user-namespace UID remapping (`unshare --user --map-root-user`) in a way that doesn't reliably enforce the limit in this environment. This is a documented category of kernel/namespace quirk, not unique to this project.
**Fix:** Don't rely on `RLIMIT_NPROC` for fork containment here. Use a real cgroups `pids` controller instead — confirmed to actually work via an isolated test before trusting it in the real module.
**Lesson:** An in-process `resource.setrlimit()` call succeeding (no exception raised when *setting* it) is not evidence that the limit is actually *enforced*. Test the enforcement directly — deliberately exceed the limit and check the outcome — never assume from the setter succeeding.

### 6. `RLIMIT_CPU` + `SIGXCPU` crashes `unshare --fork`'s own signal handling
**What happened:** Any sandboxed execution that actually *hit* its `RLIMIT_CPU` limit caused the outer `unshare` process itself to crash with `sigprocmask unblock failed: Invalid argument`, rather than cleanly terminating the child.
**Root cause:** Confirmed via a minimal, isolated reproduction — bare `unshare --fork` wrapping nothing but a `RLIMIT_CPU` busy-loop, no chroot, no other namespaces — that this is `unshare --fork`'s own signal-handling logic breaking on `SIGXCPU` delivery in this specific container environment, not something caused by anything else this project's code does.
**Fix:** Don't rely on `RLIMIT_CPU` for CPU-time enforcement here. Wrap the whole invocation in an *external* `timeout -s KILL N`, which was independently verified to terminate a busy-loop reliably regardless of the in-process rlimit's problems.
**Lesson:** When a mechanism fails in a complex composed system (chroot + multiple namespaces + resource limits), isolate it to the smallest possible reproduction before concluding *why* it failed. The minimal repro here (two lines, no chroot) is what turned "some confusing crash somewhere in the sandbox" into "specifically `unshare --fork` + `SIGXCPU`, confirmed" — a claim precise enough to trust and document.

### 7. Race condition: joining a cgroup *after* `Popen()` returns is too late
**What happened:** Wiring a real, independently-verified-working cgroups `pids` controller into the actual sandbox module still failed intermittently — sometimes all 50 forks succeeded despite `pids.max=5`, sometimes it worked correctly, with no pattern visible from the outside.
**Root cause:** The code wrote the launched process's PID to `cgroup.procs` *after* `subprocess.Popen()` returned. A tight `fork()` loop can complete entirely (all 50 forks, microseconds each) before the calling Python code gets around to opening and writing that file — a classic time-of-check-to-time-of-use race.
**Fix:** Join the cgroup from `preexec_fn`, which runs synchronously *in the child*, after `fork()` but before `exec()` — guaranteeing cgroup membership is established before the process becomes anything that could start forking.
**Lesson:** "It passed once" is not evidence a race condition is fixed or absent, especially for anything involving process creation timing. Run any timing-sensitive fix multiple times (this project used 8 repeats, then 3 full-suite reruns) before trusting it — a single green run can be luck.

### 17. Cgroups `pids` controller path hardcoded to v1, silently degrading to a known-broken fallback on v2-only hosts
**What happened:** Bug #7's fix — a real cgroups `pids` controller for fork containment — was verified working and marked "CLOSED" in `security-review-sandbox.md`. Re-validating on a real deployment target (`scripts/preflight_check.py` against a Proxmox LXC guest, per Section 7.3) found fork containment failing again: `no cgroups v1 'pids' controller`.
**Root cause:** Both `sandbox.py`'s `_cgroup_pids_available()` and the preflight script's own copy hardcoded the cgroups v1 path, `/sys/fs/cgroup/pids`. The Proxmox LXC guest runs cgroups v2 only (unified hierarchy) — that path never exists there. `_cgroup_pids_available()` returned `False`, so `run_sandboxed()` silently fell back to `RLIMIT_NPROC` — which bug #5 already proved is unenforced in this environment. Fork containment was therefore not actually enforced by anything on that host, despite the earlier fix and its "CLOSED" status.
**Fix:** Added `_cgroup_pids_version()`, which checks for the v1 path first, then falls back to checking `/sys/fs/cgroup/cgroup.controllers` for a `pids` entry (the v2 signal), returning `"v1"`, `"v2"`, or `None`. `_make_pids_cgroup()` now takes the detected version and creates the cgroup under the right root — for v2, this also requires enabling `pids` in the parent's `cgroup.subtree_control` before a child cgroup can use it, which v1 never needed. Verified against the real Proxmox LXC guest's actual cgroups v2 setup: fork containment now blocks correctly (forks blocked after 2, against a limit of 5).
**Lesson:** A fix verified as "CLOSED" against one environment is a claim about *that environment*, not a universal one — exactly what `security-review-sandbox.md` Section 7.3 already says to guard against for the CPU-time gap, and it turned out to apply here too, to a gap that had already been marked resolved. Re-validating on a new deployment target isn't just for catching *new* problems; it can un-close old ones that were only ever closed for the reference environment's specific cgroups version.

---

## Storage / correctness bugs

### 8. Checkpoint entry's own hash computed before a field was attached to it
**What happened:** `write_checkpoint()` computed `entry_hash` from a canonical dict that excluded `snapshot_id` (correct, since the ID is derived *from* the content), but then a second version of the object — *including* `snapshot_id` — was stored under a *different* key computed from that second version's own new hash. The index pointed at the first hash, but nothing useful was stored there under a retrievable, self-consistent shape. Reads failed.
**Root cause:** Content-addressing requires strict discipline about exactly what bytes produce the address — mixing "the thing I hash" and "the thing I store" when they're not byte-identical breaks the address→content mapping silently until read time.
**Fix:** Store only the canonical form (without the self-referential field) under its own hash; reattach the field (`snapshot_id`) at *read* time instead of trying to store two versions.
**Lesson:** In any content-addressed system, be explicit and consistent about whether a field is *part of* what's hashed or *derived from* the hash — never let an object simultaneously contain its own address and be hashed to produce that same address.

### 9. `verify_chain()` only checked entry metadata, not payload content
**What happened:** A test that corrupted a checkpoint's *payload* (not its metadata record) still reported the chain as verified — a corrupted checkpoint body would have silently passed integrity checking.
**Root cause:** The verification loop called `read_entry()` (which validates the metadata record's own hash) but never called `cas.get()` on the entry's `payload_ref` — so the payload's integrity was never actually checked, only referenced.
**Fix:** `verify_chain()` now also calls `self.cas.get(entry.payload_ref)` for every entry, which triggers the same tamper-detection the metadata check already had.
**Lesson:** "Verified" needs to mean everything a caller would reasonably assume is covered. A chain-integrity check that only checks chain *links* but not the *content* those links point to is a checklist item that looks complete but isn't — ask "what would a corrupted version of this actually look like, and does my check catch that specific case" rather than "does my check run without error."

---

## Data-shape / API bugs

### 10. Calling `.to_dict()` on data that was already a plain dict
**What happened:** `list_questions()` in the HTTP API called `e.to_dict()` on every value from the Question Ledger's state — but those values were already plain dicts (because `ledger.submit()` stores `entry.to_dict()` into the JSON-serialized checkpoint state, not the dataclass instance itself). `AttributeError: 'dict' object has no attribute 'to_dict'` on every request.
**Root cause:** Assumed the in-memory shape of data read back from a checkpoint matches the shape of the object that was originally written, without checking — but checkpoints round-trip through JSON serialization, which already converts dataclasses to dicts.
**Fix:** Return the dicts directly; don't call `.to_dict()` on data that's already past that stage.
**Lesson:** After any serialize/deserialize round-trip (a checkpoint, an HTTP response, a cache), verify the actual runtime type of what comes back — don't assume it's still the rich object type it started as.

---

## Test-authoring bugs (not library bugs, but worth the same scrutiny)

### 11. Test question missing the keyword needed for routing
**What happened:** A synthesis test called `framing_round("17", "q1")` — but the Mathematics agent's jurisdiction check looks for domain keywords like "prime" in the question text, and the bare string `"17"` didn't contain any, so no agent was routed at all and the test's assumptions about the result were wrong from the start.
**Fix:** Use `"is 17 prime?"`, matching what a real caller would send.
**Lesson:** When testing routing/dispatch logic, use realistic inputs that would actually trigger the routing — a minimal-looking test input can silently bypass the exact logic the test claims to exercise.

### 12. Test had an agent incorrectly cross-examining its own claim
**What happened:** A test called `MasterOfMathematics().cross_examine(claim, ...)` where `claim.issuing_agent == "Mathematics"` — but `cross_examine` correctly, deliberately returns `None` immediately when an agent is asked to examine its own claim (Section 3.3's design: agents don't cross-talk with themselves). The test's assumption was wrong, not the code.
**Fix:** Construct the test claim with a different `issuing_agent` so the cross-examination path actually runs.
**Lesson:** When a test fails, check whether the *code* is wrong or the *test's setup* violates an intentional invariant the code correctly enforces — don't assume test failure always means implementation bug.

### 13. Test read the wrong level of nested checkpoint state on resume
**What happened:** A resume test did `runner2 = SingleUnitRunner(log2, shared_state=state)` where `state = log2.read_latest()` — but `read_latest()` returns the *whole* checkpoint object (`{"units": {...}, "shared_state": {...}}`), not the `shared_state` sub-object directly.
**Fix:** `shared_state=state["shared_state"]`.
**Lesson:** When a stored structure is itself a container of other structures, be precise about which *level* a given read call returns — especially in tests, where an off-by-one-level bug can silently pass by accident (e.g., an empty dict where an empty dict was also a valid starting state) rather than failing loudly.

### 14. Test asserted the wrong threshold for the Reputability grading policy
**What happened:** A test expected a source to reach `"rejected"` after 1 corroboration + 3 challenges, but the policy's actual rule requires **zero** corroborations before "rejected" — the test's own expectation was wrong, not the grading logic.
**Fix:** Rewrote the test scenario to have 0 corroborations before accumulating challenges.
**Lesson:** When writing a test against a policy you just wrote yourself, re-read the policy's actual conditions rather than writing the test from memory/intuition of what you meant it to do — the two can silently diverge.

---

## Documentation-accuracy mistakes

### 15. Claimed two unrelated bugs "shared a root cause" without verifying that claim
**What happened:** An earlier version of `security-review-sandbox.md` stated the CPU-time gap (#6 above) and the fork-containment gap (#5 above) "share a root cause: this specific container/kernel environment's interaction with `unshare --fork`'s signal handling." Further investigation showed this was false — `RLIMIT_NPROC`'s failure mode is silent non-enforcement (no crash, no signal involved at all), completely unrelated to `RLIMIT_CPU`'s signal-handling crash. They just happened to both fail in the same testing session.
**Fix:** Corrected the document once the real, separate root causes were isolated (see #5 and #6).
**Lesson:** Don't merge two failures into one narrative just because they occurred close together or both involve "the same environment." Isolate each with its own minimal reproduction before claiming a shared cause — convenient-sounding unification is a bias, not a finding, until independently tested.

---

## Deployment host gotchas (Proxmox-specific, not code bugs)

### 18. Docker's `FORWARD`-chain DROP policy silently breaks Proxmox bridge networking for every guest, not just Docker's own
**What happened:** After extensive setup (static IP, MAC pinning, disabling Proxmox's per-guest and cluster-wide firewalls), the test LXC (VMID 104) still couldn't reach the LAN gateway, the internet, or be reached by another machine on the same subnet — while the Proxmox host itself could always reach the container fine, and ARP resolution for the container always succeeded.
**Root cause:** The Proxmox host also runs Docker (for something unrelated to this project). Docker manages the kernel's `iptables`/`nftables` `FORWARD` chain directly, setting its default policy to `DROP` and only explicitly allowing traffic tied to its own managed bridges/interfaces. Because `bridge-nf-call-iptables` is active, this also catches ordinary L2-bridged IP traffic through `vmbr0` — any guest talking to the gateway, or another LAN machine talking to a guest — even though none of that traffic has anything to do with Docker. ARP isn't IP traffic, so it bypasses this chain entirely, which is exactly why ARP kept succeeding while ICMP/TCP silently failed. Host↔guest traffic was also unaffected, because that's the host's own INPUT/OUTPUT chain, not FORWARD — which made "the host can always reach the container" a misleading signal that things were mostly fine.
**Fix:** One rule in the chain Docker guarantees it will never overwrite: `iptables -I DOCKER-USER -i vmbr0 -o vmbr0 -j ACCEPT`. Not yet confirmed persisted across a host reboot (no `iptables-persistent`/`netfilter-persistent` confirmed installed) — re-check after any reboot of `proxmox01`.
**Lesson:** When a Linux host runs both a hypervisor (Proxmox) and a container engine (Docker) that each manage their own `iptables`/`nftables` rules, symptoms that look like a Proxmox/bridge/ARP/DHCP problem can actually be the *other* system's firewall rules, since both share the same kernel netfilter tables. The specific tell worth remembering: **ARP resolves fine but ICMP/TCP across the bridge doesn't** points at an IP-layer filter (something in `iptables -L FORWARD`), not an L2/bridge/ARP-cache problem — check that first, before spending time on Proxmox ACLs, per-guest/cluster firewall settings, MAC/ARP staleness, or physical-LAN theories (switch port-security, AP isolation, VLANs). All four were chased first here and were dead ends.

### 19. A host-only setup script assumed `jq` would be present on the Proxmox host itself
**What happened:** `infra/proxmox/06-setup-backups.sh`'s first command, `pvesh set /storage/local --content $(pvesh get /storage/local --output-format json | jq -r '.content'),backup`, hit `jq: command not found` on `proxmox01` (host, not a guest). The broken `jq` pipe made the `$(...)` substitution empty, so the command that actually ran was `pvesh set /storage/local --content ,backup` — which Proxmox accepted, silently **replacing** `local`'s content types with just `backup`, dropping `vztmpl` and `iso` entirely. The rest of the script (systemd unit, timer, first backup run) still completed successfully despite this — `backup` was still a valid content type, so `vzdump` worked and produced real archives, which made the corruption easy to miss behind an apparently-successful run. Confirmed via `pvesh get /storage/local` afterward: `content: backup` only. The two already-downloaded templates (`debian-12-standard`, `ubuntu-24.04-standard`) were never deleted — just no longer listed while `vztmpl` was missing from the content-type flag.
**Root cause:** Two compounding mistakes: (1) `jq` had been explicitly `apt install`ed on the two LXC guests (104, 106) earlier in the session, creating an unstated assumption it was "just available" everywhere in this project's tooling — the Proxmox **host** itself is a separate machine with its own package set, never verified to include `jq`. (2) The script computed a *replacement* value (`--content $(new list),backup`) instead of an additive one, so when the substitution silently produced garbage (empty string, not an error), the result was silent data loss rather than a loud failure.
**Fix:** Restored with `pvesh set /storage/local --content iso,vztmpl,backup` — confirmed templates reappeared in listing immediately (they were on disk the whole time). Rewrote the script's `jq` usage as `grep -o '"content":"[^"]*"' | cut -d'"' -f4` on raw JSON (zero host-side dependencies), and added an explicit check that aborts the script if that extraction comes back empty, rather than silently proceeding to build a `--content` value from nothing.
**Lesson:** Two lessons, not one. First: "it mostly worked" is not "it worked as designed" — a script that silently skips one step and still produces a plausible-looking overall result (real backup files existed) can hide real data loss that only surfaces later. Second, more generally: **when a command constructs a config value by substituting the output of another command, treat an empty/garbled substitution as a hard failure, not as "whatever the flag defaults to."** `--content ,backup` should never have been sent at all — validate the substituted value before using it to *replace* something, especially anything that can silently drop existing configuration rather than erroring.

---

## Recurring process mistake (not a code bug — a workflow one)

### 16. Duplicate "final" print statement when appending new steps to a narrated demo script
**What happened:** `demo_brain.py` ends with `print("\n=== brain demo complete ===")`. On **two separate occasions**, new narrated steps were appended by inserting content *before* that existing final print — without removing it first — producing the "complete" banner printed once in the middle of the script and again at the true end.
**Root cause:** Treating "add a new step" as "paste new content in front of the last line" without first checking what the last line already was.
**Fix:** Both times, fixed by locating the existing final print and folding it into the edit rather than leaving a duplicate.
**Lesson:** This is a **repeated** mistake, which is the whole point of this file existing — catching a bug once doesn't prevent it from happening again in a *different* file edit later, if the underlying habit that caused it isn't changed. Before appending to any script that has a "final output" line, `grep` for that line first and treat it as something to move, not something to leave in place while inserting before it.

---

## How to use this file

Before writing similar code again in this project:
- **Any new sandboxing/namespace work:** re-read entries 5–7 and 17. Test enforcement directly, isolate failures to minimal reproductions, re-verify timing-sensitive fixes multiple times before trusting them, and never assume a mechanism verified on one environment (cgroups version, kernel, container runtime) carries over to the next deployment target unvalidated.
- **Any Proxmox guest networking problem (unreachable gateway, unreachable from another LAN machine, DHCP not working):** re-read entry 18 first. Check `iptables -L FORWARD -n -v` before Proxmox ACLs, firewall settings, or physical-LAN theories — the ARP-works-but-ICMP-doesn't fingerprint means check the host's Docker/iptables rules first.
- **Any new script meant to run directly on the Proxmox host** (not a guest): re-read entry 19. Don't assume `jq`/`curl`/anything beyond a stock install is present — that assumption is only safe for the guest-side tooling this project deliberately installed it on.
- **Any new content-addressed or checkpoint code:** re-read entries 8–9. Be explicit about what's hashed vs. stored vs. derived, and make sure "verified" checks everything a caller would assume it checks.
- **Any new API/serialization boundary:** re-read entry 10. Check the actual runtime type after a round-trip.
- **Any new test:** re-read entries 11–14 before assuming a failing test means the implementation is wrong.
- **Any new demo/narrated script:** re-read entry 16 before appending to it.
- **Any security or reliability claim in a design doc:** re-read entry 15 before writing "both X and Y share a cause" — prove it, don't infer it.

This file should keep growing as real bugs are found — append to it, don't let it go stale once written.
