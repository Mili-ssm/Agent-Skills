import pytest

import mem

OLD = "knowledge/computing/attention-replaces-recurrence.md"
NEW = "knowledge/computing/attention-beats-recurrence.md"
LIT = "literature/computing/2017-vaswani-attention.md"


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file() and p.name != ".curation-log"}  # the log is append-only


def write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def append(root, rel, text):
    path = root / rel
    path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")


def run(root, *args):
    return mem.main(["--root", str(root), "rename", *args])


def test_rewrites_links_everywhere_and_check_passes(hub_root, capsys):
    stem = "attention-replaces-recurrence"
    append(hub_root, OLD, f"\n[self]({stem}.md) [anchor]({stem}.md#claim)\n")
    append(hub_root, LIT, f"\n[a](../../knowledge/computing/{stem}.md) and [x](https://e.org/{stem}.md)\n")
    write(hub_root, "docs/search-eval.md",
          f"| q | [n](../knowledge/computing/{stem}.md#evidence \"t\") |\n")
    fenced = f"```\n[a](../knowledge/computing/{stem}.md)\n```\nand `[a]({stem}.md)`\n"
    write(hub_root, "docs/code.md", fenced)
    assert run(hub_root, OLD, "attention-beats-recurrence.md") == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == NEW
    assert captured.err.strip() == "rewrote 5 links in 4 files"
    assert not (hub_root / OLD).exists() and (hub_root / NEW).is_file()
    new = "attention-beats-recurrence"
    assert f"[self]({new}.md) [anchor]({new}.md#claim)" in (hub_root / NEW).read_text()
    assert f"[a](../../knowledge/computing/{new}.md) and [x](https://e.org/{stem}.md)" in \
        (hub_root / LIT).read_text()
    assert f"[n](../knowledge/computing/{new}.md#evidence \"t\")" in (hub_root / "docs/search-eval.md").read_text()
    assert (hub_root / "docs/code.md").read_text() == fenced
    assert new in (hub_root / "knowledge/computing/README.md").read_text()
    assert mem.check(hub_root) == []


def test_moves_sources_folder(hub_root):
    write(hub_root, ".sources/2017-vaswani-attention/source.txt", "text")
    assert run(hub_root, LIT, "2017-vaswani-attention-is-all") == 0
    assert (hub_root / ".sources/2017-vaswani-attention-is-all/source.txt").read_text() == "text"
    assert not (hub_root / ".sources/2017-vaswani-attention").exists()
    assert mem.check(hub_root) == []


@pytest.mark.parametrize("note, stem", [
    (OLD, "Bad Name"),
    (OLD, "use-attention"),
    (OLD, "a" * 81),
    (OLD, "attention-replaces-recurrence"),
    (LIT, "2018-vaswani-attention"),
    (LIT, "2017-vaswani-vaswani-x"),
    ("research/2026-11-llm-eval-methods/README.md", "x"),
    ("knowledge/computing/README.md", "x"),
    ("knowledge/computing/missing.md", "x"),
])
def test_refusals_leave_hub_untouched(hub_root, capsys, note, stem):
    before = snapshot(hub_root)
    assert run(hub_root, note, stem) == 1
    assert capsys.readouterr().err.startswith("mem: ")
    assert snapshot(hub_root) == before


def test_refuses_stem_used_in_another_folder_and_existing_sources(hub_root):
    write(hub_root, "knowledge/biology/taken.md", "x")
    write(hub_root, ".sources/free/source.txt", "t")
    before = snapshot(hub_root)
    assert run(hub_root, OLD, "taken") == 1
    assert run(hub_root, OLD, "free") == 1
    assert snapshot(hub_root) == before


def test_multi_token_author_slug_is_kept_whole(hub_root):
    rel = "literature/computing/2019-vanderberg-x.md"
    write(hub_root, rel, (hub_root / LIT).read_text().replace("[Vaswani, Shazeer]", "[Van der Berg]")
          .replace("year: 2017", "year: 2019"))
    assert run(hub_root, rel, "2019-van-bar-x") == 1
    assert run(hub_root, rel, "2019-vanderberg-y") == 0
    write(hub_root, "literature/computing/2019-van-der-berg-y.md",
          (hub_root / "literature/computing/2019-vanderberg-y.md").read_text())
    assert run(hub_root, "literature/computing/2019-van-der-berg-y.md", "2019-van-bar-y") == 1
    assert run(hub_root, "literature/computing/2019-van-der-berg-y.md", "2019-van-der-berg-z") == 0


def test_refuses_unwritable_files_before_writing_anything(hub_root, capsys, monkeypatch):
    stem = "attention-replaces-recurrence"
    append(hub_root, LIT, f"\n[a](../../knowledge/computing/{stem}.md)\n")
    before = snapshot(hub_root)
    real = mem.os.access
    monkeypatch.setattr(mem.os, "access", lambda p, mode: False if p == (hub_root / LIT).resolve() else real(p, mode))
    assert run(hub_root, OLD, "attention-beats-recurrence") == 1
    assert "not writable: literature/computing/2017-vaswani-attention.md" in capsys.readouterr().err
    assert snapshot(hub_root) == before


