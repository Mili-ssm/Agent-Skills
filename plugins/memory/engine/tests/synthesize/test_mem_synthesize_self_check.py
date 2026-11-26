"""`bin/mem-synthesize --self-check`: the offline trial with a fake `claude` must keep passing."""

import subprocess
import sys
from pathlib import Path

SYNTHESIZE = Path(__file__).resolve().parents[3] / "bin" / "mem-synthesize"


def test_self_check_passes():
    done = subprocess.run(
        [sys.executable, str(SYNTHESIZE), "--self-check"],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "self-check passed" in done.stdout
