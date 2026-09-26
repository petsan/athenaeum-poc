"""The narrated demo is part of the product: it must run cleanly end to end,
and (known-bugs.md #16, a mistake made twice) print its final banner once."""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).parent.parent


def test_demo_brain_runs_and_ends_exactly_once(tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / "demo_brain.py")], cwd=tmp_path,
                            capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.count("brain demo complete") == 1
    assert result.stdout.rstrip().endswith("=== brain demo complete ===")
    assert "16/16 passed" in result.stdout