def test_rewrites_the_local_copy_path_in_notes(hub_root, capsys):
    write(hub_root, ".sources/2017-vaswani-attention/p.txt", "t")
    append(hub_root, LIT, "\nLocal copy: `.sources/2017-vaswani-attention/p.txt`, not `.sources/2017-vaswani-attention-x/`\n")
    assert run(hub_root, LIT, "2017-vaswani-attention-is-all") == 0
    assert capsys.readouterr().err.strip() == "rewrote 4 links in 4 files"  # 3 links in other notes + the note's own copy path
    text = (hub_root / "literature/computing/2017-vaswani-attention-is-all.md").read_text()
    assert "`.sources/2017-vaswani-attention-is-all/p.txt`, not `.sources/2017-vaswani-attention-x/`" in text


def test_rename_takes_no_prefix(hub_root, capsys):
    before = snapshot(hub_root)
    assert run(hub_root, "attention-replaces", "attention-beats-recurrence") == 1
    assert snapshot(hub_root) == before


def test_refuses_a_hidden_note_and_an_unreadable_linker(hub_root, capsys):
    write(hub_root, "knowledge/computing/.draft-note.md", "x\n")
    before = snapshot(hub_root)
    assert run(hub_root, "knowledge/computing/.draft-note.md", "draft-note") == 1
    (hub_root / "docs").mkdir(exist_ok=True)
    (hub_root / "docs" / "bad.md").write_bytes(b"\xff\xfe [x](../" + OLD.encode() + b")\n")
    before = snapshot(hub_root)
    assert run(hub_root, OLD, "attention-beats-recurrence") == 1
    assert "cannot read docs/bad.md" in capsys.readouterr().err and snapshot(hub_root) == before


def test_rename_repoints_a_reference_definition(hub_root):
    stem = "attention-replaces-recurrence"
    append(hub_root, LIT, f"\nSee [a][r].\n\n[r]: ../../knowledge/computing/{stem}.md#claim\n")
    assert run(hub_root, OLD, "attention-beats-recurrence.md") == 0
    assert "[r]: ../../knowledge/computing/attention-beats-recurrence.md#claim" in (hub_root / LIT).read_text()
    assert mem.check(hub_root) == []


def restore(root, handle):
    return mem.main(["--root", str(root), "restore", handle])


def test_restore_undoes_a_rename_byte_for_byte(hub_root, capsys):
    stem = "attention-replaces-recurrence"
    append(hub_root, OLD, f"\n[self]({stem}.md)\n")
    append(hub_root, LIT, f"\n[a](../../knowledge/computing/{stem}.md)\n")
    write(hub_root, f".sources/{stem}/source.txt", "text")
    before = snapshot(hub_root)
    assert run(hub_root, OLD, "attention-beats-recurrence") == 0
    assert snapshot(hub_root) != before
    capsys.readouterr()
    assert restore(hub_root, "attention-beats-recurrence") == 0
    assert snapshot(hub_root) == before
    assert mem.check(hub_root) == []


def test_restore_after_rename_refuses_when_a_rewritten_file_changed_since(hub_root, capsys):
    append(hub_root, LIT, "\n[a](../../knowledge/computing/attention-replaces-recurrence.md)\n")
    assert run(hub_root, OLD, "attention-beats-recurrence") == 0
    append(hub_root, LIT, "\nEdited later.\n")
    edited = snapshot(hub_root)
    capsys.readouterr()
    assert restore(hub_root, "attention-beats-recurrence") == 2
    assert LIT in capsys.readouterr().err
    assert snapshot(hub_root) == edited


def test_unify_then_rename_is_undone_by_two_restores_in_reverse_order(hub_root, tmp_path, capsys):
    def new(slug, claim, evidence="Observed."):
        body = tmp_path / f"{slug}.md"
        body.write_text(f"## Claim\n\n{claim}\n\n## Evidence\n\n{evidence}\n\n## Applies when\n\nAlways.\n\n"
                        "## Does not apply when\n\nNever.\n", encoding="utf-8")
        assert mem.main(["--root", str(hub_root), "new", "knowledge", "--slug", slug, "--claim", claim,
                         "--topics", "computing", "--confidence", "medium", "--level", "intermediate",
                         "--origin", "experience", "--body-file", str(body)]) == 0
    new("mica-sheets-flex", "Mica sheets flex")
    new("mica-sheets-bend", "Mica sheets bend")
    new("zinc-hinges-rust", "Zinc hinges rust", "See [m](mica-sheets-bend.md).")
    unified = tmp_path / "u.md"
    unified.write_text("## Claim\n\nMica sheets flex and bend.\n\n## Evidence\n\nObserved.\n\n"
                       "## Applies when\n\nAlways.\n\n## Does not apply when\n\nNever.\n", encoding="utf-8")
    start = snapshot(hub_root)
    assert mem.main(["--root", str(hub_root), "unify", "mica-sheets-flex", "mica-sheets-bend",
                     "--body-file", str(unified)]) == 0
    unified_state = snapshot(hub_root)
    assert run(hub_root, "mica-sheets-flex", "mica-sheets-bend-and-flex") == 0
    capsys.readouterr()
    assert restore(hub_root, "mica-sheets-bend-and-flex") == 0
    assert snapshot(hub_root) == unified_state
    assert restore(hub_root, "mica-sheets-flex") == 0
    assert snapshot(hub_root) == start
    assert mem.check(hub_root) == []
