import json
import os
from dataclasses import replace

import pytest
from commands import split_transaction as tx
from commands.split_plan import SplitPlan
from core import jobs, safe_io
from core.file_journal import DivergedError


def plan(root, conflicts=()):
    a, b = root / "syntheses/a.md", root / "knowledge/t/b.md"
    a.parent.mkdir(parents=True, exist_ok=True)
    b.parent.mkdir(parents=True, exist_ok=True)
    a.write_bytes(b"old")
    return SplitPlan("", "", "", "", (), conflicts, {a: (b"old", b"new"), b: (None, b"note")})


def test_apply_undo_and_status(tmp_path):
    p = plan(tmp_path)
    group = tx.apply_split(tmp_path, lambda: p)
    assert tx.split_status(tmp_path) == (False, [group])
    tx.undo_split(tmp_path, group)
    assert next(iter(p.changes)).read_bytes() == b"old"
    assert not (tmp_path / "knowledge/t/b.md").exists()
    assert tx.split_status(tmp_path) == (False, [])
    with pytest.raises(ValueError):
        tx.undo_split(tmp_path, group)


def test_conflict_and_later_edit_refused(tmp_path):
    p = plan(tmp_path, ("other",))
    with pytest.raises(ValueError):
        tx.apply_split(tmp_path, lambda: p)
    assert (tmp_path / "syntheses/a.md").read_bytes() == b"old"
    p = replace(p, conflicts=())
    group = tx.apply_split(tmp_path, lambda: p)
    (tmp_path / "knowledge/t/b.md").write_bytes(b"edited")
    with pytest.raises((ValueError, DivergedError)):
        tx.undo_split(tmp_path, group)
    assert (tmp_path / "syntheses/a.md").read_bytes() == b"new"


def test_interruption_and_recovery(tmp_path, monkeypatch):
    p = plan(tmp_path)
    replace = safe_io.replace_file
    count = 0

    def fail(path, data, *args, **kwargs):
        nonlocal count
        count += 1
        if count == 2:  # ruff: ignore[magic-value-comparison]
            raise KeyboardInterrupt()
        return replace(path, data, *args, **kwargs)

    monkeypatch.setattr(safe_io, "replace_file", fail)
    with pytest.raises(KeyboardInterrupt):
        tx.apply_split(tmp_path, lambda: p)
    monkeypatch.setattr(safe_io, "replace_file", replace)
    assert tx.split_status(tmp_path)[0]
    assert tx.recover_split(tmp_path)
    assert not tx.recover_split(tmp_path)
    assert (tmp_path / "syntheses/a.md").read_bytes() == b"old"
    assert tx.split_status(tmp_path) == (False, [])


def test_receipt_rejects_unrelated_path(tmp_path):
    p = plan(tmp_path)
    group = tx.apply_split(tmp_path, lambda: p)
    receipt = tmp_path / ".split-history" / f"{group}.json"
    data = json.loads(receipt.read_text())
    data["entries"][0]["path"] = "topics.yaml"
    receipt.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        tx.undo_split(tmp_path, group)
    with pytest.raises(ValueError):
        tx.undo_split(tmp_path, "../escape")


def test_partial_rollback_is_retryable(tmp_path, monkeypatch):
    p = plan(tmp_path)
    replace = safe_io.replace_file
    count = 0

    def interrupt(path, data, *args, **kwargs):
        nonlocal count
        count += 1
        if count == 3:  # ruff: ignore[magic-value-comparison]
            raise KeyboardInterrupt()
        return replace(path, data, *args, **kwargs)

    monkeypatch.setattr(safe_io, "replace_file", interrupt)
    with pytest.raises(KeyboardInterrupt):
        tx.apply_split(tmp_path, lambda: p)
    monkeypatch.setattr(safe_io, "replace_file", replace)

    def fail(path, data, *args, **kwargs):
        raise OSError("rollback failed")

    monkeypatch.setattr(safe_io, "replace_file", fail)
    with pytest.raises(OSError, match="rollback failed"):
        tx.recover_split(tmp_path)
    assert tx.split_status(tmp_path)[0]
    monkeypatch.setattr(safe_io, "replace_file", replace)
    assert tx.recover_split(tmp_path)
    assert not tx.recover_split(tmp_path)


def test_pending_blocks_writes_and_divergence(tmp_path, monkeypatch):
    p = plan(tmp_path)
    replace = safe_io.replace_file

    def interrupt(path, data, *args, **kwargs):
        if path == tmp_path / "syntheses/a.md":
            raise KeyboardInterrupt()
        return replace(path, data, *args, **kwargs)

    monkeypatch.setattr(safe_io, "replace_file", interrupt)
    with pytest.raises(KeyboardInterrupt):
        tx.apply_split(tmp_path, lambda: p)
    monkeypatch.setattr(safe_io, "replace_file", replace)
    with pytest.raises(FileExistsError):
        tx.apply_split(tmp_path, lambda: p)
    (tmp_path / "syntheses/a.md").write_bytes(b"edited")
    with pytest.raises(DivergedError):
        tx.recover_split(tmp_path)
    assert tx.split_status(tmp_path)[0]


def test_status_is_read_only_on_fresh_store(tmp_path):
    assert tx.split_status(tmp_path) == (False, [])
    assert list(tmp_path.iterdir()) == []


def test_io_failure_rolls_back_and_reports_failed_rollback(tmp_path, monkeypatch):
    p = plan(tmp_path)
    replace = safe_io.replace_file

    def fail_second(path, data, *args, **kwargs):
        if path == tmp_path / "knowledge/t/b.md":
            raise OSError("write failed")
        return replace(path, data, *args, **kwargs)

    monkeypatch.setattr(safe_io, "replace_file", fail_second)
    with pytest.raises(OSError, match="write failed"):
        tx.apply_split(tmp_path, lambda: p)
    assert (tmp_path / "syntheses/a.md").read_bytes() == b"old"
    assert not tx.split_status(tmp_path)[0]

    def fail_write_and_rollback(path, data, *args, **kwargs):
        if path == tmp_path / "knowledge/t/b.md" or data == b"old":
            raise OSError("failed")
        return replace(path, data, *args, **kwargs)

    monkeypatch.setattr(safe_io, "replace_file", fail_write_and_rollback)
    with pytest.raises(OSError, match="recovery pending"):
        tx.apply_split(tmp_path, lambda: p)
    monkeypatch.setattr(safe_io, "replace_file", replace)
    assert tx.recover_split(tmp_path)


def test_status_rejects_active_writer_without_creating_files(tmp_path):
    folder = tmp_path / ".split-recovery"
    fd = jobs.take_run_lock(folder)
    assert fd is not None
    before = set(tmp_path.rglob("*"))
    try:
        with pytest.raises(BlockingIOError, match="running"):
            tx.split_status(tmp_path)
        assert set(tmp_path.rglob("*")) == before
    finally:
        os.close(fd)
    assert tx.split_status(tmp_path) == (False, [])
