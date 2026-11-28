import json
from pathlib import Path

import pytest
from core import safe_io
from core.file_journal import SPLIT_VERSION, DivergedError, FileJournal


def test_create_delete_empty_and_retry(tmp_path: Path, monkeypatch):
    journal = FileJournal(tmp_path, ".split-recovery")
    new, deleted, empty = (tmp_path / name for name in ("new", "deleted", "empty"))
    deleted.write_bytes(b"old")
    empty.write_bytes(b"")
    with journal.locked():
        journal.publish({new: (None, b""), deleted: (b"old", None), empty: (b"", b"changed")})
        assert (
            json.loads((tmp_path / ".split-recovery/journal.json").read_text())["version"]
            == SPLIT_VERSION
        )
        new.write_bytes(b"")
        deleted.unlink()
        empty.write_bytes(b"changed")
        replace = safe_io.replace_file
        calls = 0

        def interrupt(path, data):
            nonlocal calls
            calls += 1
            if calls == 2:  # ruff: ignore[magic-value-comparison]
                raise OSError("interrupted")
            replace(path, data)

        monkeypatch.setattr(safe_io, "replace_file", interrupt)
        with pytest.raises(OSError, match="interrupted"):
            journal.rollback()
        monkeypatch.setattr(safe_io, "replace_file", replace)
        journal.rollback()
        journal.rollback()
        assert not new.exists()
        assert deleted.read_bytes() == b"old"
        assert empty.read_bytes() == b""
        journal.clear()
        assert not journal.pending()


def test_divergence_preflight_and_expected_original(tmp_path: Path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.write_bytes(b"old")
    b.write_bytes(b"")
    journal = FileJournal(tmp_path, ".split-recovery")
    with journal.locked():
        with pytest.raises(ValueError):
            journal.publish({a: (b"wrong", b"new")})
        assert not journal.pending()
        journal.publish({a: (b"old", b"new"), b: (b"", None)})
        a.write_bytes(b"new")
        b.write_bytes(b"edited")
        with pytest.raises(DivergedError):
            journal.rollback()
        assert a.read_bytes() == b"new"


def test_rejects_unsafe_paths(tmp_path: Path):
    journal = FileJournal(tmp_path, ".split-recovery")
    with journal.locked():
        for path in (tmp_path, tmp_path / ".." / "escape", tmp_path / ".split-recovery" / "x"):
            with pytest.raises(ValueError):
                journal.publish({path: (None, b"x")})
        (tmp_path / "link").symlink_to(tmp_path / "elsewhere")
        with pytest.raises(OSError):
            journal.publish({tmp_path / "link" / "x": (None, b"x")})


def test_reads_existing_version_one_journal(tmp_path: Path):
    target = tmp_path / "note"
    target.write_bytes(b"new")
    folder = tmp_path / ".import-recovery"
    folder.mkdir()
    (folder / "journal.json").write_text(
        '{"version": 1, "entries": [{"path": "note", "original": "b2xk", '
        '"after": "11507a0e2f5e69d5dfa40a62a1bd7b6ee57e6bcd85c67c9b8431b36fff21c437"}]}'
    )
    journal = FileJournal(tmp_path, ".import-recovery", version=1)
    with journal.locked():
        journal.rollback()
    assert target.read_bytes() == b"old"
