from conftest import usage_log_path
import json

import mem
import notes

from test_find_new import write_note
from test_search_stats import add

LIT = "literature/computing/2017-vaswani-attention.md"
RES = "research/2026-11-llm-eval-methods/README.md"


def show(root, capsys, *argv):
    code = mem.main(["--root", str(root), "show", *argv])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_handle_with_and_without_md_and_research_id(hub_root, capsys):
    for arg, rel in (("2017-vaswani-attention", LIT), ("2017-vaswani-attention.md", LIT),
                     ("2026-11-llm-eval-methods", RES)):
        code, out, _ = show(hub_root, capsys, arg, "--section", "x")
        assert code == 0 and out.startswith(f"== {rel}\n")


def test_unique_prefix_of_handle_and_of_path(hub_root, capsys):
    for arg in ("attention-repl", "knowledge/computing/attention-repl"):
        code, out, _ = show(hub_root, capsys, arg, "--section", "claim")
        assert code == 0 and out.startswith("== knowledge/computing/attention-replaces-recurrence.md")


def test_exact_handle_wins_over_prefix(hub_root, capsys):
    add(hub_root, "foo", "Foo")
    add(hub_root, "foo-bar", "Foo bar")
    code, out, _ = show(hub_root, capsys, "foo")
    assert code == 0 and out.startswith("== knowledge/computing/foo.md")


def test_ambiguous_show_reports_and_still_shows_others(hub_root, capsys):
    add(hub_root, "foo-one", "One")
    add(hub_root, "foo-two", "Two")
    code, out, err = show(hub_root, capsys, "foo", LIT, "--section", "x")
    assert code == 1
    assert "== foo\n(ambiguous: 2 notes match)" in out and f"== {LIT}" in out
    assert err.splitlines() == ["ambiguous: foo matches 2 notes:", "knowledge/computing/foo-one.md",
                                "knowledge/computing/foo-two.md"]


def test_ambiguous_lists_at_most_ten(hub_root, capsys):
    for i in range(12):
        add(hub_root, f"many-{i:02d}", f"Many {i}")
    _, _, err = show(hub_root, capsys, "many")
    assert err.splitlines()[0] == "ambiguous: many matches 12 notes:" and len(err.splitlines()) == 11


def test_not_found_as_before(hub_root, capsys):
    code, out, err = show(hub_root, capsys, "nothing-like-it")
    assert code == 1 and out.strip() == "== nothing-like-it\n(not found)" and err == ""


def test_resolve_note_contract(hub_root):
    add(hub_root, "foo-one", "One")
    add(hub_root, "foo-two", "Two")
    assert mem.resolve_note(hub_root, "2017-vaswani") == (hub_root / LIT).resolve()
    assert mem.resolve_note(hub_root, "foo") == ["knowledge/computing/foo-one.md", "knowledge/computing/foo-two.md"]
    assert mem.resolve_note(hub_root, "zzz") is None and mem.resolve_note(hub_root, "") is None


def test_related_and_passages_use_the_resolver(hub_root, capsys):
    assert mem.main(["--root", str(hub_root), "related", "2017-vaswani-attention"]) == 0
    assert "attention-replaces-recurrence" in capsys.readouterr().out
    add(hub_root, "foo-one", "One")
    add(hub_root, "foo-two", "Two")
    assert mem.main(["--root", str(hub_root), "related", "foo"]) == 1
    assert "ambiguous: foo matches 2 notes:" in capsys.readouterr().err
    assert mem.main(["--root", str(hub_root), "passages", "foo", "one"]) == 1
    assert "ambiguous: foo matches 2 notes:" in capsys.readouterr().err


def test_usage_log_records_resolved_paths(hub_root, capsys, monkeypatch):
    monkeypatch.delenv("MEM_USAGE_LOG", raising=False)
    show(hub_root, capsys, "2017-vaswani-attention", "--section", "x")
    entry = json.loads(usage_log_path().read_text().splitlines()[-1])
    assert entry["paths"] == [LIT]


