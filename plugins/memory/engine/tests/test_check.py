import re

import pytest

import mem


def has(problems, path, kw):
    return any(p.path == path and kw in p.message for p in problems)


def lit(root):
    return root / "literature" / "computing" / "2017-vaswani-attention.md"


def know(root):
    return root / "knowledge" / "computing" / "attention-replaces-recurrence.md"


def edit(path, old, new):
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def test_valid_hub_has_no_problems(hub_root):
    assert mem.check(hub_root) == []


def test_bad_literature_name(hub_root):
    lit(hub_root).rename(hub_root / "literature" / "computing" / "2017-Vaswani-attention.md")
    assert has(mem.check(hub_root), "literature/computing/2017-Vaswani-attention.md", "invalid name")


def test_knowledge_name_with_date_prefix(hub_root):
    know(hub_root).rename(hub_root / "knowledge" / "computing" / "2017-attention.md")
    assert has(mem.check(hub_root), "knowledge/computing/2017-attention.md", "invalid name")


def test_research_month_out_of_range(hub_root):
    (hub_root / "research" / "2026-11-llm-eval-methods").rename(
        hub_root / "research" / "2026-13-llm-eval-methods"
    )
    assert has(mem.check(hub_root), "research/2026-13-llm-eval-methods", "invalid name")


def test_stray_file_in_research(hub_root):
    (hub_root / "research" / "notes.md").write_text("x\n", encoding="utf-8")
    assert has(mem.check(hub_root), "research/notes.md", "not allowed here")


def test_frontmatter_not_mapping(hub_root):
    lit(hub_root).write_text("---\n- a\n---\n## TL;DR\n", encoding="utf-8")
    assert has(mem.check(hub_root), "literature/computing/2017-vaswani-attention.md", "frontmatter")


def test_missing_and_unknown_field(hub_root):
    edit(lit(hub_root), "kind: paper\n", "doi: x\n")
    problems = mem.check(hub_root)
    path = "literature/computing/2017-vaswani-attention.md"
    assert has(problems, path, "missing field") and has(problems, path, "unknown field")


def test_invalid_enum_and_url(hub_root):
    edit(lit(hub_root), "kind: paper", "kind: blog")
    edit(lit(hub_root), "url: https://arxiv.org/abs/1706.03762", "url: ftp://x")
    bad = [p for p in mem.check(hub_root) if "invalid value" in p.message]
    assert len(bad) == 2


def test_heading_order(hub_root):
    text = lit(hub_root).read_text(encoding="utf-8")
    text = text.replace("## TL;DR", "## @@").replace("## Relevance", "## TL;DR").replace("## @@", "## Relevance")
    lit(hub_root).write_text(text, encoding="utf-8")
    assert has(mem.check(hub_root), "literature/computing/2017-vaswani-attention.md", "missing heading")


def test_year_and_author_mismatch(hub_root):
    edit(lit(hub_root), "year: 2017", "year: 2018")
    edit(lit(hub_root), "authors: [Vaswani, Shazeer]", "authors: [Shazeer]")
    problems = mem.check(hub_root)
    path = "literature/computing/2017-vaswani-attention.md"
    assert has(problems, path, "year mismatch") and has(problems, path, "author mismatch")


def test_started_mismatch(hub_root):
    readme = hub_root / "research" / "2026-11-llm-eval-methods" / "README.md"
    edit(readme, 'started: "2026-11"', 'started: "2026-10"')
    assert has(mem.check(hub_root), "research/2026-11-llm-eval-methods/README.md", "started mismatch")


def test_unknown_topic_and_missing_ancestor(hub_root):
    edit(know(hub_root), "topics: [llm, deep-learning, ml, computing]", "topics: [llm, deep-learning, computing, quantum]")
    problems = mem.check(hub_root)
    path = "knowledge/computing/attention-replaces-recurrence.md"
    assert has(problems, path, "unknown topic") and has(problems, path, "missing ancestor")


