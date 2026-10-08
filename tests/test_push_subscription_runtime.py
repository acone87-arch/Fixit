"""Keep the browser subscription lifecycle regression in the standard pytest gate."""

from pathlib import Path
import subprocess


def test_push_subscription_lifecycle_runtime():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["node", "tests/push_subscription_runtime_test.js"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
