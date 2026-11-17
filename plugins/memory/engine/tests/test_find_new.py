import re
from datetime import date

import pytest

import mem


def write_note(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_find_topic_expands_descendants(hub_root):
    write_note(hub_root, "literature/computing/2020-lee-llm.md",
               '---\ntitle: T\nauthors: [Lee]\nyear: 2020\nkind: paper\nurl: https://x.org\n'
               'topics: [llm]\nadded: 2026-11-07\n---\n')
    write_note(hub_root, "knowledge/biology/cells.md",
               "---\nclaim: Cells\ntopics: [biology]\nconfidence: low\norigin: experience\n"
               "updated: 2026-11-07\n---\n")
    paths = [rel for rel, _ in mem.find(hub_root, topic="ml")]
    assert paths == [
        "knowledge/computing/attention-replaces-recurrence.md",
        "literature/computing/2017-vaswani-attention.md",
        "literature/computing/2020-lee-llm.md",
        "research/2026-11-llm-eval-methods/README.md",
    ]
    assert "knowledge/biology/cells.md" not in paths


def test_find_type_specific_filter_restricts_type(hub_root):
    result = mem.find(hub_root, kind="paper")
    assert [rel for rel, _ in result] == ["literature/computing/2017-vaswani-attention.md"]


def test_find_knowledge_title_is_claim(hub_root):
    result = dict(mem.find(hub_root, confidence="medium"))
    assert result["knowledge/computing/attention-replaces-recurrence.md"].startswith("Self-attention")


def test_find_skips_unparseable_with_warning(hub_root, capsys):
    write_note(hub_root, "knowledge/computing/broken.md", "no frontmatter\n")
    paths = [rel for rel, _ in mem.find(hub_root)]
    assert "knowledge/computing/broken.md" not in paths
    assert "knowledge/computing/broken.md" in capsys.readouterr().err


def test_find_prints_relative_paths_from_other_cwd(hub_root, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert mem.main(["--root", str(hub_root), "find", "--topic", "llm"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines
    assert all(re.match(r"(literature|knowledge|research)/.*\t", ln) for ln in lines)


TODAY = date(2026, 11, 7)


def fill_placeholders(root):
    for path in root.rglob("*.md"):
        text = path.read_text(encoding="utf-8")
        if "TODO(hub):" in text:
            path.write_text(text.replace("TODO(hub):", "Done:"), encoding="utf-8")


def make_all(root):
    lit = mem.new_note(root, "literature", slug="x", topics=["llm"], today=TODAY, title="Title",
                       author="García", year=2024, kind="paper", level="advanced", url="https://x.org/a")
    know = mem.new_note(root, "knowledge", slug="k-one", topics=["biology"], today=TODAY,
                        claim="A claim", confidence="high", level="beginner", origin="experience")
    res = mem.new_note(root, "research", slug="x", topics=["computing"], today=TODAY,
                       title="R", question="Why?")
    return lit, know, res


def test_new_each_type_passes_check(hub_root):
    lit, know, res = make_all(hub_root)
    assert lit == hub_root / "literature" / "computing" / "2024-garcia-x.md"
    assert know == hub_root / "knowledge" / "biology" / "k-one.md"
    assert res == hub_root / "research" / "2026-11-x" / "README.md"
    assert mem.load_yaml(res.read_text(encoding="utf-8").split("---\n")[1])["status"] == "idea"
    problems = mem.check(hub_root)
    assert problems
    assert all("placeholder" in p.message for p in problems)
    fill_placeholders(hub_root)
    assert mem.check(hub_root) == []


def test_new_refuses_empty_author_slug(hub_root):
    with pytest.raises(mem.NewNoteError):
        mem.new_note(hub_root, "literature", slug="x", topics=["llm"], today=TODAY, title="T",
                     author="李", year=2024, kind="paper", level="advanced", url="https://x.org")


def test_new_adds_ancestors(hub_root):
    path = mem.new_note(hub_root, "knowledge", slug="anc", topics=["llm"], today=TODAY,
                        claim="c", confidence="low", level="beginner", origin="research")
    meta, _, _ = mem.split_frontmatter(path.read_text(encoding="utf-8"))
    assert meta["topics"] == ["llm", "deep-learning", "ml", "computing"]


def test_new_quotes_colon_values(hub_root):
    path = mem.new_note(hub_root, "knowledge", slug="q", topics=["biology"], today=TODAY,
                        claim="a: b # c", confidence="low", level="beginner", origin="research")
    meta, _, _ = mem.split_frontmatter(path.read_text(encoding="utf-8"))
    assert meta["claim"] == "a: b # c"


KNOW = dict(claim="c", confidence="low", level="beginner", origin="research")


def test_new_refuses_existing_bad_slug_unknown_topic(hub_root, capsys):
    mem.new_note(hub_root, "knowledge", slug="dup", topics=["biology"], today=TODAY, **KNOW)
    with pytest.raises(mem.NewNoteError):
        mem.new_note(hub_root, "knowledge", slug="dup", topics=["biology"], today=TODAY, **KNOW)
    with pytest.raises(mem.NewNoteError):
        mem.new_note(hub_root, "knowledge", slug="Bad Slug", topics=["biology"], today=TODAY, **KNOW)
    with pytest.raises(mem.NewNoteError):
        mem.new_note(hub_root, "knowledge", slug="ok", topics=["nope"], today=TODAY, **KNOW)
    argv = ["--root", str(hub_root), "new", "knowledge", "--slug", "dup", "--claim", "c",
            "--topics", "biology", "--confidence", "low", "--level", "beginner", "--origin", "research"]
    assert mem.main(argv) == 1
    assert "dup" in capsys.readouterr().err


def test_new_cli_success_prints_rel_path(hub_root, capsys):
    argv = ["--root", str(hub_root), "new", "knowledge", "--slug", "cli", "--claim", "c",
            "--topics", "biology,computing", "--confidence", "low", "--level", "beginner", "--origin", "research"]
    assert mem.main(argv) == 0
    assert capsys.readouterr().out.strip() == "knowledge/biology/cli.md"


def test_find_unknown_topic_fails(hub_root, capsys):
    assert mem.main(["--root", str(hub_root), "find", "--topic", "nope"]) == 1
    assert "unknown topic nope: for free text use: hub.py search \"nope\"" in capsys.readouterr().err


def test_new_places_note_under_root_of_first_topic(hub_root):
    path = mem.new_note(hub_root, "knowledge", slug="first", topics=["biology", "llm"], today=TODAY, **KNOW)
    assert path == hub_root / "knowledge" / "biology" / "first.md"
    path = mem.new_note(hub_root, "literature", slug="deep", topics=["deep-learning"], today=TODAY,
                        title="T", author="Lee", year=2024, kind="paper", level="advanced", url="https://x.org")
    assert path == hub_root / "literature" / "computing" / "2024-lee-deep.md"
    assert (hub_root / "knowledge" / "biology" / "README.md").is_file()


def test_new_refuses_topic_without_root(hub_root):
    with (hub_root / "topics.yaml").open("a", encoding="utf-8") as f:
        f.write("lost: {parent: nowhere}\nodd: {parent: 5}\n")
    for topic in ("lost", "odd"):
        with pytest.raises(mem.NewNoteError, match="no root topic"):
            mem.new_note(hub_root, "knowledge", slug="x", topics=[topic], today=TODAY, **KNOW)
    assert not (hub_root / "knowledge" / "nowhere").exists()
    assert sorted(p.name for p in (hub_root / "knowledge").iterdir()) == ["README.md", "computing"]
    assert mem.main(["--root", str(hub_root), "new", "knowledge", "--slug", "x", "--claim", "c",
                     "--topics", "lost", "--confidence", "low", "--level", "beginner", "--origin", "research"]) == 1


def test_new_knowledge_refuses_instruction_slug(hub_root):
    with pytest.raises(mem.NewNoteError, match="reads as an instruction"):
        mem.new_note(hub_root, "knowledge", slug="use-idempotency-keys", topics=["biology"],
                     today=TODAY, **KNOW)
    assert not (hub_root / "knowledge" / "biology").exists()
    assert mem.main(["--root", str(hub_root), "new", "knowledge", "--slug", "then-fix-it", "--claim",
                     "c", "--topics", "biology", "--confidence", "low", "--level", "beginner", "--origin", "research"]) == 1
    assert not (hub_root / "knowledge" / "biology").exists()


def test_new_literature_author_list_and_repeated_slug(hub_root):
    path = mem.new_note(hub_root, "literature", slug="adam", topics=["deep-learning"], today=TODAY,
                        title="T", author="Kingma,Ba", year=2014, kind="paper", level="advanced", url="https://x.org")
    assert path.name == "2014-kingma-adam.md"
    meta, _, _ = mem.split_frontmatter(path.read_text(encoding="utf-8"))
    assert meta["authors"] == ["Kingma", "Ba"]
    with pytest.raises(mem.NewNoteError, match="repeats the first author"):
        mem.new_note(hub_root, "literature", slug="porter-suffix", topics=["llm"], today=TODAY,
                     title="T", author="Porter", year=1980, kind="paper", level="advanced", url="https://x.org")
    mem.new_note(hub_root, "literature", slug="brownian-motion", topics=["llm"], today=TODAY,
                 title="T", author="Brown", year=2020, kind="paper", level="advanced", url="https://x.org")


def test_new_literature_refuses_slug_starting_with_year(hub_root):
    with pytest.raises(mem.NewNoteError, match="repeats the year"):
        mem.new_note(hub_root, "literature", slug="2004-zaragoza-trec", topics=["llm"], today=TODAY,
                     title="T", author="Zaragoza", year=2004, kind="paper", level="advanced", url="https://x.org")


def _new_knowledge(root, slug, claim):
    return mem.main(["--root", str(root), "new", "knowledge", "--slug", slug, "--claim", claim,
                     "--topics", "computing", "--confidence", "low", "--level", "beginner", "--origin", "experience"])


def test_new_lists_similar_notes_on_stderr(hub_root, capsys):
    assert _new_knowledge(hub_root, "attention-beats-recurrence",
                          "Attention replaces recurrence in sequence models") == 0
    captured = capsys.readouterr()
    assert captured.out == "knowledge/computing/attention-beats-recurrence.md\n"
    lines = captured.err.splitlines()
    assert lines[0].startswith("Similar notes exist:")
    assert any(ln.startswith("similar: knowledge/computing/attention-replaces-recurrence.md\t")
               for ln in lines[1:])
    assert not any("attention-beats-recurrence" in ln for ln in lines[1:])
    assert len(lines) <= 4


def test_new_prints_no_hint_without_matches(hub_root, capsys):
    assert _new_knowledge(hub_root, "zzz", "Qwxzy") == 0
    captured = capsys.readouterr()
    assert captured.out == "knowledge/computing/zzz.md\n"
    assert captured.err == ""


def test_unknown_topic_suggests_close_ids_and_search(hub_root, capsys):
    assert mem.main(["--root", str(hub_root), "find", "--topic", "learning"]) == 1
    err = capsys.readouterr().err
    assert "unknown topic learning" in err and "deep-learning" in err and 'hub.py search "learning"' in err


def test_find_level_filters_to_literature_and_knowledge(hub_root):
    write_note(hub_root, "knowledge/biology/cells.md",
               "---\nclaim: Cells\ntopics: [biology]\nconfidence: low\nlevel: basic\n"
               "origin: experience\nupdated: 2026-11-07\n---\n")
    assert [r for r, _ in mem.find(hub_root, level="basic")] == ["knowledge/biology/cells.md"]
    assert [r for r, _ in mem.find(hub_root, level="advanced")] == [
        "literature/computing/2017-vaswani-attention.md"]
    assert mem.find(hub_root, level="expert") == []
    assert [r for r, _, _ in mem.search(hub_root, "cells", level="basic")] == ["knowledge/biology/cells.md"]
    assert mem.search(hub_root, "attention", level="basic") == []


def test_find_and_search_level_cli(hub_root, capsys):
    assert mem.main(["--root", str(hub_root), "find", "--level", "intermediate"]) == 0
    assert capsys.readouterr().out.startswith("knowledge/computing/attention-replaces-recurrence.md\t")
    assert mem.main(["--root", str(hub_root), "search", "attention", "--level", "advanced"]) == 0
    assert capsys.readouterr().out.startswith("literature/computing/2017-vaswani-attention.md\t")
    with pytest.raises(SystemExit):
        mem.main(["--root", str(hub_root), "find", "--level", "guru"])


def test_new_requires_level_and_writes_it(hub_root, capsys):
    argv = ["--root", str(hub_root), "new", "knowledge", "--slug", "lvl", "--claim", "c",
            "--topics", "biology", "--confidence", "low", "--origin", "research"]
    with pytest.raises(SystemExit):
        mem.main(argv)
    assert "--level" in capsys.readouterr().err
    assert mem.main(argv + ["--level", "niche"]) == 0
    text = (hub_root / "knowledge" / "biology" / "lvl.md").read_text(encoding="utf-8")
    assert "confidence: low\nlevel: niche\norigin: research\n" in text
    lit = ["--root", str(hub_root), "new", "literature", "--title", "T", "--author", "Doe", "--year", "2024",
           "--kind", "book", "--url", "https://x.org", "--topics", "biology", "--slug", "lv"]
    with pytest.raises(SystemExit):
        mem.main(lit)
    assert mem.main(lit + ["--level", "expert"]) == 0
    text = (hub_root / "literature" / "biology" / "2024-doe-lv.md").read_text(encoding="utf-8")
    assert "kind: book\nlevel: expert\nurl:" in text


def test_new_refuses_a_too_long_knowledge_name(hub_root):
    with pytest.raises(mem.NewNoteError, match="too long"):
        mem.new_note(hub_root, "knowledge", slug="a-" + "b" * mem.MAX_KNOWLEDGE_NAME, topics=["biology"],
                     today=TODAY, **KNOW)


def test_new_research_suggests_its_branch(hub_root, capsys):
    assert mem.main(["--root", str(hub_root), "new", "research", "--slug", "branchy", "--title", "T",
                     "--question", "Q?", "--topics", "computing"]) == 0
    captured = capsys.readouterr()
    assert captured.out.strip().endswith("README.md")
    assert "git switch -c research/" in captured.err and captured.err.split("git switch -c ")[1].startswith("research/") and "-branchy" in captured.err.split("git switch -c ")[1].split()[0]


def test_new_refuses_author_split_across_slug_words(hub_root):
    with pytest.raises(mem.NewNoteError, match="repeats the first author"):
        mem.new_note(hub_root, "literature", slug="ethereum-org-merge", topics=["llm"], today=TODAY,
                     title="T", author="ethereumorg", year=2026, kind="web", level="beginner", url="https://x.org")


def test_cli_find_detail_levels(hub_root, capsys):
    def run(*argv):
        code = mem.main(["--root", str(hub_root), "find", "--type", "knowledge", *argv])
        return code, capsys.readouterr().out.splitlines()
    code, default = run()
    assert code == 0 and default[0].count("\t") == 1
    assert run("--detail", "titles") == (0, default)
    assert run("--detail", "paths")[1] == [line.split("\t")[0] for line in default]
    facts = run("--detail", "facts")[1]
    assert facts[0] == default[0] and facts[1].startswith("  ")
    snip = run("--detail", "snippet")[1]
    assert snip[:2] == facts[:2] and snip[2] == "  Self-attention can replace recurrence for sequence transduction."
    assert run("--limit", "1")[1] == default[:1]
    summary = run("--detail", "summary")[1]
    assert summary[2] == "  Self-attention can replace recurrence for sequence transduction."
    assert "## Claim" not in summary


def test_topics_tree_counts_match_find(hub_root, capsys):
    rows = mem.topic_tree(hub_root)
    assert rows and rows[0][0] == 0
    for depth, topic, count in rows:
        assert count == len(mem._matching_notes(hub_root, topic=topic))
    assert mem.main(["--root", str(hub_root), "topics"]) == 0
    assert capsys.readouterr().out.splitlines() == [f"{'  ' * d}{t}\t{c}" for d, t, c in rows]
    sub = mem.topic_tree(hub_root, rows[0][1])
    assert sub[0] == (0, rows[0][1], rows[0][2])
    assert mem.main(["--root", str(hub_root), "topics", "zzz-no-such-topic"]) == 1
