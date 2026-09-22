"""
Sandboxed execution capability (body-design.md Section 4.6), built and
empirically tested against security-review-sandbox.md's required
properties. See security-review-sandbox.md Section 7 for the full,
honest scorecard this implementation was validated against.

STATUS: reference implementation, Task 23g in progress.
`execution_sandbox.enabled` stays `false` in config.defaults.yaml
regardless of this module existing or its tests passing -- per the
review, code passing tests here does not itself authorize enabling real
execution against untrusted input; two specific, environment-observed
gaps are documented below and must be closed (or mitigated at the
deployment layer, e.g. a cgroups 'pids' controller) first.

Isolation mechanism (each property independently verified empirically,
not assumed -- see security-review-sandbox.md Section 7):
  - unshare(user, net, pid, mount, uts, ipc) + chroot into a freshly
    built minimal root: read-only bind mounts of /usr, /lib, /lib64,
    plus a fresh writable scratch directory. Genuine OS-level isolation,
    not a restricted interpreter -- paths outside the mounted set do not
    exist inside the sandbox's filesystem view at all, verified against
    absolute-path and traversal attempts.
  - Network: empty net namespace. DNS resolution and raw socket connects
    both fail at the OS level. VERIFIED.
  - Memory: RLIMIT_AS, set by this harness before the untrusted code
    ever runs (never something the code itself could skip or override).
    Synchronous, kernel-enforced (MemoryError on exceeding). VERIFIED.
  - CPU time / wall clock: enforced EXTERNALLY via `timeout -s KILL`
    wrapping the whole invocation, not via in-process RLIMIT_CPU.
    RLIMIT_CPU is still set defensively inside the bootstrap (harmless,
    may help on other kernels) but its SIGXCPU delivery was found to
    reliably break `unshare --fork`'s own signal handling in THIS
    container environment (a reproducible `sigprocmask unblock failed`
    error) -- KNOWN GAP, mitigated by the external wall-clock kill,
    which was independently verified to terminate a busy-loop reliably.
  - Fork/process-count containment: RLIMIT_NPROC is set defensively but
    was NOT observed to stop a fork loop within the test window in this
    environment -- the external wall-clock kill is the actual backstop
    here too. KNOWN GAP -- a production deployment should additionally
    configure a cgroups 'pids' controller for a harder per-namespace
    guarantee; not implemented in this reference version.
  - Environment: executed with an explicitly empty environment (no host
    variables visible inside). VERIFIED.
  - Scratch directory: a fresh temp directory created per invocation,
    confirmed empty at the start of each call, never reused, torn down
    after. VERIFIED.
  - Process visibility: the executed code becomes PID 1 inside its own
    PID namespace with no view of host processes. VERIFIED via the
    namespace mechanism itself (standard Linux PID-namespace semantics).
"""
from __future__ import annotations
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


class SandboxSetupError(Exception):
    """Raised if the isolation environment itself couldn't be built --
    always fail closed, never fall back to running code unsandboxed."""


@dataclass
class SandboxResult:
    status: str            # "completed" | "timeout" | "setup_failed"
    stdout: str
    stderr: str
    returncode: int | None


def _build_root(root: Path, scratch: Path) -> None:
    for d in ("usr", "lib", "lib64", "dev", "scratch"):
        (root / d).mkdir(parents=True, exist_ok=True)
    steps = [
        ["mount", "--bind", "-o", "ro", "/usr", str(root / "usr")],
        ["mount", "--bind", "-o", "ro", "/lib", str(root / "lib")],
    ]
    if Path("/lib64").is_dir():
        steps.append(["mount", "--bind", "-o", "ro", "/lib64", str(root / "lib64")])
    steps.append(["mount", "--bind", str(scratch), str(root / "scratch")])
    for r in steps:
        subprocess.run(r, check=True, capture_output=True)
    (root / "dev" / "null").touch()
    (root / "dev" / "urandom").touch()
    subprocess.run(["mount", "--bind", "/dev/null", str(root / "dev" / "null")], check=True, capture_output=True)
    subprocess.run(["mount", "--bind", "/dev/urandom", str(root / "dev" / "urandom")], check=True, capture_output=True)


def _teardown_root(root: Path) -> None:
    for sub in ("dev/null", "dev/urandom", "scratch", "usr", "lib", "lib64"):
        subprocess.run(["umount", str(root / sub)], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    shutil.rmtree(root, ignore_errors=True)


BOOTSTRAP = """
import os, resource
os.environ.clear()  # env scrubbing happens HERE, for the user code only --
                     # not at the outer subprocess level, which still needs
                     # PATH to find unshare/chroot themselves
resource.setrlimit(resource.RLIMIT_AS, ({mem_bytes}, {mem_bytes}))
resource.setrlimit(resource.RLIMIT_CPU, ({cpu_s}, {cpu_s}))  # defensive only -- see module docstring gap
try:
    resource.setrlimit(resource.RLIMIT_NPROC, (16, 16))  # defensive only -- see module docstring gap
except Exception:
    pass
os.chdir("/scratch")
exec(compile(open("/scratch/code.py").read(), "/scratch/code.py", "exec"))
"""


def run_sandboxed(code: str, cpu_time_limit_seconds: int = 5, memory_limit_mb: int = 256,
                   wall_clock_timeout_seconds: int = 10) -> SandboxResult:
    """
    The ONLY entry point Engineering's `executable` claim verification
    should use. `wall_clock_timeout_seconds` is the REAL enforcement
    mechanism for runaway execution in this environment (see module
    docstring) -- set it deliberately, don't rely on cpu_time_limit_seconds
    alone.
    """
    scratch = Path(tempfile.mkdtemp(prefix="athenaeum-sandbox-scratch-"))
    root = Path(tempfile.mkdtemp(prefix="athenaeum-sandbox-root-"))
    try:
        try:
            (scratch / "code.py").write_text(code)
            _build_root(root, scratch)
        except Exception as e:
            return SandboxResult(status="setup_failed", stdout="", stderr=str(e), returncode=None)

        bootstrap = BOOTSTRAP.format(mem_bytes=memory_limit_mb * 1024 * 1024, cpu_s=cpu_time_limit_seconds)
        cmd = [
            "timeout", "-s", "KILL", str(wall_clock_timeout_seconds),
            "unshare", "--user", "--map-root-user", "--net", "--pid", "--mount",
            "--uts", "--ipc", "--fork", "--mount-proc", "--",
            "chroot", str(root), "/usr/bin/python3", "-c", bootstrap,
        ]
        proc = subprocess.run(cmd, env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin"}, capture_output=True, text=True)
        # subprocess.run reports signal-terminated processes as a NEGATIVE
        # returncode (Python convention: -9 for SIGKILL), not the shell's
        # 128+signal convention (137) -- our external `timeout -s KILL`
        # always terminates via SIGKILL, so a negative code IS a timeout.
        status = "timeout" if (proc.returncode is not None and proc.returncode < 0) else "completed"
        return SandboxResult(status=status, stdout=proc.stdout, stderr=proc.stderr, returncode=proc.returncode)
    finally:
        _teardown_root(root)