def test_empty_topics_list(hub_root):
    edit(know(hub_root), "topics: [llm, deep-learning, ml, computing]", "topics: []")
    assert has(mem.check(hub_root), "knowledge/computing/attention-replaces-recurrence.md", "at least one topic")


def test_topic_on_is_a_string(hub_root):
    with (hub_root / "topics.yaml").open("a", encoding="utf-8") as f:
        f.write("on: {}\n")
    edit(know(hub_root), "topics: [llm, deep-learning, ml, computing]", "topics: [llm, deep-learning, ml, computing, on]")
    assert not any("unknown topic" in p.message for p in mem.check(hub_root))


def test_topics_file_missing(hub_root):
    (hub_root / "topics.yaml").unlink()
    problems = mem.check(hub_root)
    mentioning = [p for p in problems if "topics.yaml" in p.message or p.path == "topics.yaml"]
    assert len(mentioning) == 1
    assert (mentioning[0].path, mentioning[0].line) == ("topics.yaml", 1)
    assert "topics file" in mentioning[0].message
    assert not any("unknown topic" in p.message for p in problems)


def test_placeholder_reported(hub_root):
    with know(hub_root).open("a", encoding="utf-8") as f:
        f.write("\nTODO(hub): fill me\n")
    assert has(mem.check(hub_root), "knowledge/computing/attention-replaces-recurrence.md", "placeholder")


def test_hidden_files_ignored(hub_root):
    (hub_root / "literature" / "computing" / ".2017-vaswani-attention.md.swp").write_text("x", encoding="utf-8")
    (hub_root / "literature" / ".cache").mkdir()
    (hub_root / "research" / ".tmp").mkdir()
    assert mem.check(hub_root) == []


def test_topics_unknown_parent_and_cycle(hub_root):
    path = hub_root / "topics.yaml"
    original = path.read_text(encoding="utf-8")
    path.write_text(original + "orphan: {parent: nope}\n", encoding="utf-8")
    assert has(mem.check(hub_root), "topics.yaml", "unknown parent")
    path.write_text(original + "a: {parent: b}\nb: {parent: a}\n", encoding="utf-8")
    assert has(mem.check(hub_root), "topics.yaml", "cycle")


def test_topics_non_string_parent_and_unknown_field(hub_root):
    with (hub_root / "topics.yaml").open("a", encoding="utf-8") as f:
        f.write("a: {parent: [x]}\nb: {color: red}\n")
    problems = [p for p in mem.check(hub_root) if p.path == "topics.yaml"]
    assert len(problems) == 2 and all("topics file entry" in p.message for p in problems)


def test_subfolder_in_literature(hub_root):
    (hub_root / "literature" / "sub").mkdir()
    (hub_root / "literature" / "sub" / "x.md").write_text("x\n", encoding="utf-8")
    (hub_root / "literature" / "paper.pdf").write_bytes(b"%PDF")
    bad = [p for p in mem.check(hub_root) if "not allowed here" in p.message]
    assert sorted(p.path for p in bad) == ["literature/paper.pdf", "literature/sub"]


def test_invalid_utf8_note_is_reported(hub_root):
    (hub_root / "literature" / "computing" / "2018-bad-utf8.md").write_bytes(b"\xff")
    assert has(mem.check(hub_root), "literature/computing/2018-bad-utf8.md", "frontmatter")


def test_messages_end_with_a_fix(hub_root):
    (hub_root / "research" / "notes.md").write_text("x\n", encoding="utf-8")
    (hub_root / "topics.yaml").write_text("a: {parent: b}\nb: {parent: a}\n", encoding="utf-8")
    for p in mem.check(hub_root):
        assert re.search(r": \S", p.message), p


def test_cli_check_exit_codes(hub_root, capsys):
    assert mem.main(["--root", str(hub_root), "check"]) == 0
    lit(hub_root).rename(hub_root / "literature" / "computing" / "2017-Vaswani-attention.md")
    assert mem.main(["--root", str(hub_root), "check"]) == 1
    assert "literature/computing/2017-Vaswani-attention.md:1: invalid name" in capsys.readouterr().out


