from pathlib import Path

import mem
from notes.note import Note
from notes.split_candidates import find_candidates
from syntheses.document import Section, Synthesis
from synthesize.run import topics_without_synthesis

FIVE = 5
TOPICS = {"root": {}, "child": {"parent": "root"}, "deep": {"parent": "child"}, "other": {}}


def note(i, **meta):
    rel = f"knowledge/test/{i}.md"
    return Note(
        "knowledge",
        Path(rel),
        rel,
        {"topics": ["child"], "part_of": "parent#part", **meta},
        "",
        1,
        "",
        None,
    )


def synthesis():
    return Synthesis(
        Path("parent.md"), "parent", topics=["root"], sections=[Section("part", "Part", "", [], 1)]
    )


def test_threshold_and_distinct_notes():
    notes = [note(i, topics=["child", "child"]) for i in range(5)]
    assert find_candidates([*notes[:4], notes[0]], [synthesis()], TOPICS) == []
    found = find_candidates(reversed(notes), [synthesis()], TOPICS)
    assert [(c.part, c.topic, c.notes) for c in found] == [
        ("parent#part", "child", tuple(n.rel for n in notes))
    ]


def test_excludes_invalid_attachments_and_topics():
    notes = [note(i) for i in range(4)]
    notes += [
        note("sup", superseded_by="x"),
        note("loose", part_of=None),
        note("missing", part_of="parent#missing"),
        note("other", topics=["other"]),
        note("unknown", topics=["unknown"]),
        note("declared", topics=["root"]),
    ]
    assert find_candidates(notes, [synthesis()], TOPICS) == []
    notes += [note("deep", topics=["deep", "child"])]
    assert [c.topic for c in find_candidates(notes, [synthesis()], TOPICS)] == ["child"]
    syn = synthesis()
    syn.topics.append("child")
    assert find_candidates([note(i) for i in range(5)], [syn], TOPICS) == []


def test_cli_split_block_does_not_confuse_crowded_parser(hub_root, capsys):
    (hub_root / "topics.yaml").write_text(
        "root: {}\nchild:\n  parent: root\nloose: {}\n", encoding="utf-8"
    )
    (hub_root / "syntheses").mkdir(exist_ok=True)
    (hub_root / "syntheses" / "parent.md").write_text(
        "---\ntitle: Parent\ntopics: [root]\ncreated: '2026-01-01'\nupdated: '2026-01-01'\n---\n\n## Summary\n\nSummary.\n\n## Part\n\nText.\n",
        encoding="utf-8",
    )
    folder = hub_root / "knowledge" / "test"
    folder.mkdir()
    for i in range(13):
        topic = "child" if i < FIVE else "loose"
        part = "part_of: parent#part\n" if i < FIVE else ""
        (folder / f"n-{i}.md").write_text(
            f"---\ntopics: [{topic}]\nclaim: Unique {i}\n{part}---\n\nText.\n", encoding="utf-8"
        )
    assert mem.main(["--root", str(hub_root), "curate", "--notes"]) == 0
    out = capsys.readouterr().out
    assert "synthesis split candidates\n  s:parent#part  child  5 notes\n" in out
    assert topics_without_synthesis(out) == ["loose"]
