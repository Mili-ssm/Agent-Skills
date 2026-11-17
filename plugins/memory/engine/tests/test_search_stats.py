import pytest

import mem

from test_find_new import write_note


def knowledge(claim, body="Body.", topics="[computing]"):
    return (f"---\nclaim: {claim}\ntopics: {topics}\nconfidence: low\norigin: experience\n"
            f"updated: 2026-11-07\n---\n\n## Claim\n\n{body}\n")


def add(root, name, claim, body="Body.", topics="[computing]"):
    write_note(root, f"knowledge/computing/{name}.md", knowledge(claim, body, topics))
    return f"knowledge/computing/{name}.md"


def paths(result):
    return [rel for rel, _, _ in result]


def test_stats_counts_on_fixture(hub_root, capsys):
    assert mem.main(["--root", str(hub_root), "stats"]) == 0
    out = capsys.readouterr().out.splitlines()
    values = dict(line.split(": ") for line in out)
    assert out[1:4] == ["literature: 1", "knowledge: 1", "research: 1"]
    assert values["literature/computing"] == "1"
    assert values["knowledge/computing"] == "1"
    assert values["topics"] == "6"
    assert int(values["tokens"]) == int(values["characters"]) // 4 > 0
    assert int(values["mem.py lines"]) > 1000


def test_search_ranks_title_above_body_mention(hub_root):
    body_only = add(hub_root, "body-only", "Something else entirely", "Zebra appears once here.")
    in_claim = add(hub_root, "in-claim", "Zebra crossings are safe", "Other text.")
    result = mem.search(hub_root, "zebra")
    assert paths(result) == [in_claim, body_only]
    assert result[0][1] > result[1][1] > 0


def test_search_rarer_term_scores_higher(hub_root):
    common = add(hub_root, "common", "Common words", "alpha alpha alpha")
    rare = add(hub_root, "rare", "Rare words", "omega")
    add(hub_root, "other", "Other", "alpha")
    add(hub_root, "another", "Another", "alpha")
    assert paths(mem.search(hub_root, "alpha omega"))[0] == rare
    assert common in paths(mem.search(hub_root, "alpha omega"))


def test_search_filters_apply_before_scoring(hub_root):
    add(hub_root, "k", "Attention matters in knowledge")
    assert paths(mem.search(hub_root, "attention", type="literature")) == [
        "literature/computing/2017-vaswani-attention.md"]
    assert paths(mem.search(hub_root, "attention", confidence="medium")) == [
        "knowledge/computing/attention-replaces-recurrence.md"]
    assert paths(mem.search(hub_root, "attention", topic="llm", type="research")) == []


def test_search_limit(hub_root):
    for i in range(4):
        add(hub_root, f"n{i}", f"Quokka {i}")
    assert len(mem.search(hub_root, "quokka", limit=2)) == 2


def test_search_accents_and_authors(hub_root):
    write_note(hub_root, "literature/computing/2024-garcia-x.md",
               '---\ntitle: T\nauthors: [García]\nyear: 2024\nkind: paper\nurl: https://x.org\n'
               'topics: [computing]\nadded: 2026-11-07\n---\n')
    assert paths(mem.search(hub_root, "GARCÍA")) == ["literature/computing/2024-garcia-x.md"]
    assert paths(mem.search(hub_root, "garcia"))[0] == "literature/computing/2024-garcia-x.md"


def test_search_query_terms_are_deduplicated(hub_root):
    assert mem.search(hub_root, "attention") == mem.search(hub_root, "attention attention Attention")


def test_search_skips_unparsable_note_with_warning(hub_root, capsys):
    write_note(hub_root, "knowledge/computing/bad.md", "no frontmatter attention\n")
    assert "bad.md" not in " ".join(paths(mem.search(hub_root, "attention")))
    assert "skipping knowledge/computing/bad.md" in capsys.readouterr().err


def test_cli_search_output_and_no_match(hub_root, capsys):
    assert mem.main(["--root", str(hub_root), "search", "vaswani"]) == 0
    row = capsys.readouterr().out.splitlines()[0].split("\t")
    assert row[0] == "literature/computing/2017-vaswani-attention.md"
    assert len(row[1].split(".")[1]) == 2
    assert row[2] == "Attention Is All You Need"
    assert mem.main(["--root", str(hub_root), "search", "nonexistentword"]) == 0
    captured = capsys.readouterr()
    assert captured.out == "" and "no matches" in captured.err


