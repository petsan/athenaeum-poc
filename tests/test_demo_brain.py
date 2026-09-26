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
    # batches 4-5 (steps 12-15)
    assert "citations idle evolution now reads from the graph: {'fixture:textbook': ['fixture:survey']}" in result.stdout
    assert "paid or metered access -- hard invariant, never fetched" in result.stdout
    assert "sampled ONE claim, yet reopened: ['c1', 'c2', 'c3']" in result.stdout
    assert result.stdout.count("unit_error: attempt") == 2 and "unit_failed: attempt 3" in result.stdout
    assert "c5 is now: suspended" in result.stdout
