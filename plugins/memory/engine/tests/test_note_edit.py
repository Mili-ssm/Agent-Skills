"""`mem note edit`: a section, the claim or the topics of a note, through the guard, with undo."""

import io

import mem
import pytest
import yaml
from commands import edit
from notes import index as index_files

REL = "knowledge/computing/attention-replaces-recurrence.md"
EXIT_USAGE = 2  # argparse's exit code, which `mem` also uses for a refused edit
EXIT_REFUSED = 4  # a refused write (secret or term)
HANDLE = "attention-replaces-recurrence"
INDEX = "knowledge/computing/README.md"
EVIDENCE = (
    "See [Attention Is All You Need](../../literature/computing/2017-vaswani-attention.md) "
    "for the original results."
)
FAKE_TOKEN = "ghp_" + "a" * 36  # built from parts: obviously fake


@pytest.fixture
def run(hub_root, capsys):
    def go(*argv):
        code = mem.main(["--root", str(hub_root), "note", "edit", *argv])
        out = capsys.readouterr()
        return code, out.out, out.err

    return go


def body(tmp_path, text, name="body.md"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def snapshot(root):
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.name != ".curation-log"
    }


def restore(hub_root, capsys):
    code = mem.main(["--root", str(hub_root), "restore", HANDLE])
    capsys.readouterr()
    return code


def test_section_replaces_only_that_section_and_bumps_updated(run, hub_root, tmp_path):
    before = (hub_root / REL).read_text()
    new = f"{EVIDENCE} Its tables also show the training cost.\n"
    code, out, _ = run(HANDLE, "--section", "Evidence", "--body-file", body(tmp_path, new))
    assert code == 0
    assert out == f"{HANDLE}\tedited section Evidence\n"
    after = (hub_root / REL).read_text()
    assert "Its tables also show the training cost." in after
    assert after.replace(new.strip(), EVIDENCE) == before.replace(
        "updated: 2026-11-07", f"updated: '{mem.datetime.date.today()}'"
    )
    assert mem.check(hub_root) == []


def test_section_accepts_a_path_and_reads_stdin(run, hub_root, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(f"{EVIDENCE} Plus a note.\n"))
    assert run(REL, "--section", "Evidence", "--body-file", "-")[0] == 0
    assert "Plus a note." in (hub_root / REL).read_text()


def test_section_guard_refuses_a_shrink_until_shrink_is_given(run, hub_root, tmp_path):
    before = snapshot(hub_root)
    code, _, err = run(HANDLE, "--section", "Evidence", "--body-file", body(tmp_path, "Short.\n"))
    assert code == EXIT_USAGE and "--shrink" in err
    assert snapshot(hub_root) == before
    assert (
        run(HANDLE, "--section", "Evidence", "--shrink", "--body-file", body(tmp_path, "Short.\n"))[
            0
        ]
        == 0
    )
    assert "## Evidence\n\nShort.\n\n## Applies when" in (hub_root / REL).read_text()


@pytest.mark.parametrize(
    "section, text",
    [("Nope", "Text here.\n"), ("Evidence", "## Another\n\nx\n"), ("Evidence", "  \n")],
)
def test_section_refusals_write_nothing(run, hub_root, tmp_path, section, text):
    before = snapshot(hub_root)
    assert run(HANDLE, "--section", section, "--body-file", body(tmp_path, text))[0] == EXIT_USAGE
    assert snapshot(hub_root) == before


def test_claim_one_word_correction_needs_no_shrink(run, hub_root):
    code, out, _ = run(
        HANDLE, "--claim", "Self-attention can replace recurrence for sequence modelling"
    )
    assert code == 0 and out == f"{HANDLE}\tedited claim\n"
    text = (hub_root / REL).read_text()
    assert "claim: Self-attention can replace recurrence for sequence modelling\n" in text
    assert f"updated: '{mem.datetime.date.today()}'" in text
    assert "modelling" in (hub_root / INDEX).read_text()
    assert mem.check(hub_root) == []


