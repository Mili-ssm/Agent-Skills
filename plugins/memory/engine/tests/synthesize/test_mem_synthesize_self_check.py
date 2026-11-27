"""`bin/mem-synthesize --self-check`: the offline trial with a fake `claude` must keep passing."""

import subprocess
import sys
from pathlib import Path

RUN = Path(__file__).resolve().parents[2] / "run.py"


def test_self_check_passes():
    done = subprocess.run(
        [sys.executable, str(RUN), "--bin", "mem-synthesize", "--self-check"],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "self-check passed" in done.stdout
