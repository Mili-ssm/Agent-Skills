from pathlib import Path

import pytest
from commands import import_recovery as recovery


def test_rollback_after_interruption_and_retry(tmp_path: Path):
    old = tmp_path / "notes" / "old.md"
    old.parent.mkdir()
    old.write_bytes(b"old")
    new = old.parent / "new.md"
    log = tmp_path / ".curation-log"
    log.write_bytes(b"before")
    with recovery.locked(tmp_path):
        recovery.publish(tmp_path, {old: b"replacement", new: b"new", log: b"after"})
        old.write_bytes(b"replacement")
        new.write_bytes(b"new")
    with recovery.locked(tmp_path):
        recovery.rollback(tmp_path)
        assert old.read_bytes() == b"old"
        assert not new.exists()
        assert log.read_bytes() == b"before"
        recovery.rollback(tmp_path)
        recovery.clear(tmp_path)
        assert not recovery.pending(tmp_path)


def test_divergent_edit_refuses_before_any_rollback(tmp_path: Path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_bytes(b"before a")
    b.write_bytes(b"before b")
    with recovery.locked(tmp_path):
        recovery.publish(tmp_path, {a: b"after a", b: b"after b"})
        a.write_bytes(b"after a")
        b.write_bytes(b"user edit")
        with pytest.raises(recovery.DivergedError):
            recovery.rollback(tmp_path)
        assert a.read_bytes() == b"after a"
        assert recovery.pending(tmp_path)


def test_lock_and_journal_are_exclusive(tmp_path: Path):
    with recovery.locked(tmp_path):
        with pytest.raises(BlockingIOError), recovery.locked(tmp_path):
            pass
        recovery.publish(tmp_path, {tmp_path / "x": b"new"})
        with pytest.raises(FileExistsError):
            recovery.publish(tmp_path, {tmp_path / "x": b"new"})


def test_rejects_escaping_path(tmp_path: Path):
    with recovery.locked(tmp_path), pytest.raises(ValueError):
        recovery.publish(tmp_path, {tmp_path / ".." / "outside": b"x"})
