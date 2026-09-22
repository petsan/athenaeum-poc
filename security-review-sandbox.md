# Security Review: Sandboxed Execution Capability

**Status:** Review, not implementation. This document exists specifically because `body-design.md` Section 4.6 says the execution sandbox needs "a dedicated security review before real code execution is enabled" and flags it explicitly as off by default (`execution_sandbox.enabled: false`) until that happens. Nothing here authorizes flipping that flag — this is the review, not its conclusion that the review passed.

**Why this exists at all:** the Engineering Master Agent's `executable` claim type (`brain-design.md` Section 2.2, 3.5) only means what it claims to mean — "this was actually run and verified" — if the thing it ran in is genuinely isolated. If the sandbox leaks, every `executable` claim in the system inherits that risk silently, because the claim's confidence grammar doesn't distinguish "verified in an isolated sandbox" from "verified in something that turned out not to be isolated." That's a system-wide integrity problem, not a contained one, which is why this gets a dedicated pass rather than being folded into an ordinary task.

---

## 1. What this capability is asked to do

Per `body-design.md` Section 4.6, the sandbox receives code and inputs from the Engineering agent, runs it, and returns output/pass-fail/error — nothing else. Section 4.6's stated properties:
- No network egress
- No access to any store beyond an explicitly provisioned scratch area
- No persistence beyond a single execution request
- Resource-bounded (CPU/memory/time), scaled against currently available resources
- Stateless per invocation

This review assumes that scope and does not expand it. If a future need arises for the sandbox to do more (e.g., multi-step stateful execution, network access to a specific allowlisted resource), that is a **new** capability requiring its **own** review, not an amendment to this one.

## 2. Threat model

### 2.1 Who/what can reach the sandbox, and what they might contain
The sandbox executes code that ultimately traces back to two sources, both already flagged elsewhere in this project as untrusted:
- **Ingested corpus material**, which `brain-design.md` Section 12 already treats as evidence-only, never instructions — but a compromised or adversarial source could still contain content that, if it ever influenced what code the Engineering agent decides to write or run, could be an indirect injection vector.
- **Human input** (`brain-design.md` Section 11), which similarly is evidence-only but could contain adversarially-crafted code samples, or content designed to manipulate the Engineering agent into generating unsafe code.

Neither of these needs to be a deliberate attack for this to matter — an ordinary bug in a generated script (an infinite loop, a fork bomb, an accidental `rm -rf`-equivalent) is exactly as dangerous to an unisolated sandbox as a deliberate one, and is far more likely to occur first. **The threat model below treats "accidental unsafe code" and "adversarial unsafe code" as needing the same containment, because the failure mode is identical from the sandbox's perspective.**

### 2.2 What a failure looks like, ranked by severity
1. **Host compromise / lateral movement.** Executed code escapes the sandbox boundary and gains access to the Body's actual stores (Belief Graph, Provenance Ledger, checkpoints), the resource monitor, or the underlying Proxmox host. This is the severe case — it would compromise the append-only, tamper-evident guarantees the entire Body design is built on, from inside.
2. **Data exfiltration.** Executed code reads something it shouldn't (another execution's leftover state, host filesystem contents, credentials) and gets it out via network egress, even if it never modifies anything. Mitigated primarily by "no network egress" as a hard invariant, but worth stating as its own failure mode since a sandbox can fail this specifically even while succeeding at containment otherwise (e.g., a covert channel).
3. **Resource exhaustion / denial of service.** Executed code consumes CPU/memory/disk without bound, starving the rest of the Body's work-unit scheduler (Section 7) — this doesn't compromise data, but it does compromise the "elastic, never lose progress" guarantee the whole scheduler exists to provide.
4. **Cross-invocation state leakage.** One execution's data (even non-malicious) persists and becomes visible to a later, unrelated execution — a confidentiality/correctness issue rather than a compromise, but it would silently violate the "stateless per invocation" guarantee `executable` claims depend on for their meaning.
5. **False-positive containment.** The sandbox reports a clean pass/fail when it actually failed to isolate correctly — this is the failure mode that's easiest to miss, because nothing looks wrong until it's exploited. Worth calling out as its own category because a security review that only checks "does it isolate" and not "does it correctly *report* when isolation fails" leaves this open.

### 2.3 Explicitly out of scope for this review
- The correctness of code the Engineering agent generates (that's a reasoning-quality question, covered by `brain-design.md` Section 9's evaluation strategy, not a security question).
- Trust in the model backing the Engineering agent (that's the Local Model Serving Layer's concern, `body-design.md` Section 4.5).
- Anything beyond the single-request, stateless, no-network scope defined in Section 1 above.

## 3. Required properties before `execution_sandbox.enabled` can be set `true`

These map directly to `acceptance-criteria.md`'s Task 23g entry, restated here with the reasoning behind each, since a checklist without rationale is easy to satisfy technically while missing the point:

