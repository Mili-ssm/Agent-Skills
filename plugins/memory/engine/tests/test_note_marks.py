"""`mem note confirm` and `mem note dispute`: a source's verdict on a knowledge note, with undo."""

import datetime

import mem
import pytest
from notes import check as check_rules
from notes import note as note_files

REL = "knowledge/computing/attention-replaces-recurrence.md"
HANDLE = "attention-replaces-recurrence"
URL = "https://example.org/paper"
EXIT_REFUSED = 2  # mem's exit code for a refused or invalid command
EXIT_FORBIDDEN_TERM = 4  # mem's exit code when a text holds a secret or forbidden term
FACT = "the paper reports 28.4 BLEU"
QUOTE = "achieves 28.4 BLEU on WMT 2014"
FAKE_TOKEN = "ghp_" + "a" * 36  # built from parts: obviously fake


@pytest.fixture
def run(hub_root, capsys):
    def go(verb, *argv):
        code = mem.main(["--root", str(hub_root), "note", verb, *argv])
        out = capsys.readouterr()
        return code, out.out, out.err

    return go


def marks(*extra, source=URL, fact=FACT, quote=QUOTE):
    return [HANDLE, "--fact", fact, "--source", source, "--quote", quote, *extra]


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


def meta(root):
    return note_files.split_frontmatter((root / REL).read_text())[0]


def test_confirm_appends_one_evidence_line_and_check_stays_clean(run, hub_root):
    before = (hub_root / REL).read_text()
    code, out, _ = run("confirm", *marks())
    assert (code, out) == (0, f"{HANDLE}\tconfirmed\n")
    after = (hub_root / REL).read_text()
    today = datetime.date.today().isoformat()
    line = f'- {today} confirmed: {FACT} "{QUOTE}" ([example.org]({URL}))'
    assert line in after.split("## Evidence")[1].split("## Applies when")[0]
    assert (
        after.replace(line + "\n", "", 1).replace(f"updated: '{today}'", "updated: 2026-11-07")
        == before
    )
    assert check_rules.check(hub_root) == []


def test_confirm_then_restore_returns_the_exact_bytes(run, hub_root, capsys):
    before = snapshot(hub_root)
    assert run("confirm", *marks())[0] == 0
    assert snapshot(hub_root) != before
    assert restore(hub_root, capsys) == 0
    assert snapshot(hub_root) == before


def test_dispute_sets_the_field_and_leaves_the_rest_of_the_note_alone(run, hub_root):
    before = (hub_root / REL).read_text()
    code, out, _ = run("dispute", *marks())
    assert (code, out) == (0, f"{HANDLE}\tdisputed\n")
    after = (hub_root / REL).read_text()
    today = datetime.date.today().isoformat()
    assert meta(hub_root)["disputed"] == [
        {"date": today, "fact": FACT, "source": URL, "quote": QUOTE}
    ]
    assert meta(hub_root)["claim"] == note_files.split_frontmatter(before)[0]["claim"]
    assert note_files.split_frontmatter(after)[1] == note_files.split_frontmatter(before)[1]
    assert check_rules.check(hub_root) == []


def test_dispute_then_restore_returns_the_exact_bytes(run, hub_root, capsys):
    before = snapshot(hub_root)
    assert run("dispute", *marks())[0] == 0
    assert restore(hub_root, capsys) == 0
    assert snapshot(hub_root) == before


def test_a_second_dispute_adds_an_entry_and_clear_removes_the_field(run, hub_root):
    assert run("dispute", *marks())[0] == 0
    assert run("dispute", *marks(source="https://example.org/two"))[0] == 0
    assert [e["source"] for e in meta(hub_root)["disputed"]] == [URL, "https://example.org/two"]
    assert check_rules.check(hub_root) == []
    code, out, _ = run("dispute", HANDLE, "--clear")
    assert (code, out) == (0, f"{HANDLE}\tcleared the dispute\n")
    assert "disputed" not in meta(hub_root)
    assert check_rules.check(hub_root) == []
    assert run("dispute", HANDLE, "--clear")[0] == EXIT_REFUSED  # nothing to clear


