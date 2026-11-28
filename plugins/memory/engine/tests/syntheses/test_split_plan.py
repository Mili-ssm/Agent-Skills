from dataclasses import replace
from datetime import date

import pytest
from commands.split_plan import SplitProposal, candidate_input, prepare_split
from notes.note import split_frontmatter
from syntheses import units

FIVE = 5
SIX = 6


@pytest.fixture
def world(hub_root):
    root = hub_root
    (root / "topics.yaml").write_text("root: {}\nchild:\n  parent: root\nother:\n  parent: root\n")
    folder = root / "knowledge" / "test"
    folder.mkdir()
    syn = root / "syntheses" / "parent.md"
    syn.parent.mkdir(exist_ok=True)
    refs = [f"[n{i}](../knowledge/test/n{i}.md)" for i in range(5)]
    body = "There were 42 cases. " + " ".join(refs) + "\n\nSources: " + ", ".join(refs)
    syn.write_text(
        "---\ntitle: Parent\ntopics: [root]\ncreated: '2026-01-01'\nupdated: '2026-01-01'\n---\n\n## Summary\n\nSummary.\n\n## Before\n\nBefore.\n\n## Part\n\n"
        + body
        + "\n\n## After\n\nAfter.\n"
    )
    for i in range(7):
        topic = "child" if i < FIVE else "root"
        (folder / f"n{i}.md").write_text(
            f"---\ntopics: [{topic}]\nclaim: Claim {i}\npart_of: parent#part\npart_of_hash: {units.fingerprint(body) if i < SIX else 'stale'}\n---\n\nNote.\n"
        )
    return root, body, refs


def proposal(root, body):
    data = candidate_input(root, "s:parent#part", "child")
    fields = data["proposal"]
    assert isinstance(fields, dict)
    return SplitProposal(**{
        **fields,
        "parent_text": "General introduction.\n\nSources: [n5](../knowledge/test/n5.md)",
        "child_heading": "Details",
        "child_text": body,
    })


def test_new_child_and_no_writes(world):
    root, body, _ = world
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    plan = prepare_split(root, proposal(root, body), date(2026, 1, 2), {})
    assert plan.destination == "child#details"
    assert len(plan.moves) == FIVE and not plan.conflicts
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before
    parent_bytes = plan.changes[root / "syntheses/parent.md"][1]
    assert parent_bytes is not None
    parent = parent_bytes.decode()
    assert parent.index("## Before") < parent.index("## Part") < parent.index("## After")
    assert "(child.md#details)" in parent and "(parent.md#part)" in plan.child_text
    for rel in plan.moves:
        note_bytes = plan.changes[root / rel][1]
        assert note_bytes is not None
        meta = split_frontmatter(note_bytes.decode())[0]
        assert meta["part_of"] == "child#details" and meta["claim"].startswith("Claim ")
    current_bytes = plan.changes[root / "knowledge/test/n5.md"][1]
    assert current_bytes is not None
    current = split_frontmatter(current_bytes.decode())[0]
    assert units.is_current(current["part_of_hash"], plan.parent_text, "../knowledge/test/n5.md")
    assert root / "knowledge/test/n6.md" not in plan.changes


def test_snapshot_rejects_new_eligible_note(world):
    root, body, _ = world
    p = proposal(root, body)
    note = root / "knowledge/test/n5.md"
    note.write_text(note.read_text().replace("[root]", "[child]"))
    with pytest.raises(ValueError, match="snapshot"):
        prepare_split(root, p, date.today(), {})


def test_overlap_is_visible(world):
    root, body, _ = world
    for i in range(5):
        p = root / f"knowledge/test/n{i}.md"
        p.write_text(p.read_text().replace("[child]", "[child, other]"))
    p = proposal(root, body)
    assert candidate_input(root, p.part, p.topic)["conflicts"] == ["other"]
    assert prepare_split(root, p, date.today(), {}).conflicts == ("other",)