def test_claim_guard_refuses_a_big_drop(run, hub_root):
    before = snapshot(hub_root)
    code, _, err = run(HANDLE, "--claim", "Attention works")
    assert code == EXIT_USAGE and "--shrink" in err
    assert snapshot(hub_root) == before
    assert run(HANDLE, "--claim", "Attention works", "--shrink")[0] == 0
    assert mem.check(hub_root) == []


def test_topics_replace_and_rebuild_the_index(run, hub_root):
    code, out, _ = run(HANDLE, "--topics", "ml,computing,algorithms")
    assert code == 0 and out == f"{HANDLE}\tedited topics\n"
    assert "topics: [ml, computing, algorithms]\n" in (hub_root / REL).read_text()
    assert "### algorithms" in (hub_root / INDEX).read_text()
    assert mem.check(hub_root) == []


def test_topics_refuse_unknown_and_other_domain(run, hub_root, capsys):
    before = snapshot(hub_root)
    assert run(HANDLE, "--topics", "ml,nope")[0] == EXIT_USAGE
    code, _, err = run(HANDLE, "--topics", "ml")
    assert code == EXIT_USAGE and "ancestor" in err
    code, _, err = run(HANDLE, "--topics", "biology")
    assert code == EXIT_USAGE and "domain" in err
    assert snapshot(hub_root) == before


def test_options_combine_in_one_call_and_one_restore_undoes_them(run, hub_root, tmp_path, capsys):
    before = snapshot(hub_root)
    new = f"{EVIDENCE} Extra words for the section.\n"
    code, out, _ = run(
        HANDLE,
        "--section",
        "Evidence",
        "--body-file",
        body(tmp_path, new),
        "--claim",
        "Self-attention can replace recurrence for sequence modelling",
        "--topics",
        "ml,computing,algorithms",
    )
    assert code == 0 and out == f"{HANDLE}\tedited section Evidence, claim, topics\n"
    assert mem.check(hub_root) == []
    assert restore(hub_root, capsys) == 0
    assert snapshot(hub_root) == before
    assert mem.check(hub_root) == []


@pytest.mark.parametrize(
    "argv",
    [
        ["--claim", "Self-attention can replace recurrence for sequence modelling"],
        ["--topics", "ml,computing,algorithms"],
    ],
)
def test_restore_returns_the_exact_bytes_and_the_index(run, hub_root, capsys, argv):
    before = snapshot(hub_root)
    assert run(HANDLE, *argv)[0] == 0
    assert snapshot(hub_root) != before
    assert restore(hub_root, capsys) == 0
    assert snapshot(hub_root) == before
    assert mem.check(hub_root) == []


def test_secret_is_refused_with_exit_4_and_nothing_written(run, hub_root, tmp_path):
    before = snapshot(hub_root)
    assert (
        run(
            HANDLE,
            "--section",
            "Evidence",
            "--body-file",
            body(tmp_path, f"{EVIDENCE} {FAKE_TOKEN}\n"),
        )[0]
        == EXIT_REFUSED
    )
    assert (
        run(HANDLE, "--claim", f"Self-attention replaces recurrence {FAKE_TOKEN}")[0]
        == EXIT_REFUSED
    )
    assert snapshot(hub_root) == before
    assert not (hub_root / ".curation-log").exists()


def test_forbidden_term_is_refused(run, hub_root, tmp_path):
    terms = tmp_path / "mem-config" / "agent-memory" / "forbidden-terms"
    terms.parent.mkdir(parents=True)
    terms.write_text("zetacorp\n")
    before = snapshot(hub_root)
    assert (
        run(HANDLE, "--claim", "Self-attention can replace recurrence for zetacorp sequences")[0]
        == EXIT_REFUSED
    )
    assert snapshot(hub_root) == before


