#!/usr/bin/env python3
"""
Athenaeum sandbox preflight check -- standalone, no repo dependency.

Run this directly on any target deployment host (a fresh VM, an LXC
container, bare metal) BEFORE trusting security-review-sandbox.md's
scorecard to carry over from wherever it was last validated. It re-runs
every scenario from that review, plus the specific minimal reproduction
that isolates the one open question: does RLIMIT_CPU work correctly
under `unshare --fork` on THIS kernel, or does it need the wall-clock
fallback that src/athenaeum_body/sandbox.py currently uses by default.

Usage:
    sudo python3 preflight_check.py

Requires: root (or CAP_SYS_ADMIN), and unshare/chroot/mount/umount/timeout
from util-linux/coreutils -- the same tools the real sandbox module needs,
so if this script's prerequisite check fails, the real module would fail
identically.

Exit code: 0 if every scenario passed as specified, 1 if anything needs
attention (see the summary at the end -- a non-zero exit does not
necessarily mean "unsafe to deploy," it means "read the summary before
deciding," since some findings (like the CPU one) have a known-good
fallback already built into the real module.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

RESULTS = []


def check(name, fn):
    print(f"--- {name} ---")
    try:
        ok, detail = fn()
    except Exception as e:
        ok, detail = False, f"raised {type(e).__name__}: {e}"
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {detail}\n")
    RESULTS.append((name, ok, detail))
    return ok


# ---------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------

def prereqs():
    if os.geteuid() != 0:
        return False, "not running as root -- re-run with sudo/as root"
    missing = [t for t in ("unshare", "chroot", "mount", "umount", "timeout")
               if shutil.which(t) is None]
    if missing:
        return False, f"missing required tools: {missing}"
    for p in ("/usr", "/lib"):
        if not Path(p).is_dir():
            return False, f"expected host path {p} not found"
    return True, "root + all required tools present"


def cgroups_pids_available():
    p = Path("/sys/fs/cgroup/pids")
    if p.is_dir():
        return True, f"cgroups v1 'pids' controller mounted at {p}"
    unified = Path("/sys/fs/cgroup/cgroup.controllers")
    if unified.is_file() and "pids" in unified.read_text():
        return True, "cgroups v2 unified hierarchy with 'pids' controller available"
    return False, "no cgroups 'pids' controller found (v1 or v2) -- fork containment cannot use the real mechanism"


# ---------------------------------------------------------------------
# Shared sandbox-building helpers (mirrors athenaeum_body/sandbox.py)
# ---------------------------------------------------------------------

def _build_root(root: Path, scratch: Path):
    for d in ("usr", "lib", "lib64", "dev", "scratch"):
        (root / d).mkdir(parents=True, exist_ok=True)
    subprocess.run(["mount", "--bind", "-o", "ro", "/usr", str(root / "usr")], check=True, capture_output=True)
    subprocess.run(["mount", "--bind", "-o", "ro", "/lib", str(root / "lib")], check=True, capture_output=True)
    if Path("/lib64").is_dir():
        subprocess.run(["mount", "--bind", "-o", "ro", "/lib64", str(root / "lib64")], check=True, capture_output=True)
    subprocess.run(["mount", "--bind", str(scratch), str(root / "scratch")], check=True, capture_output=True)
    (root / "dev" / "null").touch()
    (root / "dev" / "urandom").touch()
    subprocess.run(["mount", "--bind", "/dev/null", str(root / "dev" / "null")], check=True, capture_output=True)
    subprocess.run(["mount", "--bind", "/dev/urandom", str(root / "dev" / "urandom")], check=True, capture_output=True)


def _teardown_root(root: Path):
    for sub in ("dev/null", "dev/urandom", "scratch", "usr", "lib", "lib64"):
        subprocess.run(["umount", str(root / sub)], stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    shutil.rmtree(root, ignore_errors=True)


def run_in_sandbox(code: str, wall_clock_timeout=10, mem_mb=256, cpu_s=5,
                    cgroup: Path = None):
    scratch = Path(tempfile.mkdtemp(prefix="preflight-scratch-"))
    root = Path(tempfile.mkdtemp(prefix="preflight-root-"))
    try:
        (scratch / "code.py").write_text(code)
        _build_root(root, scratch)
        bootstrap = f"""
