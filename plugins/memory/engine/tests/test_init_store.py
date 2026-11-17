import mem

BODY = {
    "knowledge": "## Claim\n\nIt holds.\n\n## Evidence\n\n- Experience (anonymized): seen.\n\n## Applies when\n\nAlways.\n\n## Does not apply when\n\nNever.\n",
}


def test_a_new_store_takes_notes_and_passes_check(tmp_path, capsys):
    store = tmp_path / "store"
    assert mem.main(["init", str(store)]) == 0
    assert sorted(p.name for p in (store / "templates").iterdir()) == ["knowledge.md", "literature.md", "research.md"]
    body = tmp_path / "body.md"
    body.write_text(BODY["knowledge"], encoding="utf-8")
    root = ["--root", str(store)]
    assert mem.main([*root, "new", "knowledge", "--slug", "a-first-claim-is-recorded", "--claim", "A first claim is recorded.",
                     "--topics", "notes", "--confidence", "medium", "--level", "beginner", "--origin", "experience",
                     "--body-file", str(body)]) == 0
    lit = tmp_path / "lit.md"
    lit.write_text("## TL;DR\n\nA source.\n\n## What the source says\n\n- It says so.\n\n## Our interpretation\n\nWe agree.\n\n## Relevance\n\nHere.\n", encoding="utf-8")
    assert mem.main([*root, "new", "literature", "--title", "A paper", "--author", "Doe", "--year", "2024", "--kind", "paper",
                     "--level", "intermediate", "--url", "https://example.org/p.pdf", "--topics", "notes",
                     "--slug", "a-paper", "--body-file", str(lit)]) == 0
    capsys.readouterr()
    assert (store / "knowledge/notes/a-first-claim-is-recorded.md").is_file()
    assert mem.main([*root, "check"]) == 0
    assert capsys.readouterr().out == ""
    assert mem.main([*root, "search", "first"]) == 0
    assert "knowledge/notes/a-first-claim-is-recorded.md" in capsys.readouterr().out


def test_init_on_a_marked_store_changes_nothing(tmp_path):
    store = tmp_path / "store"
    assert mem.main(["init", str(store)]) == 0
    (store / "templates" / "knowledge.md").write_text("mine", encoding="utf-8")
    assert mem.main(["init", str(store)]) == 0
    assert (store / "templates" / "knowledge.md").read_text() == "mine"
