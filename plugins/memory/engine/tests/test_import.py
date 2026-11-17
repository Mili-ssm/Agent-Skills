import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest
from conftest import FIXTURE, usage_log_path

import mem


@pytest.fixture
def source(tmp_path) -> Path:
    src = tmp_path / "old-notes"
    shutil.copytree(FIXTURE, src)
    (src / ".hidden").mkdir()
    (src / ".hidden" / "x.md").write_text("hidden\n", encoding="utf-8")
    (src / "research" / "2026-11-llm-eval-methods" / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (src / "research" / "2026-11-llm-eval-methods" / "__pycache__").mkdir()
    (src / "research" / "2026-11-llm-eval-methods" / "__pycache__" / "m.pyc").write_bytes(b"\x00")
    (src / ".sources" / "2017-vaswani-attention").mkdir(parents=True)
    (src / ".sources" / "2017-vaswani-attention" / "paper.txt").write_text("text\n", encoding="utf-8")
    return src


@pytest.fixture
def dest(tmp_path) -> Path:
    store = tmp_path / "store"
    assert mem.main(["init", str(store)]) == 0
    return store


def snapshot(folder: Path) -> dict:
    out = {}
    for p in sorted(folder.rglob("*")):
        st = p.stat()
        out[p.relative_to(folder).as_posix()] = (
            hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None, st.st_mtime_ns)
    return out


def run(dest, src, capsys, *extra):
    capsys.readouterr()
    code = mem.main(["--root", str(dest), "import", str(src), *extra])
    cap = capsys.readouterr()
    return code, cap.out, cap.err


def test_a_first_import_copies_the_notes_and_makes_them_searchable(source, dest, capsys):
    code, out, _ = run(dest, source, capsys)
    print(out)
    lines = out.splitlines()
    assert code == 0
    assert lines[0] == f"source: {source.resolve()}"
    assert lines[1] == f"destination: {dest.resolve()}"
    assert lines[2] == "notes: 1 literature, 1 knowledge, 1 research"
    assert lines[3] == "files: 5 copied, 0 identical, 0 conflicts"
    assert lines[4] == "topics: 6 added, 0 kept as they were"
    assert lines[5] == "check: 0 problems"
    assert lines[6] == "flagged: 0 files"
    assert len(lines) == 7
    assert (dest / "knowledge/computing/attention-replaces-recurrence.md").is_file()
    assert (dest / "research/2026-11-llm-eval-methods/data.csv").is_file()
    assert "attention-replaces-recurrence" in (dest / "knowledge/computing/README.md").read_text(encoding="utf-8")
    assert not (dest / ".hidden").exists()
    assert not (dest / "research/2026-11-llm-eval-methods/__pycache__").exists()
    assert not (dest / ".sources").exists()
    assert mem.main(["--root", str(dest), "search", "self-attention recurrence"]) == 0
    assert "attention-replaces-recurrence" in capsys.readouterr().out
    assert mem.main(["--root", str(dest), "check"]) == 0


def test_the_source_is_never_changed(source, dest, capsys):
    before = snapshot(source)
    for extra in ((), ("--overwrite",), ("--dry-run",), ("--with-sources",)):
        assert run(dest, source, capsys, *extra)[0] == 0
    assert snapshot(source) == before


def test_a_second_import_copies_nothing(source, dest, capsys):
    run(dest, source, capsys)
    code, out, _ = run(dest, source, capsys)
    assert code == 0
    assert "files: 0 copied, 5 identical, 0 conflicts" in out
    assert "topics: 0 added, 0 kept as they were" in out


def test_a_changed_destination_file_is_a_conflict_until_overwrite(source, dest, capsys):
    run(dest, source, capsys)
    target = dest / "knowledge/computing/attention-replaces-recurrence.md"
    mine = target.read_text(encoding="utf-8") + "\nMy edit.\n"
    target.write_text(mine, encoding="utf-8")
    code, out, _ = run(dest, source, capsys)
    assert code == 0
    assert "files: 0 copied, 4 identical, 1 conflicts" in out
    assert out.split("conflicts:\n")[1].splitlines()[0].strip() == "knowledge/computing/attention-replaces-recurrence.md"
    assert target.read_text(encoding="utf-8") == mine
    code, out, _ = run(dest, source, capsys, "--overwrite")
    assert code == 0
    assert "files: 1 copied, 4 identical, 0 conflicts" in out
    assert "My edit." not in target.read_text(encoding="utf-8")
    log = [json.loads(line) for line in (dest / ".curation-log").read_text(encoding="utf-8").splitlines()]
    assert len(log) == 1 and "My edit." in log[0]["before"] and log[0]["action"] == "import"
    assert usage_log_path().read_text(encoding="ascii").splitlines()[-1].count('"copied": 1') == 1


def test_dry_run_changes_nothing_and_reports_the_same(source, dest, capsys):
    (source / "knowledge/computing/broken.md").write_text("no frontmatter, links [x](../../docs/a.md)\n", encoding="utf-8")
    before = snapshot(dest)
    code, dry, _ = run(dest, source, capsys, "--dry-run")
    assert code == 0
    assert snapshot(dest) == before
    code, real, _ = run(dest, source, capsys)
    assert code == 0 and real == dry
    assert "check: 0 problems" not in real


def test_topics_are_united_and_a_differing_id_is_kept_and_reported(source, dest, capsys):
    (dest / "topics.yaml").write_text("# mine\nnotes: {description: General notes}\nml: {description: Mine}\n", encoding="utf-8")
    code, out, _ = run(dest, source, capsys)
    assert code == 0
    assert "topics: 5 added, 1 kept as they were" in out
    assert out.split("topics kept:\n")[1].splitlines()[0].strip() == "ml"
    text = (dest / "topics.yaml").read_text(encoding="utf-8")
    assert text.startswith("# mine\nnotes: {description: General notes}\nml: {description: Mine}\n")
    topics = mem.load_topics(dest)
    assert topics["ml"] == {"description": "Mine"} and topics["llm"] == {"parent": "deep-learning", "description": "Large language models"}
    assert "notes" in topics


def test_with_sources_copies_the_sources_folder(source, dest, capsys):
    code, out, _ = run(dest, source, capsys, "--with-sources")
    assert code == 0
    assert (dest / ".sources/2017-vaswani-attention/paper.txt").read_text(encoding="utf-8") == "text\n"
    assert "files: 6 copied" in out


def test_generated_listings_are_not_copied(source, dest, capsys):
    (source / "literature" / "README.md").write_text("SOURCE-LISTING\n", encoding="utf-8")
    (source / "knowledge" / "computing" / "README.md").write_text("SOURCE-LISTING\n", encoding="utf-8")
    code, out, _ = run(dest, source, capsys)
    assert code == 0 and "files: 5 copied" in out
    assert not (dest / "literature" / "README.md").exists()  # copied listings would be here; none is made without a marker
    assert "SOURCE-LISTING" not in (dest / "knowledge/computing/README.md").read_text(encoding="utf-8")


def test_a_store_without_the_marker_is_refused(source, dest, capsys):
    (dest / "mem-store.yaml").unlink()
    code, out, err = run(dest, source, capsys)
    assert code == 2 and out == "" and "read-only" in err
    assert not (dest / "knowledge/computing").exists()


def test_source_equal_inside_or_containing_the_destination_is_refused(source, dest, tmp_path, capsys):
    inner = dest / "old"
    inner.mkdir()
    outer = tmp_path
    for src in (dest, inner, outer):
        code, out, err = run(dest, src, capsys)
        assert code == 2 and out == "" and err.startswith("mem:")
    code, _, err = run(dest, tmp_path / "missing", capsys)
    assert code == 2


def test_a_link_outside_the_three_folders_is_a_check_problem_not_a_failure(source, dest, capsys):
    note = source / "knowledge/computing/attention-replaces-recurrence.md"
    note.write_text(note.read_text(encoding="utf-8") + "\nSee [the doc](../../docs/spec.md).\n", encoding="utf-8")
    code, out, _ = run(dest, source, capsys)
    assert code == 0
    assert "check: 1 problems" in out
    assert "check problems (first 20):\n" in out
    assert "docs/spec.md" in out.split("check problems (first 20):\n")[1]


def test_a_file_with_a_secret_is_flagged_and_still_copied(source, dest, capsys):
    note = source / "knowledge/computing/attention-replaces-recurrence.md"
    note.write_text(note.read_text(encoding="utf-8") + "\nkey: " + "AKIA" + "ABCDEFGHIJKLMNOP" + "\n", encoding="utf-8")
    code, out, _ = run(dest, source, capsys)
    assert code == 0
    assert "flagged: 1 files" in out
    assert out.split("flagged:\n")[1].splitlines()[0].strip() == "knowledge/computing/attention-replaces-recurrence.md"
    assert "AKIA" in (dest / "knowledge/computing/attention-replaces-recurrence.md").read_text(encoding="utf-8")