def test_part_of_survives_an_edit(run, hub_root, tmp_path, capsys):
    assert (
        mem.main([
            "--root",
            str(hub_root),
            "synthesis",
            "new",
            "--title",
            "Attention",
            "--topics",
            "ml",
            "--slug",
            "attention",
            "--summary-file",
            body(tmp_path, "How it works.\n", "s.md"),
        ])
        == 0
    )
    src = f"Sources: [a](../{REL})"
    assert (
        mem.main([
            "--root",
            str(hub_root),
            "synthesis",
            "add",
            "s:attention",
            "--section",
            "Part",
            "--body-file",
            body(tmp_path, f"Text of the part.\n\n{src}\n", "p.md"),
        ])
        == 0
    )
    assert (
        mem.main(["--root", str(hub_root), "synthesis", "attach", HANDLE, "s:attention#part"]) == 0
    )
    capsys.readouterr()
    assert (
        run(HANDLE, "--claim", "Self-attention can replace recurrence for sequence modelling")[0]
        == 0
    )
    text = (hub_root / REL).read_text()
    assert 'part_of: "attention#part"' in text and "part_of_hash:" in text
    assert mem.check(hub_root) == []
    digest = [ln for ln in text.splitlines() if ln.startswith("part_of_hash:")]
    assert (
        run(
            HANDLE,
            "--section",
            "Evidence",
            "--body-file",
            body(tmp_path, f"{EVIDENCE} More words here.\n", "e.md"),
        )[0]
        == 0
    )
    after = (hub_root / REL).read_text()
    assert [ln for ln in after.splitlines() if ln.startswith("part_of_hash:")] == digest
    assert mem.check(hub_root) == []


def test_refused_when_the_file_changed_since_it_was_read(run, hub_root, tmp_path, monkeypatch):
    real = edit._edited_note_text

    def meddle(*a, **k):
        path = hub_root / REL
        path.write_text(path.read_text() + "\nA late line.\n")
        return real(*a, **k)

    monkeypatch.setattr(edit, "_edited_note_text", meddle)
    changed = (hub_root / REL).read_bytes()
    code, _, err = run(
        HANDLE, "--claim", "Self-attention can replace recurrence for sequence modelling"
    )
    assert code == EXIT_USAGE and "changed" in err
    assert (hub_root / REL).read_bytes() == changed + b"\nA late line.\n"


def test_read_only_store_and_missing_options(run, hub_root, tmp_path):
    for argv in ([HANDLE], [HANDLE, "--section", "Evidence"]):
        with pytest.raises(SystemExit) as stop:
            run(*argv)
        assert stop.value.code == EXIT_USAGE
    (hub_root / "mem-store.yaml").unlink()
    assert (
        run(HANDLE, "--claim", "Self-attention can replace recurrence for sequence modelling")[0]
        == EXIT_USAGE
    )


def test_a_change_between_read_and_swap_writes_nothing(run, hub_root, monkeypatch):
    real = edit._index_files

    def meddle(root):
        path = hub_root / REL
        path.write_text(path.read_text() + "\nA late line.\n")
        return real(root)

    monkeypatch.setattr(edit, "_index_files", meddle)
    before = snapshot(hub_root)
    code, _, err = run(
        HANDLE, "--claim", "Self-attention can replace recurrence for sequence modelling"
    )
    assert code == EXIT_USAGE and "changed" in err
    assert snapshot(hub_root) == {**before, REL: before[REL] + b"\nA late line.\n"}
    assert not (hub_root / ".curation-log").exists()


def test_any_error_after_the_swap_rolls_everything_back(run, hub_root, monkeypatch):
    log = hub_root / ".curation-log"
    log.write_text('{"t": "x", "action": "other", "handle": "a"}\n')
    before, log_before = snapshot(hub_root), log.read_bytes()

    def boom(root):
        raise yaml.YAMLError("broken")

    monkeypatch.setattr(index_files, "apply_index", boom)
    assert (
        run(HANDLE, "--claim", "Self-attention can replace recurrence for sequence modelling")[0]
        == EXIT_USAGE
    )
    assert snapshot(hub_root) == before and log.read_bytes() == log_before