import os, resource
os.environ.clear()
resource.setrlimit(resource.RLIMIT_AS, ({mem_mb * 1024 * 1024}, {mem_mb * 1024 * 1024}))
resource.setrlimit(resource.RLIMIT_CPU, ({cpu_s}, {cpu_s}))
os.chdir("/scratch")
exec(compile(open("/scratch/code.py").read(), "/scratch/code.py", "exec"))
"""
        cmd = [
            "timeout", "-s", "KILL", str(wall_clock_timeout),
            "unshare", "--user", "--map-root-user", "--net", "--pid", "--mount",
            "--uts", "--ipc", "--fork", "--mount-proc", "--",
            "chroot", str(root), "/usr/bin/python3", "-c", bootstrap,
        ]

        def _join_cgroup():
            if cgroup is not None:
                with open(cgroup / "cgroup.procs", "w") as f:
                    f.write(str(os.getpid()))

        proc = subprocess.Popen(cmd, env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin"},
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                 preexec_fn=_join_cgroup if cgroup is not None else None)
        stdout, stderr = proc.communicate()
        return proc.returncode, stdout, stderr
    finally:
        _teardown_root(root)


# ---------------------------------------------------------------------
# Scenario 1: network egress
# ---------------------------------------------------------------------

def scenario_network():
    code = """
import socket
try:
    socket.gethostbyname("example.com")
    print("FAIL:dns")
except Exception:
    print("PASS:dns")
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2)
    s.connect(("8.8.8.8", 53))
    print("FAIL:socket")
except Exception:
    print("PASS:socket")
"""
    rc, out, err = run_in_sandbox(code)
    ok = "PASS:dns" in out and "PASS:socket" in out
    return ok, f"rc={rc} stdout={out.strip()!r} stderr={err.strip()[:200]!r}"


# ---------------------------------------------------------------------
# Scenario 2/3: filesystem containment
# ---------------------------------------------------------------------

def scenario_filesystem():
    code = """
for path in ["/etc/passwd", "/root/.bashrc", "../../etc/shadow"]:
    try:
        open(path).read()
        print(f"FAIL:read:{path}")
    except Exception:
        print(f"PASS:read:{path}")
try:
    open("/etc/should-not-write", "w").write("x")
    print("FAIL:write")
except Exception:
    print("PASS:write")
"""
    rc, out, err = run_in_sandbox(code)
    ok = out.count("PASS:read:") == 3 and "PASS:write" in out
    return ok, f"rc={rc} stdout={out.strip()!r}"


# ---------------------------------------------------------------------
# Scenario 4: fork containment via cgroups pids controller
# ---------------------------------------------------------------------

def scenario_fork_containment():
    cg_root = Path("/sys/fs/cgroup/pids")
    if not cg_root.is_dir():
        return False, "no cgroups v1 'pids' controller -- cannot test the real mechanism (see cgroups_pids_available above)"
    cg = cg_root / f"preflight-{uuid.uuid4().hex[:10]}"
    cg.mkdir()
    (cg / "pids.max").write_text("5")
    code = """
import os
count = 0
try:
    for _ in range(50):
        pid = os.fork()
        if pid == 0:
            os._exit(0)
        count += 1
except OSError as e:
    print(f"PASS:blocked_after_{count}")
else:
    print("FAIL:all_forks_succeeded")
"""
    try:
        rc, out, err = run_in_sandbox(code, cgroup=cg)
    finally:
        deadline = time.time() + 2
        while time.time() < deadline:
            if not (cg / "cgroup.procs").read_text().split():
                break
            time.sleep(0.05)
        try:
            cg.rmdir()
        except OSError:
            pass
    ok = "PASS:blocked_after_" in out
    return ok, f"rc={rc} stdout={out.strip()!r}"


# ---------------------------------------------------------------------
# Scenario 5: CPU time -- THE key question for this environment
# ---------------------------------------------------------------------

def minimal_rlimit_cpu_repro():
    """The isolated reproduction, deliberately with NO chroot, NO other
    namespaces -- just unshare --fork + RLIMIT_CPU + a busy loop. This is
    exactly what determined the finding in the reference environment.
    Answers: does unshare --fork crash on SIGXCPU delivery HERE."""
    proc = subprocess.run(
        ["unshare", "--fork", "--", "python3", "-c",
         "import resource\nresource.setrlimit(resource.RLIMIT_CPU, (2, 2))\n"
         "x = 0\nwhile True:\n    x += 1\n"],
        capture_output=True, text=True, timeout=8,
    )
    crashed = "sigprocmask" in proc.stderr or "unshare:" in proc.stderr
    if crashed:
        return False, f"unshare --fork crashed on SIGXCPU delivery: {proc.stderr.strip()!r}"
    return True, f"unshare --fork survived RLIMIT_CPU/SIGXCPU cleanly (rc={proc.returncode}) -- RLIMIT_CPU is usable as the PRIMARY CPU-time mechanism on this kernel"


def scenario_wall_clock_fallback():
    """Independent of whether RLIMIT_CPU works, the external kill must
    work regardless -- it's the fallback either way."""
    start = time.time()
    code = "x = 0\nwhile True:\n    x += 1\n"
    rc, out, err = run_in_sandbox(code, wall_clock_timeout=3)
    elapsed = time.time() - start
    ok = rc is not None and rc < 0 and elapsed < 6
    return ok, f"rc={rc} elapsed={elapsed:.1f}s (expect ~3s, negative rc = killed by signal)"


