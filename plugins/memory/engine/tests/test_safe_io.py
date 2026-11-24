import datetime
import os
import stat

import pytest

import project_syntheses as ps
import records
import safe_io

TODAY = datetime.date(2026, 11, 24)


def memory(folder, claim="Keep the cache warm."):
    return records.write_memory(folder, "project", kind="lesson", claim=claim, body="Body.", today=TODAY)


def test_update_does_not_follow_a_planted_temp_symlink(tmp_path):
    m = memory(tmp_path / ".memory")
    victim = tmp_path / "victim.txt"
    victim.write_text("precious")
    (m.path.parent / f".{m.path.name}.tmp").symlink_to(victim)
    updated = records.update(m, TODAY, context="changed")
    assert victim.read_text() == "precious"
    assert updated.context == "changed"


def test_replace_file_replaces_a_symlinked_target_not_its_target(tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("precious")
    target = tmp_path / "h.md"
    target.symlink_to(victim)
    safe_io.replace_file(target, b"new")
    assert victim.read_text() == "precious"
    assert not target.is_symlink() and target.read_bytes() == b"new"
    assert stat.S_IMODE(target.stat().st_mode) != 0o777


def test_replace_file_keeps_the_mode(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("x")
    f.chmod(0o644)
    safe_io.replace_file(f, b"y")
    assert stat.S_IMODE(f.stat().st_mode) == 0o644
    safe_io.replace_file(f, b"z", mode=0o600)
    assert stat.S_IMODE(f.stat().st_mode) == 0o600
    assert [p.name for p in tmp_path.iterdir()] == ["a.md"]


def test_append_text_refuses_a_symlinked_log(tmp_path):
    m = memory(tmp_path / ".memory")
    victim = tmp_path / "victim.txt"
    victim.write_text("precious")
    (m.path.parent / records.CURATION_LOG).symlink_to(victim)
    with pytest.raises(OSError):
        records.log_before(m, "edit")
    assert victim.read_text() == "precious"


def test_project_memories_skip_symlinked_files(tmp_path):
    folder = tmp_path / ".memory"
    memory(folder)
    other = memory(tmp_path / "elsewhere", "Another claim here.")
    (folder / "planted.md").symlink_to(other.path)
    assert [m.handle for m in records.load_memories(folder, "project")] == [records.slug_of("Keep the cache warm.")]


def test_a_symlinked_project_folder_loads_nothing_and_refuses_writes(tmp_path):
    memory(tmp_path / "real")
    link = tmp_path / ".memory"
    link.symlink_to(tmp_path / "real")
    assert records.load_memories(link, "project") == []
    assert len(records.load_memories(link, "global")) == 1
    with pytest.raises(safe_io.UnsafePath):
        records.write_memory(link, "project", kind="lesson", claim="New one.", body="", today=TODAY)
    assert len(list((tmp_path / "real").glob("*.md"))) == 1


def test_synthesis_write_refuses_a_symlinked_syntheses_folder(tmp_path):
    mem = tmp_path / ".memory"
    mem.mkdir()
    target = tmp_path / "target"
    target.mkdir()
    (mem / "syntheses").symlink_to(target)
    with pytest.raises(safe_io.UnsafePath):
        ps.write_part(mem, tmp_path, "organization", "Heading", "Text.", [], TODAY)
    assert list(target.iterdir()) == []


def test_load_each_skips_symlinked_files(tmp_path):
    mem = tmp_path / ".memory"
    folder = ps.folder(mem)
    folder.mkdir(parents=True)
    (tmp_path / "outside.md").write_text("garbage")
    (folder / "organization.md").symlink_to(tmp_path / "outside.md")
    assert ps.load_each(mem) == ({}, [])
