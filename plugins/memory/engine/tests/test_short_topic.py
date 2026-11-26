import mem
import pytest
from memories import records

CLAIM = "Always run the project's checks before reporting that a change works."
SHORT = "Run the checks before reporting a change."
RC_USAGE = 2
RC_BLOCKED = 4


@pytest.fixture
def gfolder(tmp_path, monkeypatch):
    folder = tmp_path / "gmem"
    monkeypatch.setenv("MEM_MEMORIES", str(folder))
    return folder


def remember(*extra, claim=CLAIM):
    return mem.main(["remember", "--global", "--kind", "lesson", "--claim", claim, *extra])


def only(gfolder):
    (m,) = records.load_memories(gfolder, "global")
    return m


def put(folder, handle, claim, extra=""):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{handle}.md"
    path.write_text(
        f"---\nkind: lesson\nclaim: {claim}\ncreated: '2026-01-01'\nobserved: 1\nstatus: active\n{extra}---\n",
        encoding="utf-8",
    )
    return path


def test_remember_and_edit_store_short_and_topic(gfolder, capsys):
    assert (
        mem.main([
            "remember",
            "--global",
            "--kind",
            "lesson",
            "--claim",
            CLAIM,
            "--short",
            SHORT,
            "--topic",
            "testing",
        ])
        == 0
    )
    m = records.load_memories(gfolder, "global")[0]
    assert m.short == SHORT and m.topic == "testing" and m.load is None
    assert (
        mem.main([
            "memory",
            "edit",
            f"m:{m.handle}",
            "--global",
            "--short",
            "",
            "--topic",
            "process",
            "--no-load",
        ])
        == 0
    )
    m = records.load_memories(gfolder, "global")[0]
    assert m.short is None and m.topic == "process" and m.load == "no"
    assert mem.main(["memory", "edit", f"m:{m.handle}", "--global", "--load"]) == 0
    assert records.load_memories(gfolder, "global")[0].load is None


@pytest.mark.parametrize(
    "flag,bad",
    [
        ("--short", "x" * 121),
        ("--short", "two\nlines"),
        ("--topic", "Testing"),
        ("--topic", "three word topic"),
        ("--topic", "x" * 25),
        ("--topic", "other"),
    ],
)
def test_invalid_values_are_refused(flag, bad, gfolder, capsys):
    assert remember(flag, bad) == RC_USAGE
    assert flag[2:] in capsys.readouterr().err
    assert not gfolder.exists() or records.load_memories(gfolder, "global") == []
    assert remember() == 0
    before = only(gfolder).path.read_bytes()
    assert (
        mem.main(["memory", "edit", f"m:{only(gfolder).handle}", "--global", flag, bad]) == RC_USAGE
    )
    assert flag[2:] in capsys.readouterr().err
    assert only(gfolder).path.read_bytes() == before
    with pytest.raises(ValueError):
        records.write_memory(
            gfolder,
            "global",
            kind="lesson",
            claim="Another claim.",
            body="",
            today=records.datetime.date.today(),
            **{flag[2:]: bad},
        )


def test_a_bad_stored_value_reads_as_absent_and_keeps_the_record(gfolder):
    path = put(gfolder, "bad", CLAIM, "short: [1, 2]\ntopic: 7\nload: maybe\n")
    m = records.load_memories(gfolder, "global")[0]
    assert m.error is None and m.short is None and m.topic is None and m.load is None
    path.write_text(path.read_text().replace("load: maybe", "load: no"), encoding="utf-8")
    assert (
        records.load_memories(gfolder, "global")[0].load == "no"
    )  # a bare no is read by YAML as False


def test_an_edit_of_the_claim_removes_the_short_form_and_says_so(gfolder, capsys):
    assert remember("--short", SHORT, "--topic", "testing") == 0
    h = only(gfolder).handle
    assert mem.main(["memory", "edit", f"m:{h}", "--global", "--no-load"]) == 0
    capsys.readouterr()
    assert (
        mem.main(["memory", "edit", f"m:{h}", "--global", "--claim", CLAIM + " Then say so."]) == 0
    )
    assert (
        "mem: the short form was removed with the old claim: write a new one with --short"
        in capsys.readouterr().err
    )
    m = only(gfolder)
    assert m.short is None and m.topic == "testing" and m.load == "no"
    assert "short" not in m.path.read_text()


def test_an_edit_of_claim_and_short_together_keeps_the_new_short(gfolder, capsys):
    assert remember("--short", SHORT) == 0
    h = only(gfolder).handle
    capsys.readouterr()
    assert (
        mem.main([
            "memory",
            "edit",
            f"m:{h}",
            "--global",
            "--claim",
            CLAIM + " Then say so.",
            "--short",
            "Run the checks, then say so.",
        ])
        == 0
    )
    assert "removed" not in capsys.readouterr().err
    assert only(gfolder).short == "Run the checks, then say so."