def test_research_folder_without_readme(hub_root):
    (hub_root / "research" / "2026-11-llm-eval-methods" / "README.md").unlink()
    (hub_root / "research" / ".hidden").mkdir()
    problems = mem.check(hub_root)
    assert has(problems, "research/2026-11-llm-eval-methods", "missing readme")
    assert not any(p.path.startswith("research/.hidden") for p in problems)


def test_research_folder_holding_only_local_files_needs_no_readme(hub_root):
    folder = hub_root / "research" / "2026-11-local-only"
    for sub in ("data/raw", "code/.venv/lib", "code/__pycache__", "code/tests"):
        (folder / sub).mkdir(parents=True)
    (folder / "data" / "raw" / "ticks.csv").write_text("x")
    (folder / "code" / ".venv" / "lib" / "m.py").write_text("x")
    (folder / "code" / "__pycache__" / "m.pyc").write_text("x")
    assert not any(p.path.startswith("research/2026-11-local-only") for p in mem.check(hub_root))
    (folder / "data" / "raw" / "big.bin").write_bytes(b"0" * (mem.MAX_FILE_BYTES + 1))
    assert not any(p.path.startswith("research/2026-11-local-only") for p in mem.check(hub_root))
    (folder / "code" / "run.py").write_text("x")
    assert has(mem.check(hub_root), "research/2026-11-local-only", "missing readme")


@pytest.mark.parametrize("committable", [".gitignore", "code/.env", "code/data/prices.csv"])
def test_research_folder_with_a_file_git_would_store_needs_a_readme(hub_root, committable):
    folder = hub_root / "research" / "2026-11-local-only"
    (folder / committable).parent.mkdir(parents=True, exist_ok=True)
    (folder / committable).write_text("x")
    assert has(mem.check(hub_root), "research/2026-11-local-only", "missing readme")


def test_wrong_domain(hub_root):
    target = hub_root / "knowledge" / "biology"
    target.mkdir()
    know(hub_root).rename(target / "attention-replaces-recurrence.md")
    problems = mem.check(hub_root)
    wrong = [p for p in problems if "wrong domain" in p.message]
    assert [p.path for p in wrong] == ["knowledge/biology/attention-replaces-recurrence.md"]
    assert wrong[0].message.endswith("move to knowledge/computing/")


def test_note_spanning_roots_may_live_under_any_root(hub_root):
    edit(know(hub_root), "topics: [llm, deep-learning, ml, computing]",
         "topics: [llm, deep-learning, ml, computing, biology]")
    assert not any("wrong domain" in p.message for p in mem.check(hub_root))
    target = hub_root / "knowledge" / "biology"
    target.mkdir()
    know(hub_root).rename(target / "attention-replaces-recurrence.md")
    assert not any("wrong domain" in p.message for p in mem.check(hub_root))


def test_unknown_domain_folder(hub_root):
    (hub_root / "literature" / "misc").mkdir()
    (hub_root / "knowledge" / "ml").mkdir()  # a topic, but not a root topic
    bad = [p for p in mem.check(hub_root) if "not allowed here" in p.message]
    assert sorted(p.path for p in bad) == ["knowledge/ml", "literature/misc"]


def test_note_at_top_level_is_not_allowed(hub_root):
    (hub_root / "knowledge" / "loose.md").write_text("x\n", encoding="utf-8")
    assert has(mem.check(hub_root), "knowledge/loose.md", "not allowed here")


def test_note_in_subfolder_of_domain(hub_root):
    sub = hub_root / "knowledge" / "computing" / "sub"
    sub.mkdir()
    (sub / "x.md").write_text("x\n", encoding="utf-8")
    (hub_root / "knowledge" / "computing" / "data.csv").write_text("x\n", encoding="utf-8")
    bad = [p for p in mem.check(hub_root) if "not allowed here" in p.message]
    assert sorted(p.path for p in bad) == ["knowledge/computing/data.csv", "knowledge/computing/sub"]


def _rename_know(root, stem):
    new = root / "knowledge" / "computing" / f"{stem}.md"
    know(root).rename(new)
    return new.relative_to(root).as_posix()


