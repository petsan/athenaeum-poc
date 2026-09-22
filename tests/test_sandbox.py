"""
Real fault-injection tests against the actual sandbox mechanism (no
mocking) -- these ARE security-review-sandbox.md's 8 required scenarios.
Needs CAP_SYS_ADMIN (root, with unshare/mount/chroot permitted) to run;
will not pass in an unprivileged CI runner without extra setup -- see
README's note on this.
"""
import pytest
from athenaeum_body import sandbox
from athenaeum_body.sandbox import run_sandboxed

def test_cgroup_pids_version_prefers_v1_when_present(tmp_path, monkeypatch):
    v1 = tmp_path / "pids"
    v1.mkdir()
    monkeypatch.setattr(sandbox, "CGROUP_V1_PIDS_ROOT", v1)
    assert sandbox._cgroup_pids_version() == "v1"

def test_cgroup_pids_version_falls_back_to_v2_when_v1_absent(tmp_path, monkeypatch):
    v1 = tmp_path / "pids"  # never created -- v1 absent, matches a cgroups-v2-only host
    v2_controllers = tmp_path / "cgroup.controllers"
    v2_controllers.write_text("cpuset cpu io memory pids rdma\n")
    monkeypatch.setattr(sandbox, "CGROUP_V1_PIDS_ROOT", v1)
    monkeypatch.setattr(sandbox, "CGROUP_V2_CONTROLLERS_FILE", v2_controllers)
    assert sandbox._cgroup_pids_version() == "v2"

def test_cgroup_pids_version_v2_without_pids_controller_listed_is_unavailable(tmp_path, monkeypatch):
    v1 = tmp_path / "pids"
    v2_controllers = tmp_path / "cgroup.controllers"
    v2_controllers.write_text("cpuset cpu io memory rdma\n")  # no 'pids' entry
    monkeypatch.setattr(sandbox, "CGROUP_V1_PIDS_ROOT", v1)
    monkeypatch.setattr(sandbox, "CGROUP_V2_CONTROLLERS_FILE", v2_controllers)
    assert sandbox._cgroup_pids_version() is None

def test_cgroup_pids_version_none_when_neither_layout_present(tmp_path, monkeypatch):
    v1 = tmp_path / "pids"
    v2_controllers = tmp_path / "cgroup.controllers"  # never created
    monkeypatch.setattr(sandbox, "CGROUP_V1_PIDS_ROOT", v1)
    monkeypatch.setattr(sandbox, "CGROUP_V2_CONTROLLERS_FILE", v2_controllers)
    assert sandbox._cgroup_pids_version() is None

def test_scenario_1_network_egress_blocked():
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
    result = run_sandboxed(code, wall_clock_timeout_seconds=10)
    assert result.status == "completed"
    assert "PASS:dns" in result.stdout
    assert "PASS:socket" in result.stdout

def test_scenario_2_and_3_filesystem_containment():
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
    result = run_sandboxed(code, wall_clock_timeout_seconds=10)
    assert result.status == "completed"
    assert result.stdout.count("PASS:read:") == 3
    assert "PASS:write" in result.stdout

def test_scenario_4_fork_containment_via_cgroups():
    code = """
import os, sys
count = 0
try:
    for _ in range(50):
        pid = os.fork()
        if pid == 0:
            os._exit(0)
        count += 1
except OSError:
    print(f"PASS:forks_blocked_after_{count}")
"""
    result = run_sandboxed(code, wall_clock_timeout_seconds=10, max_pids=5)
    assert result.status == "completed"
    assert "PASS:forks_blocked_after_" in result.stdout
    blocked_after = int(result.stdout.split("PASS:forks_blocked_after_")[1].split("\n")[0])
    assert blocked_after < 50  # confirm it was actually blocked early, not allowed to run all 50

def test_scenario_5_wall_clock_timeout_terminates_busy_loop():
    code = "x = 0\nwhile True:\n    x += 1\n"
    result = run_sandboxed(code, wall_clock_timeout_seconds=3)
    assert result.status == "timeout"
    assert result.returncode == -9  # Python convention for SIGKILL termination

def test_scenario_6_memory_limit_enforced():
    code = """
try:
    x = bytearray(500*1024*1024)
    print("FAIL:mem")
except MemoryError:
    print("PASS:mem")
"""
    result = run_sandboxed(code, memory_limit_mb=64, wall_clock_timeout_seconds=10)
    assert result.status == "completed"
    assert "PASS:mem" in result.stdout

def test_scenario_7_scratch_directory_fresh_across_invocations():
    write_code = "open('/scratch/leftover.txt', 'w').write('should not persist')\n"
    check_code = "import os\nprint('files:', os.listdir('/scratch'))\n"
    r1 = run_sandboxed(write_code, wall_clock_timeout_seconds=10)
    assert r1.status == "completed"
    r2 = run_sandboxed(check_code, wall_clock_timeout_seconds=10)
    assert r2.status == "completed"
    assert "files: ['code.py']" in r2.stdout  # only this run's own code.py, nothing from run 1

def test_scenario_8_environment_scrubbed():
    code = "import os\nprint('env:', dict(os.environ))\n"
    result = run_sandboxed(code, wall_clock_timeout_seconds=10)
    assert result.status == "completed"
    assert "env: {}" in result.stdout

def test_normal_successful_execution_returns_output():
    code = "print(2 + 2)\n"
    result = run_sandboxed(code, wall_clock_timeout_seconds=10)
    assert result.status == "completed"
    assert result.returncode == 0
    assert "4" in result.stdout

def test_failure_is_always_distinguishable_from_success():
    """Section 2.2.5's specific concern: a timeout must never look like
    a clean pass -- status must differ, not just be inferred from output."""
    ok = run_sandboxed("print('done')", wall_clock_timeout_seconds=10)
    timed_out = run_sandboxed("while True: pass", wall_clock_timeout_seconds=2)
    assert ok.status != timed_out.status
    assert ok.status == "completed" and timed_out.status == "timeout"