| Property | Why it's required | How it should be verified |
|---|---|---|
| **Process/container-level isolation**, not merely a restricted interpreter (e.g., not just a Python `exec()` with a blocked builtins list) | Restricted-interpreter sandboxes have a long, consistent history of escape techniques (reflection, import tricks, C-extension access) — this is a known-insufficient pattern, not a hypothetical concern | Independent verification that the isolation mechanism is OS/hypervisor-level (container, VM, or equivalent), not language-level trickery |
| **No network namespace access at all**, not just a firewalled one | A firewalled-but-present network stack is one misconfiguration away from egress; a genuinely absent network namespace has no such failure mode | Attempt real network calls (DNS resolution, raw sockets, not just HTTP) from inside an execution and confirm they fail at the OS level, not an application-level block |
| **Filesystem access limited to a fresh, empty scratch directory per invocation** | Prevents both cross-invocation leakage (2.2.4) and any path to the Body's real stores (2.2.1) | Attempt to read paths outside the scratch directory (absolute paths, `../` traversal, symlink tricks) and confirm failure; confirm the scratch directory is empty at the start of every invocation, not just "usually" empty |
| **Hard resource limits enforced by the isolation layer itself**, not just requested/advisory limits | An advisory limit that misbehaving code can ignore doesn't prevent 2.2.3 | Deliberately exceed `cpu_time_limit_seconds` and `memory_limit_mb` and confirm the execution is forcibly terminated, not merely warned about |
| **Explicit, tested failure-closed behavior** | Per 2.2.5 — the dangerous case is a failure that looks like success | Every fault-injection scenario in the table below must produce a result the caller can distinguish from a genuine successful execution — never a silent pass |
| **No credentials, tokens, or environment variables from the host process available inside the sandbox** | An execution with access to ambient credentials could use those for exfiltration or further compromise even without network egress of its own, if the credentials get returned as output | Confirm the execution environment's variable/credential surface is empty or contains only an explicit, minimal allowlist |

## 4. Fault-injection scenarios required before sign-off

Matching the same discipline as `acceptance-criteria.md`'s other entries — each of these needs a concrete, automated test with a clear pass/fail line, not a manual check performed once:

1. Code attempting DNS resolution, raw socket connection, and HTTP request — all three must fail at the OS/network-namespace level.
2. Code attempting to read a path outside the scratch directory via absolute path, relative traversal (`../../`), and a symlink created to point outside the scratch directory.
3. Code attempting to write outside the scratch directory, same three vectors.
4. Code that spawns child processes or forks — must be contained within the same isolation boundary, not escape it.
5. Code that deliberately busy-loops past `cpu_time_limit_seconds` — must be terminated, and the termination must be distinguishable in the result from a normal completion.
6. Code that allocates memory past `memory_limit_mb` — same requirement.
7. Two sequential, unrelated executions where the first writes to its scratch directory — the second must start with a genuinely empty scratch directory, verified by listing it, not assumed.
8. Code that attempts to read environment variables — must see an empty or minimal allowlisted set, not the host process's actual environment.

## 5. What this review does NOT do

This document identifies what must be true and what must be tested. It does not:
- Select a specific isolation technology (container runtime, VM, gVisor-style sandbox, etc.) — that's an implementation decision for whoever builds Task 23g, informed by this review's required properties, not decided by it.
- Implement or run any of the fault-injection scenarios above — they're specified here as acceptance criteria, matching the pattern already established in `acceptance-criteria.md`, and should be added there once implementation begins.
- Certify that the eventual implementation is safe — only that implementation satisfies these criteria, which is a necessary condition this review can specify, not a sufficient one it can grant in advance.

## 6. Recommendation

`execution_sandbox.enabled` should remain `false` until every property in Section 3 is implemented and every scenario in Section 4 has a passing automated test. Given this project's established pattern of not marking anything "done" without an actual passing test to point to, the same standard should apply here — arguably more strictly, given what's at stake if this specific component is wrong. This review does not recommend a timeline or deprioritize this work; it only insists that when it does happen, it happens against these criteria rather than being inferred after the fact from whatever gets built first.

---

## 7. Implementation scorecard (added after Task 23g was started)

A reference implementation (`src/athenaeum_body/sandbox.py`) was built against Sections 3–4 above and empirically tested — every scenario below was actually run, not assumed. **`execution_sandbox.enabled` remains `false` regardless of these results** — passing tests here is necessary, not sufficient, per Section 5, and two specific gaps below are unresolved.

