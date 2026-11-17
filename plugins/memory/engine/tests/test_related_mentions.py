import mem

from test_find_new import write_note

LIT = "literature/computing/2017-vaswani-attention.md"
KNOW = "knowledge/computing/attention-replaces-recurrence.md"
FRONT = "---\nclaim: {claim}\ntopics: [llm]\nconfidence: low\norigin: experience\nupdated: 2026-11-07\n---\n"


def add(root, name, claim, body):
    rel = f"knowledge/computing/{name}.md"
    write_note(root, rel, FRONT.format(claim=claim) + body)
    return rel


def run(root, capsys, path, *flags):
    code = mem.main(["--root", str(root), "related", path, *flags])
    captured = capsys.readouterr()
    return code, captured.out.splitlines(), captured.err.splitlines()


def test_title_phrase_without_a_link_is_a_mention_and_a_link_removes_it(hub_root, capsys):
    a = add(hub_root, "says-it", "Says it", "We read Attention Is All You Need closely.\n")
    add(hub_root, "links-it", "Links it",
        "Attention is all you need, see [paper](../../literature/computing/2017-vaswani-attention.md).\n")
    code, out, err = run(hub_root, capsys, LIT, "--unlinked-mentions")
    assert code == 0
    assert [line.split("\t")[:2] for line in out] == [["mentions", a]]
    assert err == ["mentions: 1"]


def test_author_surname_near_year_matches_case_sensitively(hub_root, capsys):
    near = add(hub_root, "near", "Near", "Vaswani et al. (2017) showed it.\n")
    add(hub_root, "far", "Far", "Vaswani wrote it. " + "x " * 30 + "2017.\n")
    add(hub_root, "lower", "Lower", "vaswani 2017.\n")
    _, out, _ = run(hub_root, capsys, LIT, "--unlinked-mentions")
    assert [line.split("\t")[1] for line in out] == [near]


def test_short_titles_never_match(hub_root, capsys):
    add(hub_root, "short", "Short title", "Short title again and short title.\n")
    _, out, _ = run(hub_root, capsys, "knowledge/computing/short.md", "--unlinked-mentions")
    assert out == []


def test_knowledge_claim_phrase_is_found_in_other_notes(hub_root, capsys):
    other = add(hub_root, "other", "Other", "Note: self-attention can replace RECURRENCE for sequence transduction.\n")
    _, out, _ = run(hub_root, capsys, KNOW, "--unlinked-mentions")
    assert [line.split("\t")[1] for line in out] == [other]


def test_default_output_gets_a_summary_line_on_stderr(hub_root, capsys):
    code, out, err = run(hub_root, capsys, LIT)
    assert code == 0
    assert len(err) == 1 and err[0].startswith("links-to: ") and " · linked-from: " in err[0] and " · similar: " in err[0]
    assert all(line.split("\t")[0] in mem.RELATIONS for line in out)


def test_link_labels_are_not_mentions_and_titles_need_four_words(hub_root, capsys):
    add(hub_root, "label", "Label", "See [Attention Is All You Need](../../literature/computing/other.md).\n")
    add(hub_root, "three", "Three", "Attention is all you need.\n")
    assert [m.rel for m in mem.unlinked_mentions(hub_root, LIT, mem.build_corpus(hub_root))
            if m.rel.endswith(("label.md", "three.md"))] == ["knowledge/computing/three.md"]
    add(hub_root, "tri", "Three word title", "x\n")
    assert mem._mention_pattern(next(n for n in mem.discover_notes(hub_root) if n.rel.endswith("tri.md"))) is None