# ---------------------------------------------------------------------
# Scenario 6: memory limit
# ---------------------------------------------------------------------

def scenario_memory():
    code = """
try:
    x = bytearray(500*1024*1024)
    print("FAIL:mem")
except MemoryError:
    print("PASS:mem")
"""
    rc, out, err = run_in_sandbox(code, mem_mb=64)
    ok = "PASS:mem" in out
    return ok, f"rc={rc} stdout={out.strip()!r}"


# ---------------------------------------------------------------------
# Scenario 7: scratch directory freshness
# ---------------------------------------------------------------------

def scenario_scratch_freshness():
    rc1, _, _ = run_in_sandbox("open('/scratch/leftover.txt', 'w').write('x')\n")
    rc2, out2, _ = run_in_sandbox("import os\nprint('files:', os.listdir('/scratch'))\n")
    ok = "files: ['code.py']" in out2
    return ok, f"second invocation sees: {out2.strip()!r}"


# ---------------------------------------------------------------------
# Scenario 8: environment scrubbing
# ---------------------------------------------------------------------

def scenario_env_scrub():
    os.environ["PREFLIGHT_SECRET"] = "should-not-be-visible-inside"
    rc, out, err = run_in_sandbox("import os\nprint('env:', dict(os.environ))\n")
    ok = "env: {}" in out
    return ok, f"rc={rc} stdout={out.strip()!r}"


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main():
    print("=" * 70)
    print("Athenaeum sandbox preflight check")
    print("=" * 70)
    print()

    if not check("Prerequisites", prereqs):
        print("Cannot continue -- fix prerequisites and re-run.")
        sys.exit(1)

    check("cgroups 'pids' controller availability", cgroups_pids_available)
    check("Scenario 1: network egress blocked", scenario_network)
    check("Scenario 2/3: filesystem containment", scenario_filesystem)
    check("Scenario 4: fork containment via cgroups", scenario_fork_containment)
    cpu_ok = check("Minimal repro: RLIMIT_CPU under unshare --fork", minimal_rlimit_cpu_repro)
    check("Scenario 5b: external wall-clock kill (fallback, should always pass)", scenario_wall_clock_fallback)
    check("Scenario 6: memory limit enforced", scenario_memory)
    check("Scenario 7: scratch directory freshness", scenario_scratch_freshness)
    check("Scenario 8: environment scrubbed", scenario_env_scrub)

    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    failed = [name for name, ok, _ in RESULTS if not ok]
    for name, ok, detail in RESULTS:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    print()

    if cpu_ok:
        print(">>> RLIMIT_CPU works correctly on this kernel/environment.")
        print(">>> sandbox.py's cpu_time_limit_seconds rlimit can be trusted as the")
        print(">>> PRIMARY CPU-time enforcement here -- this is a real capability")
        print(">>> upgrade over the reference environment, where it was found to")
        print(">>> crash unshare --fork. Update security-review-sandbox.md's")
        print(">>> scorecard for this environment accordingly; the wall-clock kill")
        print(">>> can remain as a defensive backstop regardless.")
    else:
        print(">>> RLIMIT_CPU crashes unshare --fork on this kernel/environment too")
        print(">>> -- matches the reference environment's finding. The external")
        print(">>> wall-clock kill (already the default in sandbox.py) remains the")
        print(">>> correct primary CPU-time mechanism here. No code change needed.")
    print()

    other_failures = [n for n in failed if "RLIMIT_CPU" not in n]
    if other_failures:
        print(">>> Additional scenarios need attention before trusting this")
        print(">>> environment for execution_sandbox.enabled = true:")
        for n in other_failures:
            print(f"      - {n}")
    else:
        print(">>> Every other scenario passed. Combined with the CPU finding above,")
        print(">>> this is a complete, current scorecard for THIS environment --")
        print(">>> update security-review-sandbox.md Section 7 with these results")
        print(">>> before making any decision about enabling the sandbox here.")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
