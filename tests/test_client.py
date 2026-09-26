"""The mobile client's script (client/index.html), exercised by
tests/client/client_smoke.mjs against a fake DOM, fetch and timer: history,
async submit and polling, version/diff display, the maintenance panel, and
HTML escaping of every server- or user-supplied string. Needs only node."""
import shutil
import subprocess
from pathlib import Path
import pytest

SMOKE = Path(__file__).parent / "client" / "client_smoke.mjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_client_smoke():
    result = subprocess.run(["node", str(SMOKE)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "all checks passed" in result.stdout
