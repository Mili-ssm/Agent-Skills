"""short_by: a short form a model wrote and nobody read, the list of those, and the code check on a plain --short."""

import mem
import pytest
from store import records

CLAIM = "A cache may hide a stale value after a deploy, so consider clearing it."
SHORT = "Consider clearing the cache after a deploy; it may hide a stale value."
STRONG = "Always clear the cache after a deploy."
REFUSED = 2  # exit code of a refused command
LISTED_LINES = 4  # two lessons, two lines each
EDITED_LESSONS = 2


@pytest.fixture
def gfolder(tmp_path, monkeypatch):
    folder = tmp_path / "gmem"
    monkeypatch.setenv("MEM_MEMORIES", str(folder))
    return folder


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    records.project_dir(root).mkdir(parents=True)
    monkeypatch.setenv("MEM_PROJECT", str(root))
    return records.project_dir(root)


def remember(*extra, claim=CLAIM, scope: str | None = "--global"):
    return mem.main([
        "remember",
        *([scope] if scope else []),
        "--kind",
        "lesson",
        "--claim",
        claim,
        *extra,
    ])


def only(folder, scope="global"):
    (m,) = records.load_memories(folder, scope)
    return m


def test_a_plain_short_edit_is_checked_and_marked_as_the_models(gfolder, capsys):
    assert remember() == 0
    h = only(gfolder).handle
    assert mem.main(["memory", "edit", f"m:{h}", "--global", "--short", SHORT]) == 0
    m = only(gfolder)
    assert (m.short, m.short_by) == (SHORT, "model")
    assert "short_by: model" in m.path.read_text()
    assert mem.main(["show", f"m:{h}"]) == 0
    assert "short_by: model" in capsys.readouterr().out
    assert remember("--short", SHORT, claim="Another hedged claim: a retry may help once.") == 0


def test_a_plain_short_edit_that_drops_the_hedge_is_refused_with_the_reason(gfolder, capsys):
    assert remember() == 0
    before = only(gfolder).path.read_bytes()
    capsys.readouterr()
    assert (
        mem.main(["memory", "edit", f"m:{only(gfolder).handle}", "--global", "--short", STRONG])
        == REFUSED
    )
    assert "the claim is hedged and the short form is not" in capsys.readouterr().err
    assert only(gfolder).path.read_bytes() == before
    assert (
        remember("--short", STRONG, claim="A different hedged claim: sorting may help.") == REFUSED
    )
    assert len(records.load_memories(gfolder, "global")) == 1


def test_user_read_skips_the_check_and_clears_the_mark(gfolder, capsys):
    assert remember("--short", SHORT) == 0 and only(gfolder).short_by == "model"
    h = only(gfolder).handle
    assert mem.main(["memory", "edit", f"m:{h}", "--global", "--short", STRONG, "--user-read"]) == 0
    m = only(gfolder)
    assert (m.short, m.short_by) == (STRONG, None)
    assert "short_by" not in m.path.read_text()
    assert (
        remember(
            "--short", STRONG, "--user-read", claim="Another hedged claim: a retry may help once."
        )
        == 0
    )
    assert all(x.short_by is None for x in records.load_memories(gfolder, "global"))


def test_user_read_without_short_is_refused(gfolder, capsys):
    assert remember("--user-read") == REFUSED
    assert not gfolder.exists() or records.load_memories(gfolder, "global") == []
    assert remember() == 0
    before = only(gfolder).path.read_bytes()
    assert (
        mem.main([
            "memory",
            "edit",
            f"m:{only(gfolder).handle}",
            "--global",
            "--claim",
            "A new claim.",
            "--user-read",
        ])
        == REFUSED
    )
    assert only(gfolder).path.read_bytes() == before


def test_a_claim_edit_removes_short_and_short_by(gfolder, capsys):
    assert remember("--short", SHORT) == 0
    h = only(gfolder).handle
    assert (
        mem.main([
            "memory",
            "edit",
            f"m:{h}",
            "--global",
            "--claim",
            "A cache may hide a stale value after a release.",
            "--shrink",
        ])
        == 0
    )
    m = only(gfolder)
    assert (m.short, m.short_by) == (None, None)
    assert "short_by" not in m.path.read_text()


def test_a_claim_edit_removes_the_mark_of_a_stored_short_that_is_invalid(gfolder, capsys):
    gfolder.mkdir()
    (gfolder / "an-invalid.md").write_text(
        "---\nkind: lesson\nclaim: Claim one.\ncreated: '2026-01-01'\nobserved: 1\nstatus: active\n"
        f"short: {'x' * 130}\nshort_by: model\n---\n",
        encoding="utf-8",
    )
    (m,) = records.load_memories(gfolder, "global")
    assert m.short is None and "short_by: model" in m.path.read_text()
    assert (
        mem.main([
            "memory",
            "edit",
            f"m:{m.handle}",
            "--global",
            "--claim",
            "Claim two.",
            "--shrink",
        ])
        == 0
    )
    assert "short_by" not in m.path.read_text()


