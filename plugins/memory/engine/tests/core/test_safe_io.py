import datetime
import os
import stat
from pathlib import Path

import mem
import project_syntheses as ps
import pytest
import records
from core import jobs, safe_io
from settle import verdicts as settle_verdicts

TODAY = datetime.date(2026, 11, 24)
MODE_GROUP_READABLE = 0o644
MODE_PRIVATE = 0o600
EXIT_REFUSED = 2


def memory(folder, claim="Keep the cache warm."):
    return records.write_memory(
        folder, "project", kind="lesson", claim=claim, body="Body.", today=TODAY
    )


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
    mask = os.umask(0)
    os.umask(mask)
    assert stat.S_IMODE(target.stat().st_mode) == 0o666 & ~mask


def test_replace_file_keeps_the_mode(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("x")
    f.chmod(0o644)
    safe_io.replace_file(f, b"y")
    assert stat.S_IMODE(f.stat().st_mode) == MODE_GROUP_READABLE
    safe_io.replace_file(f, b"z", mode=0o600)
    assert stat.S_IMODE(f.stat().st_mode) == MODE_PRIVATE
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
    assert [m.handle for m in records.load_memories(folder, "project")] == [
        records.slug_of("Keep the cache warm.")
    ]


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
        ps.write_part(
            mem, tmp_path, ps.NewPart("organization", "Heading", "Text.", ["target"]), TODAY
        )
    assert list(target.iterdir()) == []


def test_load_each_skips_symlinked_files(tmp_path):
    mem = tmp_path / ".memory"
    folder = ps.folder(mem)
    folder.mkdir(parents=True)
    (tmp_path / "outside.md").write_text("garbage")
    (folder / "organization.md").symlink_to(tmp_path / "outside.md")
    assert ps.load_each(mem) == ({}, [])


def test_load_each_ignores_a_symlinked_syntheses_folder(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "src.txt").write_text("x")
    ps.write_part(
        real, tmp_path, ps.NewPart("organization", "Heading", "Text.", ["src.txt"]), TODAY
    )
    assert ps.load_each(real)[0]
    mem = tmp_path / ".memory"
    mem.mkdir()
    (mem / "syntheses").symlink_to(ps.folder(real))
    assert ps.load_each(mem) == ({}, [])


def test_refuse_symlink_chain_outside_root_raises_unsafe_path(tmp_path):
    with pytest.raises(safe_io.UnsafePath):
        safe_io.refuse_symlink_chain(tmp_path / "a", tmp_path / "b" / "c")


def test_replace_file_closes_the_fd_when_fdopen_fails(tmp_path, monkeypatch):
    closed = []
    real_close = os.close
    monkeypatch.setattr(os, "close", lambda fd: (closed.append(fd), real_close(fd))[1])
    monkeypatch.setattr(os, "fdopen", lambda *a, **k: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(OSError):
        safe_io.replace_file(tmp_path / "a.md", b"x")
    assert closed and list(tmp_path.iterdir()) == []


def test_confirm_part_refuses_a_symlinked_syntheses_folder(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "src.txt").write_text("x")
    ps.write_part(
        real, tmp_path, ps.NewPart("organization", "Heading", "Text.", ["src.txt"]), TODAY
    )
    handle = ps.load_each(real)[0]["organization"][0].handle
    before = (ps.folder(real) / "organization.md").read_text()
    mem = tmp_path / ".memory"
    mem.mkdir()
    (mem / "syntheses").symlink_to(ps.folder(real))
    with pytest.raises(safe_io.UnsafePath):
        ps.confirm_part(mem, tmp_path, "organization", handle, TODAY)
    assert (ps.folder(real) / "organization.md").read_text() == before


def test_note_restore_does_not_follow_a_planted_temp_symlink(hub_root, tmp_path, capsys):
    rel = "knowledge/computing/attention-replaces-recurrence.md"
    handle = "attention-replaces-recurrence"
    note = hub_root / rel
    assert (
        mem.main([
            "--root",
            str(hub_root),
            "note",
            "edit",
            handle,
            "--claim",
            "Self-attention can replace recurrence for sequence modelling",
        ])
        == 0
    )
    victim = tmp_path / "victim.txt"
    victim.write_text("precious")
    (note.parent / f".{note.name}.tmp").symlink_to(victim)
    capsys.readouterr()
    assert mem.main(["--root", str(hub_root), "restore", handle]) == 0
    assert victim.read_text() == "precious"


def test_state_files_stay_private(tmp_path):
    path = tmp_path / "state.json"
    jobs.write_json(path, {"a": 1})
    assert stat.S_IMODE(path.stat().st_mode) == MODE_PRIVATE
    jobs.write_json(path, {"a": 2})
    assert stat.S_IMODE(path.stat().st_mode) == MODE_PRIVATE
    assert jobs.read_json(path) == {"a": 2}


def test_write_json_does_not_follow_a_planted_old_temp_name(tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("precious")
    path = tmp_path / "state.json"
    (tmp_path / "state.json.tmp").symlink_to(victim)
    jobs.write_json(path, {"a": 1})
    assert victim.read_text() == "precious"
    assert jobs.read_json(path) == {"a": 1}


def test_note_edit_log_append_refuses_a_symlinked_curation_log(hub_root, tmp_path, capsys):
    victim = tmp_path / "victim.txt"
    victim.write_text("precious")
    (hub_root / records.CURATION_LOG).symlink_to(victim)
    mem.main([
        "--root",
        str(hub_root),
        "note",
        "edit",
        "attention-replaces-recurrence",
        "--claim",
        "Self-attention can replace recurrence for sequence modelling",
    ])
    capsys.readouterr()
    assert victim.read_text() == "precious"


def test_index_update_replaces_a_symlinked_readme_not_its_target(hub_root, tmp_path):
    readme = hub_root / "knowledge/computing/README.md"
    victim = tmp_path / "victim.md"
    victim.write_text(
        readme.read_text().replace(
            "| medium | intermediate | llm |", "| low | intermediate | llm |"
        )
    )
    before = victim.read_text()
    readme.unlink()
    readme.symlink_to(victim)
    mem.apply_index(hub_root)
    assert victim.read_text() == before
    assert not readme.is_symlink()


def test_new_note_does_not_write_through_a_dangling_link(hub_root, tmp_path, capsys):
    victim = tmp_path / "victim.md"
    folder = hub_root / "knowledge/biology"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "body-note.md").symlink_to(victim)
    mem.main([
        "--root",
        str(hub_root),
        "new",
        "knowledge",
        "--slug",
        "body-note",
        "--claim",
        "A claim about bodies.",
        "--topics",
        "biology",
        "--confidence",
        "low",
        "--level",
        "beginner",
        "--origin",
        "research",
    ])
    capsys.readouterr()
    assert not victim.exists()


def test_import_refuses_a_symlinked_destination_folder(tmp_path, capsys):
    src, dest, outside = tmp_path / "src", tmp_path / "store", tmp_path / "outside"
    assert mem.main(["init", str(dest)]) == 0
    (src / "literature/x").mkdir(parents=True)
    (src / "literature/x/a.md").write_text("note\n")
    outside.mkdir()
    (dest / "literature/x").symlink_to(outside, target_is_directory=True)
    capsys.readouterr()
    mem.main(["--root", str(dest), "import", str(src)])
    out = capsys.readouterr().out
    assert list(outside.iterdir()) == []
    assert "literature/x/a.md" in out


def test_settle_log_append_refuses_a_symlinked_log(tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("precious")
    (tmp_path / settle_verdicts.LOG_NAME).symlink_to(victim)
    with pytest.raises(OSError):
        settle_verdicts._append_log(tmp_path, {"undo": 1})
    assert victim.read_text() == "precious"


def test_append_text_closes_the_fd_when_fdopen_fails(tmp_path, monkeypatch):
    opened = []
    real_open = os.open

    def spy(*a, **k):
        fd = real_open(*a, **k)
        opened.append(fd)
        return fd

    def boom(*a, **k):
        raise RuntimeError("fdopen failed")

    monkeypatch.setattr(os, "open", spy)
    monkeypatch.setattr(os, "fdopen", boom)
    with pytest.raises(RuntimeError):
        safe_io.append_text(tmp_path / "log", "x")
    with pytest.raises(OSError):
        os.fstat(opened[0])


def test_no_predictable_temp_names_remain():
    root = Path(__file__).resolve().parents[3]
    files = [
        *(
            p
            for p in root.joinpath("engine").rglob("*.py")
            if "tests" not in p.relative_to(root).parts
        ),
        *(p for p in root.joinpath("bin").iterdir() if p.is_file()),
    ]
    assert files
    bad = [
        f"{f.name}: {needle}"
        for f in files
        for needle in ('with_name(f".{', '+ ".tmp"')
        if needle in f.read_text(encoding="utf-8")
    ]
    assert bad == []


def test_unsafe_path_from_a_command_is_a_refusal_not_a_traceback(tmp_path, monkeypatch, capsys):
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / ".memory").mkdir()
    target = tmp_path / "target"
    target.mkdir()
    (root / ".memory" / "syntheses").symlink_to(target)
    monkeypatch.setenv("MEM_PROJECT", str(root))
    monkeypatch.chdir(root)
    body = tmp_path / "body.txt"
    body.write_text("Text.")
    code = mem.main([
        "project-synthesis",
        "add",
        "organization",
        "Heading",
        "--paths",
        "src/",
        "--body-file",
        str(body),
    ])
    err = capsys.readouterr().err
    assert (
        code == EXIT_REFUSED
        and err.startswith("mem: refused: ")
        and "symlink" in err
        and "Traceback" not in err
    )
    assert list(target.iterdir()) == []