| Scenario (Section 4) | Result | Mechanism | Notes |
|---|---|---|---|
| 1 — DNS, raw socket, HTTP egress | **PASS** | Empty network namespace (`unshare --net`) | Fails at the OS level, not an application-layer block |
| 2 — Read outside scratch (absolute, traversal, symlink) | **PASS** | `chroot` into a minimal root with only `/usr`, `/lib`, `/lib64` (read-only) and a fresh `/scratch` bind-mounted | Paths outside the mounted set don't exist in the sandbox's filesystem view at all — structural, not permission-based |
| 3 — Write outside scratch | **PASS** | Same mechanism as scenario 2 | |
| 4 — Child process / fork containment | **PASS (closed after further investigation — see 7.1)** | Real cgroups `pids` controller (`pids.max` per invocation), process joined via `preexec_fn` (synchronous, before the child execs into anything) | Initially scored PARTIAL using `RLIMIT_NPROC`, which was found to be silently unenforced in this environment (50/50 forks succeeded against a limit of 4, no error). Replaced with a real cgroups `pids` controller, which does work — but only once a race condition in how the process joined the cgroup was found and fixed (see 7.1) |
| 5 — CPU time limit exceeded | **PASS, but not via the originally-specified mechanism — see gap below** | External `timeout -s KILL` wrapping the whole invocation | In-process `RLIMIT_CPU` (SIGXCPU) was found to reliably break `unshare --fork`'s own signal handling in this container environment — confirmed via a minimal reproduction with no chroot/mount/pid namespaces at all, just bare `unshare --fork`. This is an environment limitation, not fixable by changing how this module invokes it (unlike the fork-containment gap, which turned out to be a bug in this module, not the environment) |
| 6 — Memory limit exceeded | **PASS** | `RLIMIT_AS`, set by the harness before untrusted code runs | Synchronous `MemoryError`, no signal-delivery involved — none of scenario 5's problem applies here |
| 7 — Scratch directory fresh across invocations | **PASS** | Fresh `tempfile.mkdtemp()` per call, verified empty at the start of a second invocation after the first wrote to it | |
| 8 — Environment variables scrubbed | **PASS** | `os.environ.clear()` called from inside the bootstrap, before untrusted code runs | Initially miscomposed — passing an empty environment to the *outer* orchestration commands broke `unshare`/`chroot`'s own ability to find each other via `PATH`; fixed by giving the outer commands a minimal `PATH` and scrubbing the environment from inside the bootstrap instead, exactly where the guarantee actually needs to hold |

### 7.1 One gap closed, one gap remains — both investigated to a real conclusion, not left as guesses

**Fork containment (originally flagged as a gap): CLOSED.** Further investigation found `RLIMIT_NPROC`'s non-enforcement was a genuine, separate finding from the CPU-time issue (not, as an earlier draft of this document speculated, the "same root cause" — that speculation was wrong and has been corrected here). Replacing it with a real cgroups `pids` controller initially *also* appeared to fail intermittently — investigation found this was a race condition in this module's own code: the sandboxed process was being added to the cgroup *after* `Popen()` returned, by which point a tight `fork()` loop can complete entirely before the controlling Python code gets around to writing `cgroup.procs`. Fixed by joining the cgroup from `preexec_fn`, which runs synchronously in the child immediately after `fork()` and before it execs into anything — verified stable across repeated runs afterward. This is the kind of bug that would have shipped silently as "occasionally works" if the fix had been accepted on the first passing test run instead of being tested repeatedly.

**CPU-time enforcement (still open): NOT CLOSED, confirmed as an environment limitation rather than a fixable bug.** Unlike the fork-containment issue above, this was reproduced with a minimal, isolated test case — bare `unshare --fork` wrapping a process that sets `RLIMIT_CPU` and receives `SIGXCPU`, with no chroot, no other namespaces, nothing else involved — and it crashes `unshare` itself every time. This rules out the hypothesis that it was caused by this module's composition of namespaces/mounts/chroot; it is specifically `unshare --fork`'s interaction with this signal, in this container environment. The mitigation (external wall-clock `timeout -s KILL`, independently verified reliable) stands as the actual enforcement mechanism for CPU-bound runaway code, which — for single-threaded, CPU-bound execution specifically — is a reasonable proxy for CPU time in practice, even though it is not the mechanism originally specified in Section 3's table.

### 7.2 What would need to be true before this review's recommendation (Section 6) changes
- Either the remaining CPU-time gap is closed (e.g., a working `RLIMIT_CPU` path confirmed on the actual production kernel/container runtime, different from this one), or
- The design is revised to explicitly accept external wall-clock termination as the primary time defense for CPU-bound code, with that decision made deliberately by whoever owns this system, not defaulted into by this document.

Either way, that is a decision for whoever enables this in production, informed by this scorecard — not something this review resolves on its own. The fork-containment gap that was originally listed alongside it no longer needs this decision; it's closed.

### 7.3 Re-validate on every new deployment target, not just once
This scorecard is a report on one specific environment. `scripts/preflight_check.py` (standalone, no repo dependency beyond Python's standard library and the same `unshare`/`chroot`/`mount`/`timeout` tools the real sandbox needs) re-runs every scenario above, including the isolated `RLIMIT_CPU` reproduction that answers the open question directly. **Run it on any new target — a fresh VM, an LXC container, bare metal — before trusting this document's scorecard to carry over, and especially before changing `execution_sandbox.enabled`.** If it finds `RLIMIT_CPU` works correctly there, that's a genuine capability upgrade for that environment specifically, and this section should be updated to reflect it rather than assuming the reference environment's limitation is universal.
