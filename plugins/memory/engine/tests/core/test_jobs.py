"""`jobs.lock_held`: the read-only probe of a run lock."""

import os
from pathlib import Path

from core import jobs


def test_a_held_lock_reads_true_and_a_released_one_false(tmp_path: Path):
    fd = jobs.take_run_lock(tmp_path / "state")
    assert fd is not None
    assert jobs.lock_held(tmp_path / "state") is True
    os.close(fd)
    assert jobs.lock_held(tmp_path / "state") is False


def test_a_missing_folder_reads_false_and_is_not_created(tmp_path: Path):
    folder = tmp_path / "nowhere"
    assert jobs.lock_held(folder) is False
    assert not folder.exists()