def test_cli_search_rejects_empty_query_and_bad_limit(hub_root):
    for argv in (["search", "  !! "], ["search", "x", "--limit", "0"]):
        with pytest.raises(SystemExit) as exc:
            mem.main(["--root", str(hub_root), *argv])
        assert exc.value.code == 2


KNOWLEDGE_FRONTMATTER = ("---\nclaim: Needle claim\ntopics: [computing]\nconfidence: low\nlevel: basic\n"
                         "origin: experience\nupdated: 2026-11-07\n---\n")


def test_cli_search_detail_levels(hub_root, capsys):
    run = lambda d: (mem.main(["--root", str(hub_root), "search", "attention", "--detail", d]),
                     capsys.readouterr().out.splitlines())
    code, default = mem.main(["--root", str(hub_root), "search", "attention"]), capsys.readouterr().out.splitlines()
    assert run("titles") == (0, default)  # default output is unchanged
    assert run("paths")[1] == [line.split("\t")[0] for line in default]
    facts = run("facts")[1]
    assert facts[0] == default[0] and facts[1].startswith("  ")
    snip = run("snippet")[1]
    assert snip[:2] == facts[:2] and "attention" in snip[2].lower()


def test_cli_search_detail_summary_prints_lead_section_without_heading(hub_root, capsys):
    assert mem.main(["--root", str(hub_root), "search", "recurrence", "--type", "knowledge",
                     "--detail", "summary"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert "  Self-attention can replace recurrence for sequence transduction." in lines
    assert not any("## Claim" in line or "(no section" in line for line in lines)


def test_snippet_collapses_whitespace_and_truncates(hub_root):
    rel = "knowledge/computing/long-line.md"
    write_note(hub_root, rel, KNOWLEDGE_FRONTMATTER + "\n## Evidence\n\n" + "zzzneedle\tword " * 60 + "\n")
    note = next(n for n in mem.build_corpus(hub_root).notes if n.rel == rel)
    text = mem.snippet(note, ["zzzneedle"])
    assert len(text) == 200 and text.endswith("…") and "\t" not in text and "  " not in text


def test_cli_search_snippet_no_match(hub_root, capsys):
    assert mem.main(["--root", str(hub_root), "search", "zzzunknown", "--detail", "snippet"]) == 0
    captured = capsys.readouterr()
    assert captured.out == "" and "no matches" in captured.err


def test_cli_search_detail_rejects_empty_query(hub_root):
    with pytest.raises(SystemExit) as exc:
        mem.main(["--root", str(hub_root), "search", "  !! ", "--detail", "snippet"])
    assert exc.value.code == 2


EVAL = """# Search eval

| Query | Expected notes |
| --- | --- |
| vaswani attention | [a](../literature/computing/2017-vaswani-attention.md) |
| zzzunknown | [k](../knowledge/computing/attention-replaces-recurrence.md) |
"""


def test_search_eval_hit_and_miss(hub_root, capsys):
    write_note(hub_root, "docs/search-eval.md", EVAL)
    assert mem.main(["--root", str(hub_root), "search-eval"]) == 1   # recall 0.50 is below the trigger
    captured = capsys.readouterr()
    assert captured.out.splitlines() == ['docs/search-eval.md:6: missed knowledge/computing/attention-replaces-recurrence.md '
                                         'for "zzzunknown"', "recall@10: 0.50 (1/2)", "MRR@10: 0.500"]
    assert "below the revisit trigger" in captured.err
    assert mem.main(["--root", str(hub_root), "search-eval", "--min", "0.9"]) == 1
    assert mem.main(["--root", str(hub_root), "search-eval", "--min", "0.5"]) == 0
    assert "below the revisit trigger" not in capsys.readouterr().err


def test_search_eval_empty_table_is_not_a_breach(hub_root, capsys):
    write_note(hub_root, "docs/search-eval.md", "| Query | Expected notes |\n| --- | --- |\n")
    assert mem.main(["--root", str(hub_root), "search-eval"]) == 0


def test_search_eval_without_file_is_a_noop(hub_root, capsys):
    assert mem.main(["--root", str(hub_root), "search-eval"]) == 0
    captured = capsys.readouterr()
    assert captured.out == "" and "search-eval.md" in captured.err


def test_search_eval_reads_only_the_query_table(hub_root, capsys):
    other = "\n| Cause | Meaning |\n| --- | --- |\n| zzzother | [k](../knowledge/computing/attention-replaces-recurrence.md) |\n"
    write_note(hub_root, "docs/search-eval.md", other + "\n" + EVAL)
    assert mem.main(["--root", str(hub_root), "search-eval"]) == 1
    assert capsys.readouterr().out.splitlines()[-2:] == ["recall@10: 0.50 (1/2)", "MRR@10: 0.500"]


def test_orphans_unlinked_index_only_and_linked(hub_root, capsys):
    linked = add(hub_root, "linked", "Linked note")
    lonely = add(hub_root, "lonely", "Lonely note")
    write_note(hub_root, "knowledge/computing/linker.md",
               knowledge("Linker", "See [x](linked.md) and `[no](lonely.md)`."))
    # the index READMEs list every note but do not count
    assert mem.main(["--root", str(hub_root), "index"]) == 0
    capsys.readouterr()
    orphans = mem.orphan_notes(hub_root)
    assert lonely in orphans and linked not in orphans
    assert "knowledge/computing/linker.md" in orphans
    # fixture: the knowledge and research notes are linked from nowhere but index READMEs
    assert orphans == ["knowledge/computing/attention-replaces-recurrence.md",
                       "knowledge/computing/linker.md", "knowledge/computing/lonely.md",
                       "research/2026-11-llm-eval-methods/README.md"]
    assert mem.main(["--root", str(hub_root), "stats", "--orphans"]) == 0
    assert capsys.readouterr().out.splitlines() == orphans
    assert mem.main(["--root", str(hub_root), "stats"]) == 0
    assert f"orphans: {len(orphans)}" in capsys.readouterr().out.splitlines()


def test_stats_orphans_prints_nothing_when_none(hub_root, capsys, monkeypatch):
    monkeypatch.setattr(mem, "orphan_notes", lambda root: [])
    assert mem.main(["--root", str(hub_root), "stats", "--orphans"]) == 0
    assert capsys.readouterr().out == ""


def test_title_match_outranks_more_frequent_body_match(hub_root):
    write_note(hub_root, "knowledge/computing/zebra-in-title.md",
               "---\nclaim: Zebra stripes\ntopics: [computing]\nconfidence: low\nlevel: basic\norigin: experience\n"
               "updated: 2026-11-07\n---\n## Claim\n\nx\n\n## Evidence\n\nx\n\n## Applies when\n\nx\n\n## Does not apply when\n\nx\n")
    write_note(hub_root, "knowledge/computing/zebra-in-body.md",
               "---\nclaim: Something else\ntopics: [computing]\nconfidence: low\nlevel: basic\norigin: experience\n"
               "updated: 2026-11-07\n---\n## Claim\n\nzebra zebra\n\n## Evidence\n\nx\n\n## Applies when\n\nx\n\n## Does not apply when\n\nx\n")
    ranked = [r[0] for r in mem.search(hub_root, "zebra")]
    assert ranked[:2] == ["knowledge/computing/zebra-in-title.md", "knowledge/computing/zebra-in-body.md"]


def test_search_survives_a_note_with_an_empty_body(hub_root):
    write_note(hub_root, "knowledge/computing/empty-body.md",
               "---\nclaim: Empty body claim\ntopics: [computing]\nconfidence: low\nlevel: basic\norigin: experience\n"
               "updated: 2026-11-07\n---\n")
    assert mem.search(hub_root, "empty body claim")[0][0] == "knowledge/computing/empty-body.md"


def test_rank_matches_search(hub_root):
    corpus = mem.build_corpus(hub_root)
    ranked = [(n.rel, s, mem._title(n)) for n, s in mem.rank(corpus, "attention", limit=5)]
    assert ranked == mem.search(hub_root, "attention", limit=5)


def test_search_eval_reads_notes_once(hub_root, monkeypatch):
    write_note(hub_root, "docs/search-eval.md", EVAL)
    calls = []
    real = mem.build_corpus
    monkeypatch.setattr(mem, "build_corpus", lambda *a, **k: calls.append(1) or real(*a, **k))
    mem.search_eval(hub_root)
    assert len(calls) == 1


def test_related_groups(hub_root):
    a, b = "knowledge/computing/attention-replaces-recurrence.md", "knowledge/computing/zzz-linker.md"
    write_note(hub_root, b, KNOWLEDGE_FRONTMATTER + "\n## Evidence\n\n- [a](attention-replaces-recurrence.md): x\n")
    groups = mem.related(hub_root, a)
    assert [n.rel for n in groups["linked-from"]] == [b]
    assert [n.rel for n in mem.related(hub_root, b)["links-to"]] == [a]
    assert a not in [n.rel for n in groups["similar"]] and b not in [n.rel for n in groups["similar"]]


def test_related_without_links_prints_only_similar_rows(hub_root, capsys):
    a = "knowledge/computing/zzz-isolated.md"
    write_note(hub_root, a, KNOWLEDGE_FRONTMATTER + "\n## Claim\n\nAttention needle.\n")
    groups = mem.related(hub_root, a)
    assert groups["links-to"] == [] and groups["linked-from"] == []
    assert mem.main(["--root", str(hub_root), "related", a]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines and all(line.startswith("similar\t") for line in lines)


def test_cli_related_output_and_errors(hub_root, capsys):
    a = "knowledge/computing/attention-replaces-recurrence.md"
    assert mem.main(["--root", str(hub_root), "related", a, "--limit", "2"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines and all(line.split("\t")[0] in mem.RELATIONS for line in lines)
    assert sum(line.startswith("similar\t") for line in lines) <= 2
    assert mem.main(["--root", str(hub_root), "related", "knowledge/README.md"]) == 1
    assert capsys.readouterr().err == "mem: not a note: knowledge/README.md\n"
    assert mem.main(["--root", str(hub_root), "related", "knowledge/missing.md"]) == 1
    assert capsys.readouterr().err == "mem: not a note: knowledge/missing.md\n"


def test_cli_search_snippet_prefers_informative_term_over_function_words(hub_root, capsys):
    for i in range(8):  # make the function words common, as in a real hub
        add(hub_root, f"zzz-common-{i}", f"Common {i}", "this is a note for the record")
    add(hub_root, "zzz-idf-snippet", "Zzzidfword note", "the cat is on a mat for the day\n\nzzzbmtwentyfive ranking explained")
    assert mem.main(["--root", str(hub_root), "search", "is a zzzbmtwentyfive for the", "--detail", "snippet"]) == 0
    lines = capsys.readouterr().out.splitlines()
    hit = lines.index(next(l for l in lines if l.startswith("knowledge/computing/zzz-idf-snippet.md")))
    assert lines[hit + 2] == "  zzzbmtwentyfive ranking explained"
    assert "  the cat is on a mat for the day" not in lines


def test_snippet_never_picks_a_fenced_line(hub_root):
    rel = add(hub_root, "zzz-fenced", "Zzzfenced note",
              "intro line\n\n```\nzzzfencedword inside code\n```\n\nplain closing line")
    note = next(n for n in mem.build_corpus(hub_root).notes if n.rel == rel)
    text = mem.snippet(note, ["zzzfencedword"])
    assert text and "zzzfencedword" not in text and "```" not in text


def test_term_idf_matches_rank_weights(hub_root):
    corpus = mem.build_corpus(hub_root)
    idf = mem.term_idf(corpus, ["attention", "zzznowhere"])
    assert idf["zzznowhere"] > idf["attention"] > 0


def test_related_raises_value_error_for_a_non_note(hub_root):
    with pytest.raises(ValueError, match="not a note: knowledge/README.md"):
        mem.related(hub_root, "knowledge/README.md")


def test_cli_related_builds_the_corpus_once(hub_root, monkeypatch):
    calls = []
    real = mem.build_corpus
    monkeypatch.setattr(mem, "build_corpus", lambda *a, **k: calls.append(1) or real(*a, **k))
    assert mem.main(["--root", str(hub_root), "related", "knowledge/computing/attention-replaces-recurrence.md"]) == 0
    assert len(calls) == 1


def test_search_eval_breach_on_mrr_alone(hub_root, capsys):
    for i in range(3):
        add(hub_root, f"zzz-mrr-{i}", f"Zzzmrrword zzzmrrword zzzmrrword {i}", "zzzmrrword " * 3)
    weak = add(hub_root, "zzz-mrr-weak", "Weak note", "zzzmrrword " + "filler " * 40)
    write_note(hub_root, "docs/search-eval.md",
               f"| Query | Expected notes |\n| --- | --- |\n| zzzmrrword | [w](../{weak}) |\n")
    assert mem.main(["--root", str(hub_root), "search-eval"]) == 1
    captured = capsys.readouterr()
    assert "recall@10: 1.00 (1/1)" in captured.out and "below the revisit trigger" in captured.err
    mrr = float(captured.out.split("MRR@10: ")[1])
    assert mrr < mem.MRR_TRIGGER