def test_instruction_name_first_token(hub_root):
    rel = _rename_know(hub_root, "use-attention-instead-of-recurrence")
    problems = mem.check(hub_root)
    assert has(problems, rel, 'reads as an instruction ("use-..."): rename to a declarative claim')


def test_instruction_name_after_so_and_then(hub_root):
    rel = _rename_know(hub_root, "context-is-finite-so-curate-it")
    assert has(mem.check(hub_root), rel, 'reads as an instruction ("curate-..."')
    (hub_root / rel).rename(know(hub_root))
    rel = _rename_know(hub_root, "retries-fail-then-avoid-them")
    assert has(mem.check(hub_root), rel, 'reads as an instruction ("avoid-..."')


def test_declarative_name_with_listed_verb_elsewhere_passes(hub_root):
    _rename_know(hub_root, "retries-need-idempotency-keys-to-avoid-duplicates")
    assert not any("instruction" in p.message for p in mem.check(hub_root))


def test_author_repeated_in_literature_filename(hub_root):
    new = hub_root / "literature" / "computing" / "2017-vaswani-vaswani-attention.md"
    lit(hub_root).rename(new)
    assert has(mem.check(hub_root), new.relative_to(hub_root).as_posix(), "author repeated in filename")
    new2 = new.rename(hub_root / "literature" / "computing" / "2017-vaswani-vaswanis-attention.md")
    assert not any("repeated" in p.message for p in mem.check(hub_root))
    assert new2.exists()


def test_year_repeated_in_literature_filename(hub_root):
    new = hub_root / "literature" / "computing" / "2017-vaswani-2017-attention.md"
    lit(hub_root).rename(new)
    assert has(mem.check(hub_root), new.relative_to(hub_root).as_posix(), "year repeated in filename")
    other = new.rename(hub_root / "literature" / "computing" / "2017-vaswani-1000-genomes.md")
    assert not any(p.path == other.relative_to(hub_root).as_posix() and "repeated" in p.message
                   for p in mem.check(hub_root))


def test_level_is_required_and_validated(hub_root):
    path = "knowledge/computing/attention-replaces-recurrence.md"
    edit(know(hub_root), "level: intermediate\n", "")
    edit(lit(hub_root), "level: advanced", "level: guru")
    problems = mem.check(hub_root)
    assert has(problems, path, "level")
    bad = [p for p in problems if "invalid value for 'level'" in p.message]
    assert len(bad) == 1 and "basic, beginner, intermediate, advanced, expert, niche" in bad[0].message


def test_knowledge_name_longer_than_limit_is_reported(hub_root):
    long_stem = "a-" + "b" * (mem.MAX_KNOWLEDGE_NAME - 1)
    know(hub_root).rename(know(hub_root).with_name(long_stem + ".md"))
    assert has(mem.check(hub_root), f"knowledge/computing/{long_stem}.md", "knowledge name too long")


def test_author_split_across_slug_tokens_is_repeated(hub_root):
    new = hub_root / "literature" / "computing" / "2017-vaswani-vas-wani-attention.md"
    lit(hub_root).rename(new)
    assert has(mem.check(hub_root), new.relative_to(hub_root).as_posix(), "author repeated in filename")


def test_experiment_needs_baseline_heading(hub_root):
    inv = hub_root / "research" / "2026-11-llm-eval-methods"
    assert mem.check(hub_root) == []  # no code/ or results/: not required
    (inv / "results").mkdir()
    assert mem.check(hub_root) == []  # an empty folder is not stored by git: not required either
    (inv / "results" / "r.csv").write_text("a\n1\n", encoding="utf-8")
    assert has(mem.check(hub_root), "research/2026-11-llm-eval-methods/README.md", "Baseline and contribution")
    edit(inv / "README.md", "## Contents", "## Baseline and contribution\n\nX.\n\n## Contents")
    assert not has(mem.check(hub_root), "research/2026-11-llm-eval-methods/README.md", "Baseline and contribution")