def test_check_rejects_shared_handle(hub_root):
    write_note(hub_root, "knowledge/biology/2017-vaswani-attention.md",
               "---\nclaim: C\ntopics: [biology]\nconfidence: low\norigin: experience\nupdated: 2026-11-07\n---\n")
    problems = [p for p in mem.check(hub_root) if "handle" in p.message]
    assert {p.path for p in problems} == {LIT, "knowledge/biology/2017-vaswani-attention.md"}
    assert all("also used by" in p.message for p in problems)
    assert LIT in next(p for p in problems if p.path != LIT).message


def test_conclusion_alias_per_type(hub_root, capsys):
    _, out, _ = show(hub_root, capsys, "attention-repl", LIT, RES, "--section", "Conclusion")
    assert "## Claim" in out and "## Does not apply when" in out and "## Evidence" not in out
    assert "## TL;DR" in out and "## Question" in out
    assert "(no section" not in out


def test_conclusion_alias_mixed_and_other_kind(hub_root, capsys):
    write_note(hub_root, "docs/x.md", "# T\n\n## First\na\n\n## Second\nb\n")
    _, out, _ = show(hub_root, capsys, "docs/x.md", "--section", "conclusion")
    assert "## First" in out and "## Second" not in out and "(no section" not in out
    _, out, _ = show(hub_root, capsys, "attention-repl", "--section", "Evidence", "--section", "CONCLUSION")
    assert "## Evidence" in out and "## Claim" in out


def test_md_argument_matches_exactly_never_by_prefix(hub_root, capsys):
    code, out, _ = show(hub_root, capsys, "knowledge/computing/attention-replaces.md")
    assert code == 1 and out.strip().endswith("(not found)")
    assert mem.resolve_note(hub_root, "attention-repl.md") is None
    assert mem.resolve_note(hub_root, "attention-replaces-recurrence.md") is not None


def test_prefix_can_be_turned_off(hub_root):
    assert mem.resolve_note(hub_root, "attention-repl", prefix=False) is None
    assert mem.resolve_note(hub_root, "attention-replaces-recurrence", prefix=False) is not None


def test_handle_resolution_parses_no_note(hub_root, capsys, monkeypatch):
    def fail(*_):
        raise AssertionError("parsed a note")

    monkeypatch.setattr(mem, "_read_note", fail)
    monkeypatch.setattr(notes, "_read_note", fail)  # discover_notes lives in notes since the split
    code, out, _ = show(hub_root, capsys, "2017-vaswani-attention", "--outline")
    assert code == 0 and out.startswith(f"== {LIT}")


def test_conclusion_without_lead_sections_is_a_missing_section(hub_root, capsys):
    write_note(hub_root, "knowledge/computing/odd.md",
               "---\nclaim: Odd\ntopics: [llm]\nconfidence: low\norigin: experience\nupdated: 2026-11-07\n---\n"
               "## Other\nx\n")
    _, out, _ = show(hub_root, capsys, "odd", "--section", "conclusion")
    assert '(no section "conclusion")' in out


def test_handles_flag_prints_short_handles_that_show_resolves(hub_root, capsys):
    add(hub_root, "foo-one-thing", "One thing about foo")
    add(hub_root, "foo-two-things", "Two things about foo")
    assert mem.main(["--root", str(hub_root), "find", "--type", "knowledge", "--handles"]) == 0
    names = [line.split("\t")[0] for line in capsys.readouterr().out.splitlines()]
    assert "foo-one" in names and "foo-two" in names and not any("/" in n for n in names)
    shorts = mem.short_handles(hub_root)
    assert len(set(shorts.values())) == len(shorts)
    for rel, name in shorts.items():
        assert mem.resolve_note(hub_root, name) == (hub_root / rel).resolve()
    assert mem.main(["--root", str(hub_root), "search", "foo", "--handles"]) == 0
    assert capsys.readouterr().out.split("\t")[0] in ("foo-one", "foo-two")