def test_refuses_loss_collision_and_unsafe_topic(world):
    root, body, _ = world
    p = proposal(root, body)
    with pytest.raises(ValueError, match="missing"):
        prepare_split(root, replace(p, child_text="Nothing remains."), date.today(), {})
    with pytest.raises(ValueError):
        candidate_input(root, p.part, "../escape")
    child = root / "syntheses/child.md"
    child.write_text(
        "---\ntitle: Child\ntopics: [child]\ncreated: '2026-01-01'\nupdated: '2026-01-01'\n---\n\n## Summary\n\nSummary.\n\n## Details\n\nExisting.\n"
    )
    p = proposal(root, body)
    with pytest.raises(ValueError, match="colliding"):
        prepare_split(root, p, date.today(), {})


def test_existing_destination_and_unrelated_edit(world):
    root, body, _ = world
    child = root / "syntheses/child.md"
    child.write_text(
        "---\ntitle: Child\ntopics: [child]\ncreated: '2026-01-01'\nupdated: '2026-01-01'\n---\n\n## Summary\n\nSummary.\n\n## Earlier\n\nEarlier.\n"
    )
    p = proposal(root, body)
    unrelated = root / "knowledge/test/unrelated.md"
    unrelated.write_text("---\ntopics: [root]\nclaim: Other\n---\n\nNote.\n")
    plan = prepare_split(root, p, date.today(), {})
    old, new = plan.changes[child]
    assert old == child.read_bytes()
    assert new is not None
    assert new.decode().index("## Earlier") < new.decode().index("## Details")


def test_destination_adoption_and_competing_route_stale(world):
    root, body, _ = world
    p = proposal(root, body)
    other = root / "syntheses/other.md"
    other.write_text(
        "---\ntitle: Other\ntopics: [child]\ncreated: '2026-01-01'\nupdated: '2026-01-01'\n---\n\n## Summary\n\nSummary.\n"
    )
    with pytest.raises(ValueError, match="snapshot"):
        prepare_split(root, p, date.today(), {})
    other.unlink()
    p = proposal(root, body)
    for i in range(5):
        path = root / f"knowledge/test/n{i}.md"
        path.write_text(path.read_text().replace("[child]", "[child, other]"))
    with pytest.raises(ValueError, match="snapshot"):
        prepare_split(root, p, date.today(), {})


def test_refuses_symlink_for_planned_note(world):
    root, _, _ = world
    path = root / "knowledge/test/n0.md"
    target = root / "knowledge/test/target.md"
    target.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(target.name)
    with pytest.raises(Exception, match="symlink"):
        candidate_input(root, "s:parent#part", "child")


def test_missing_number_missing_support_and_secret(world):
    root, body, _ = world
    p = proposal(root, body)
    with pytest.raises(ValueError, match="missing figure"):
        prepare_split(
            root, replace(p, child_text=body.replace("42", "forty two")), date.today(), {}
        )
    # All references remain in the parent but the destination must support every moved note.
    with pytest.raises(ValueError, match="support"):
        prepare_split(
            root,
            replace(
                p, parent_text=body, child_text="Detail.\n\nSources: [n0](../knowledge/test/n0.md)"
            ),
            date.today(),
            {},
        )
    with pytest.raises(ValueError, match="secret"):
        prepare_split(root, replace(p, child_heading="password: abcdefghijk"), date.today(), {})


def test_term_guard_does_not_create_configuration(world, tmp_path):
    root, body, _ = world
    config = tmp_path / "config"
    prepare_split(root, proposal(root, body), date.today(), {"XDG_CONFIG_HOME": str(config)})
    assert not config.exists()


def test_rejects_crlf_source_before_preview(world):
    root, body, _ = world
    syn = root / "syntheses/parent.md"
    syn.write_bytes(syn.read_bytes().replace(b"\n", b"\r\n"))
    with pytest.raises(ValueError):
        prepare_split(root, proposal(root, body), date.today(), {})