@pytest.mark.parametrize("verb", ["confirm", "dispute"])
@pytest.mark.parametrize(
    "kw",
    [
        {"source": "ftp://example.org/x"},
        {"source": "example.org/x"},
        {"source": "https://"},
        {"quote": "  "},
        {"fact": ""},
    ],
)
def test_bad_inputs_are_refused_and_write_nothing(run, hub_root, verb, kw):
    before = snapshot(hub_root)
    code, _, err = run(verb, *marks(**kw))
    assert code == EXIT_REFUSED and err
    assert snapshot(hub_root) == before


@pytest.mark.parametrize("verb", ["confirm", "dispute"])
def test_a_missing_note_and_a_non_knowledge_note_are_refused(run, hub_root, verb):
    assert (
        run(verb, "no-such-note", "--fact", FACT, "--source", URL, "--quote", QUOTE)[0]
        == EXIT_REFUSED
    )
    lit = next(p for p in (hub_root / "literature").rglob("*.md") if p.name != "README.md")
    code, _, err = run(
        verb,
        lit.relative_to(hub_root).as_posix(),
        "--fact",
        FACT,
        "--source",
        URL,
        "--quote",
        QUOTE,
    )
    assert code == EXIT_REFUSED and "knowledge note" in err


@pytest.mark.parametrize("verb", ["confirm", "dispute"])
def test_a_secret_in_the_texts_is_refused(run, hub_root, verb):
    before = snapshot(hub_root)
    assert run(verb, *marks(quote=f"token {FAKE_TOKEN}"))[0] == EXIT_FORBIDDEN_TERM
    assert snapshot(hub_root) == before


def test_confirm_adds_the_evidence_section_when_the_note_has_none(run, hub_root):
    path = hub_root / REL
    text = path.read_text()
    head, rest = text.split("## Evidence")
    path.write_text(head + "## Applies when" + rest.split("## Applies when", 1)[1])
    assert run("confirm", *marks())[0] == 0
    assert text and path.read_text().rstrip().endswith(f"([example.org]({URL}))")


def test_a_disputed_note_is_flagged_in_search_find_and_show(run, hub_root, capsys):
    assert run("dispute", *marks())[0] == 0
    for cmd in (["search", "attention recurrence"], ["find", "--type", "knowledge"]):
        assert mem.main(["--root", str(hub_root), *cmd]) == 0
        first = capsys.readouterr().out.splitlines()[0]
        assert first.endswith("for sequence transduction  [disputed]"), cmd
    for cmd in (
        ["search", "attention recurrence", "--detail", "facts"],
        ["find", "--type", "knowledge", "--detail", "facts"],
        ["show", HANDLE, "--outline"],
    ):
        assert mem.main(["--root", str(hub_root), *cmd]) == 0
        out = capsys.readouterr().out
        assert (
            "confidence: medium [disputed] \u00b7 updated:" in out
            or "confidence: high [disputed] \u00b7 updated:" in out
        ), cmd


def test_curate_notes_lists_disputed_notes_with_their_first_source(run, hub_root, capsys):
    assert run("dispute", *marks())[0] == 0
    assert run("dispute", *marks(source="https://example.org/two"))[0] == 0
    assert mem.main(["--root", str(hub_root), "curate", "--notes"]) == 0
    out = capsys.readouterr().out
    claim = meta(hub_root)["claim"]
    assert out == (
        "notes disputed by a source (decide: correct the note with mem note edit, "
        f"or mem note dispute <note> --clear)\n  {HANDLE}  {claim}  (source: {URL})\n"
    )


def test_check_rejects_a_malformed_disputed_field(run, hub_root):
    assert run("dispute", *marks())[0] == 0
    path = hub_root / REL
    path.write_text(path.read_text().replace("disputed: [{", "disputed: [{extra: 1, ", 1))
    assert any("disputed" in str(p) for p in check_rules.check(hub_root))