def test_a_bad_stored_short_by_reads_as_absent(gfolder):
    gfolder.mkdir()
    for handle, value in (("a-seven", "7"), ("an-owner", "owner")):
        (gfolder / f"{handle}.md").write_text(
            f"---\nkind: lesson\nclaim: Claim {handle}.\ncreated: '2026-01-01'\nobserved: 1\nstatus: active\n"
            f"short: Short {handle}.\nshort_by: {value}\n---\n",
            encoding="utf-8",
        )
    loaded = records.load_memories(gfolder, "global")
    assert [m.error for m in loaded] == [None, None]
    assert [m.short_by for m in loaded] == [None, None]


def test_unread_lists_project_then_global_and_skips_invalid_shorts(project, gfolder, capsys):
    assert (
        remember(
            "--short", "Consider a retry; it may help.", claim="A retry may help, so consider it."
        )
        == 0
    )
    assert remember("--short", SHORT, scope=None) == 0
    (project / "bad-short.md").write_text(
        "---\nkind: lesson\nclaim: Bad.\ncreated: '2026-01-01'\nobserved: 1\nstatus: active\n"
        f"short: {'x' * 130}\nshort_by: model\n---\n",
        encoding="utf-8",
    )
    capsys.readouterr()
    assert mem.main(["rules", "--unread"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == LISTED_LINES
    assert lines[0].split("\t")[1:] == ["project", SHORT] and lines[1] == f"\tclaim: {CLAIM}"
    assert lines[2].split("\t")[1:] == ["global", "Consider a retry; it may help."]
    assert lines[3] == "\tclaim: A retry may help, so consider it."


def test_unread_with_nothing_says_so(gfolder, capsys):
    assert mem.main(["rules", "--unread"]) == 0
    assert capsys.readouterr().out.strip() == "No short form is waiting to be read."


def test_read_all_clears_every_listed_lesson_and_read_of_an_unknown_handle_changes_nothing(
    gfolder, capsys
):
    assert remember("--short", SHORT) == 0
    assert (
        remember(
            "--short", "Consider a retry; it may help.", claim="A retry may help, so consider it."
        )
        == 0
    )
    snap = {m.handle: m.path.read_bytes() for m in records.load_memories(gfolder, "global")}
    handles = sorted(snap)
    capsys.readouterr()
    assert mem.main(["rules", "--read", f"m:{handles[0]}", "m:nonexistent"]) == REFUSED
    assert {m.handle: m.path.read_bytes() for m in records.load_memories(gfolder, "global")} == snap
    capsys.readouterr()
    assert mem.main(["rules", "--read", "all"]) == 0
    assert sorted(capsys.readouterr().out.splitlines()) == sorted(f"m:{h}\tread" for h in handles)
    assert all(m.short_by is None and m.short for m in records.load_memories(gfolder, "global"))
    log = (gfolder / records.CURATION_LOG).read_text()
    assert log.count('"action": "edit"') == EDITED_LESSONS


def test_confirm_merge_and_triage_keep_short_by(gfolder, capsys):
    assert remember("--short", SHORT) == 0
    assert remember(claim="A cache may hide a stale value after a deploy, so clear it.") == 0
    keep, drop = records.load_memories(gfolder, "global")
    if keep.short_by is None:
        keep, drop = drop, keep
    assert mem.main(["confirm", f"m:{keep.handle}", "--global", "--until", "2099-01-01"]) == 0
    assert mem.main(["merge", f"m:{keep.handle}", f"m:{drop.handle}", "--global"]) == 0
    assert {m.handle: m for m in records.load_memories(gfolder, "global")}[
        keep.handle
    ].short_by == "model"
    assert mem.main(["triage", "hold", f"m:{keep.handle}", "--because", "check it"]) == 0
    assert mem.main(["triage", "accept", f"m:{keep.handle}"]) == 0
    assert {m.handle: m for m in records.load_memories(gfolder, "global")}[
        keep.handle
    ].short_by == "model"


def test_curate_counts_the_unread_short_forms_and_says_nothing_with_none(gfolder, capsys):
    assert remember() == 0
    capsys.readouterr()
    assert mem.main(["curate", "--global"]) == 0
    assert "short forms nobody read" not in capsys.readouterr().out
    assert (
        mem.main(["memory", "edit", f"m:{only(gfolder).handle}", "--global", "--short", SHORT]) == 0
    )
    capsys.readouterr()
    assert mem.main(["curate", "--global"]) == 0
    assert "short forms nobody read: 1 (mem rules --unread)" in capsys.readouterr().out