def test_confirm_merge_and_triage_keep_the_three_fields(gfolder, capsys):
    fields = "short: Keep this rule.\ntopic: testing\nload: 'no'\n"
    put(gfolder, "keep", "Alpha beta gamma", fields)
    put(gfolder, "drop", "Alpha beta gamma delta", "short: Drop rule.\ntopic: other\n")
    assert mem.main(["confirm", "--global", "m:keep"]) == 0
    assert mem.main(["merge", "--global", "m:keep", "m:drop"]) == 0
    kept = {m.handle: m for m in records.load_memories(gfolder, "global")}["keep"]
    assert (kept.short, kept.topic, kept.load, kept.observed) == (
        "Keep this rule.",
        "testing",
        "no",
        3,
    )
    put(gfolder, "wait", "Walrus queues drain slowly", "triage: pending\n" + fields)
    assert mem.main(["triage", "accept", "m:wait"]) == 0
    waited = {m.handle: m for m in records.load_memories(gfolder, "global")}["wait"]
    assert (waited.triage, waited.short, waited.topic, waited.load) == (
        None,
        "Keep this rule.",
        "testing",
        "no",
    )


def test_a_global_short_with_a_secret_is_refused(gfolder, capsys):
    secret = "Use token ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
    assert remember("--short", secret) == RC_BLOCKED
    assert remember() == 0
    before = only(gfolder).path.read_bytes()
    assert (
        mem.main(["memory", "edit", f"m:{only(gfolder).handle}", "--global", "--short", secret])
        == RC_BLOCKED
    )
    assert only(gfolder).path.read_bytes() == before


def test_show_prints_the_fields(gfolder, capsys):
    assert remember("--short", SHORT, "--topic", "testing") == 0
    h = only(gfolder).handle
    mem.main(["memory", "edit", f"m:{h}", "--global", "--no-load"])
    capsys.readouterr()
    assert mem.main(["show", f"m:{h}"]) == 0
    out = capsys.readouterr().out
    assert f"short: {SHORT}" in out and "topic: testing" in out and "load: no" in out


def test_a_load_value_other_than_no_reads_as_absent(gfolder):
    path = put(gfolder, "zero", CLAIM, "load: 0\n")
    assert records.load_memories(gfolder, "global")[0].load is None
    path.write_text(path.read_text().replace("load: 0", "load: false"), encoding="utf-8")
    assert records.load_memories(gfolder, "global")[0].load == "no"
    path.write_text(path.read_text().replace("load: false", "load: 'no'"), encoding="utf-8")
    assert records.load_memories(gfolder, "global")[0].load == "no"


def test_short_whitespace_is_collapsed_and_a_line_break_is_named(gfolder, capsys):
    assert remember("--short", "  Run   the checks  before reporting a change.  ") == 0
    m = only(gfolder)
    assert m.short == "Run the checks before reporting a change."
    assert (
        mem.main(["memory", "edit", f"m:{m.handle}", "--global", "--short", "  Other   rule. "])
        == 0
    )
    assert only(gfolder).short == "Other rule."
    capsys.readouterr()
    assert (
        mem.main(["memory", "edit", f"m:{m.handle}", "--global", "--short", "two\nlines"])
        == RC_USAGE
    )
    assert "line break" in capsys.readouterr().err


def test_the_removal_notice_is_printed_only_after_the_write(gfolder, capsys, monkeypatch):
    assert remember("--short", SHORT) == 0
    h = only(gfolder).handle
    capsys.readouterr()

    def refuse(*a, **k):
        raise ValueError("write refused")

    monkeypatch.setattr(records, "update", refuse)
    assert (
        mem.main(["memory", "edit", f"m:{h}", "--global", "--claim", CLAIM + " Then say so."])
        == RC_USAGE
    )
    assert "removed" not in capsys.readouterr().err
    assert only(gfolder).short == SHORT


def test_load_index_is_read_stored_shown_and_exclusive(gfolder, capsys):
    path = put(gfolder, "idx", CLAIM, "load: index\n")
    assert records.load_memories(gfolder, "global")[0].load == "index"
    path.write_text(path.read_text().replace("load: index", "load: Index"), encoding="utf-8")
    assert records.load_memories(gfolder, "global")[0].load is None
    path.write_text(path.read_text().replace("load: Index\n", ""), encoding="utf-8")
    h = only_claim(gfolder).handle
    assert mem.main(["memory", "edit", f"m:{h}", "--global", "--index-only"]) == 0
    assert only_claim(gfolder).load == "index"
    capsys.readouterr()
    assert mem.main(["show", f"m:{h}"]) == 0
    assert "load: index" in capsys.readouterr().out
    assert mem.main(["memory", "edit", f"m:{h}", "--global", "--no-load"]) == 0
    assert only_claim(gfolder).load == "no"
    assert mem.main(["memory", "edit", f"m:{h}", "--global", "--index-only"]) == 0
    assert mem.main(["memory", "edit", f"m:{h}", "--global", "--load"]) == 0
    assert only_claim(gfolder).load is None
    for pair in (
        ["--index-only", "--no-load"],
        ["--index-only", "--load"],
        ["--no-load", "--load"],
    ):
        with pytest.raises(SystemExit):
            mem.main(["memory", "edit", f"m:{h}", "--global", *pair])


def only_claim(gfolder):
    return next(m for m in records.load_memories(gfolder, "global") if m.claim == CLAIM)
