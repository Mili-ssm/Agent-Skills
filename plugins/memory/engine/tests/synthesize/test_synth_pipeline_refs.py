"""The lean synthesis loop and inline references: the units file, `REF:` report lines, applying them by code."""

import io
import subprocess
import sys
from pathlib import Path

import mem
import pytest
from synthesize import pipeline as sp

A = "../knowledge/computing/attention-replaces-recurrence.md"
B = "../literature/computing/2017-vaswani-attention.md"
ALPHA = (
    f"First plain sentence   here. Second one is backed.[a]({A}) Third has [an inline one]({B}) in it.\n\n"
    "| col | val |\n|---|---|\n| row | x |\n\n"
    f"Sources: [attention]({A}), [vaswani]({B}), experience 2026-11-17"
)
BETA = f"Beta says something plain.\n\nSources: [vaswani]({B})"
GAMMA = "Gamma says one thing. Gamma says another.\n\nSources: experience 2026-11-17"


MALFORMED_REFS = 2
REMOVE_AND_ADD = 2


def parsed(path):
    """`sp.parse_report` of a report that must parse."""
    got = sp.parse_report(path)
    assert got is not None
    return got


def text_file(tmp_path, text, name="body.md"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


@pytest.fixture
def store(hub_root, tmp_path, monkeypatch):
    """The fixture store with a synthesis `attention` (parts Alpha, Beta, Gamma), and `sp.mem` run in process."""

    def fake_mem(root, env, *args, stdin=None):
        out, err = io.StringIO(), io.StringIO()
        old = sys.stdin, sys.stdout, sys.stderr
        sys.stdin, sys.stdout, sys.stderr = io.StringIO(stdin or ""), out, err
        try:
            code = mem.main(["--root", str(root), *args])
        finally:
            sys.stdin, sys.stdout, sys.stderr = old
        return subprocess.CompletedProcess(args, code, out.getvalue(), err.getvalue())

    monkeypatch.setattr(sp, "mem", fake_mem)
    assert (
        fake_mem(
            hub_root,
            {},
            "synthesis",
            "new",
            "--title",
            "Attention",
            "--topics",
            "ml",
            "--slug",
            "attention",
            "--summary-file",
            text_file(tmp_path, "How attention works here.\n", "s.md"),
        ).returncode
        == 0
    )
    for name, text in (("Alpha", ALPHA), ("Beta", BETA), ("Gamma", GAMMA)):
        done = fake_mem(
            hub_root,
            {},
            "synthesis",
            "add",
            "s:attention",
            "--section",
            name,
            "--body-file",
            "-",
            stdin=text + "\n",
        )
        assert done.returncode == 0, done.stderr
    return hub_root


def synthesis_text(root):
    return (root / "syntheses" / "attention.md").read_text(encoding="utf-8")


# ---- the units file ----


def test_units_file_lists_units_references_and_sources(store):
    text = sp.units_text(store / "syntheses" / "attention.md")
    assert text == (
        "## alpha\n"
        "1 | First plain sentence here. | -\n"
        f"2 | Second one is backed. | {A}\n"
        f"3 | Third has an inline one in it. | {B}\n"
        "4 | | col | val | | -\n"
        "5 | | row | x | | -\n"
        f"Sources: {A}, {B}\n"
        "## beta\n"
        "1 | Beta says something plain. | -\n"
        f"Sources: {B}\n"
        "## gamma\n"
        "1 | Gamma says one thing. | -\n"
        "2 | Gamma says another. | -\n"
        "Sources: \n"
    ), text


def test_units_file_is_written_for_the_parts_not_the_summary(store, tmp_path):
    target = tmp_path / "units.md"
    sp.write_units(store / "syntheses" / "attention.md", target)
    assert target.read_text().startswith("## alpha\n") and "## summary" not in target.read_text()


# ---- the report ----

REPORT = (
    "alpha | First plain sentence here | absolute | ../knowledge/a/b.md | First plain sentence, softened.\n"
    f"REF: alpha | 2 | missing | {A}\n"
    f"REF: beta | 1 | wrong {A} | {B}\n"
    f"REF: beta | 1 | wrong {A} | none\n"
    "REF: beta | x | missing | nope\n"
    "REF: beta | 1 | sideways | nope\n"
    "PARTS: alpha\nCOUNTS: checked=9 unsupported=1\n"
)


def test_parse_report_returns_ref_lines_apart_from_the_claims(tmp_path):
    path = tmp_path / "r.md"
    path.write_text(REPORT)
    got = parsed(path)
    assert (got["checked"], got["unsupported"], got["parts"]) == (9, 1, ["alpha"])
    assert [c["part"] for c in got["claims"]] == ["alpha"]
    assert got["refs"] == [
        {"part": "alpha", "number": 2, "kind": "missing", "current": None, "target": A},
        {"part": "beta", "number": 1, "kind": "wrong", "current": A, "target": B},
        {"part": "beta", "number": 1, "kind": "wrong", "current": A, "target": None},
    ]
    assert got["ref_malformed"] == MALFORMED_REFS


def test_ref_lines_alone_leave_unsupported_at_zero(tmp_path):
    path = tmp_path / "r.md"
    path.write_text(
        f"REF: s:t#alpha | 1 | missing | {A}\nPARTS: \nCOUNTS: checked=4 unsupported=0\n"
    )
    got = parsed(path)
    assert got["unsupported"] == 0 and got["claims"] == [] and got["parts"] == []
    assert got["refs"][0]["part"] == "alpha" and got["ref_malformed"] == 0


# ---- the loop ----


def loop(monkeypatch, tmp_path, store, reports, *, answers=None, **kw):
    """Run lean_loop with a fake session: each checker writes the next report, a fixer or deleter runs `act`."""
    work = tmp_path / "w"
    work.mkdir(exist_ok=True)
    ran, prompts = [], []

    def fake_session(*args, **kw):
        prompt, log = (
            args[2],
            kw["log"],
        )  # run_session(claude, model, prompt, work, settings, *, env, log, ...)
        role = log.name.split("-", 1)[1].removesuffix(".jsonl")
        ran.append(role)
        prompts.append(prompt)
        if role == "checker":
            n = ran.count("checker")
            (work / f"report-{n}.md").write_text(reports[n - 1].replace("{A}", A).replace("{B}", B))
        elif answers and role in answers:
            answers[role](work, prompt)
        return {
            "writes": 0,
            "write_errors": 0,
            "denied": 0,
            "tool_errors": 0,
            "model_usage": {},
            "cost": 0.0,
            "wall": 0.0,
            "error": False,
            "answer": "",
            "has_result": True,
        }

    monkeypatch.setattr(sp, "run_session", fake_session)
    sessions = []
    done = sp.lean_loop(
        "claude",
        {},
        tmp_path,
        store,
        work,
        settings=tmp_path / "set",
        topic="attention",
        sessions=sessions,
        **kw,
    )
    return done, ran, prompts, work


def test_a_report_of_ref_lines_only_is_applied_by_code_and_nothing_else_runs(
    monkeypatch, tmp_path, store
):
    done, ran, _, work = loop(
        monkeypatch,
        tmp_path,
        store,
        [f"REF: alpha | 1 | missing | {A}\nPARTS: \nCOUNTS: checked=6 unsupported=0\n"],
    )
    assert ran == ["checker"] and done["fixes"] == 0 and done["deleted"] == 0 and not done["why"]
    assert f"First plain sentence here.[attention]({A})" in synthesis_text(store).replace(
        "   ", " "
    ) or f"here. [attention]({A})" in synthesis_text(store)
    assert done["refs"] == [
        {
            "check": 1,
            "reported": 1,
            "malformed": 0,
            "lines": 1,
            "applied": 1,
            "refused": 0,
            "reasons": [],
            "error": "",
        }
    ]
    assert (work / "refs-1.txt").read_text() == f"alpha | 1 | add {A}\n"


def test_second_check_refs_are_applied_before_the_delete_only_step(monkeypatch, tmp_path, store):
    seen = {}

    def fixer(work, prompt):
        seen["fixer"] = prompt

    def deleter(work, prompt):
        seen["report"] = (work / "report-2.md").read_text()
        seen["text"] = synthesis_text(store)

    first = "gamma | Gamma says one thing | absolute | n | x\nPARTS: gamma\nCOUNTS: checked=6 unsupported=1\n"
    second = (
        f"gamma | Gamma says another | absolute | n | x\nREF: alpha | 1 | missing | {A}\n"
        "PARTS: gamma\nCOUNTS: checked=2 unsupported=1\n"
    )
    done, ran, _, _ = loop(
        monkeypatch, tmp_path, store, [first, second], answers={"fixer": fixer, "deleter": deleter}
    )
    assert ran == ["checker", "fixer", "checker", "deleter"] and done["deleted"] == 1
    assert "REF: alpha | 1 | missing" in seen["report"]
    assert f"[attention]({A})" in seen["text"] and "First plain sentence" in seen["text"]
    assert [r["check"] for r in done["refs"]] == [2] and done["refs"][0]["applied"] == 1


def test_units_file_is_rewritten_before_the_scoped_check(monkeypatch, tmp_path, store):
    units = []

    def fixer(work, prompt):
        path = store / "syntheses" / "attention.md"
        path.write_text(path.read_text().replace("Gamma says another.", "Gamma says more."))

    first = "gamma | Gamma says another | absolute | n | x\nPARTS: gamma\nCOUNTS: checked=6 unsupported=1\n"
    second = "PARTS: \nCOUNTS: checked=1 unsupported=0\n"
    real = sp.brief

    def spy(name, briefs=sp.BRIEFS, **values):
        if name == "checker":
            units.append(Path(values["UNITS_FILE"]).read_text(encoding="utf-8"))
        return real(name, briefs, **values)

    monkeypatch.setattr(sp, "brief", spy)
    loop(monkeypatch, tmp_path, store, [first, second], answers={"fixer": fixer})
    assert "Gamma says another." in units[0] and "Gamma says more." in units[1]


def test_a_failing_refs_command_is_recorded_and_does_not_stop_the_loop(
    monkeypatch, tmp_path, store
):
    first = f"REF: nowhere | 1 | missing | {A}\nPARTS: \nCOUNTS: checked=6 unsupported=0\n"
    done, ran, _, _ = loop(monkeypatch, tmp_path, store, [first])
    assert ran == ["checker"] and not done["why"]
    assert done["refs"][0]["applied"] == 0 and done["refs"][0]["refused"] == 1


def test_a_wrong_reference_becomes_a_remove_and_an_add(monkeypatch, tmp_path, store):
    first = f"REF: alpha | 3 | wrong {B} | {A}\nPARTS: \nCOUNTS: checked=6 unsupported=0\n"
    done, _, _, work = loop(monkeypatch, tmp_path, store, [first])
    assert (work / "refs-1.txt").read_text() == f"alpha | 3 | remove {B}\nalpha | 3 | add {A}\n"
    assert done["refs"][0]["lines"] == REMOVE_AND_ADD


def test_the_loop_reads_its_briefs_from_the_folder_it_is_given(monkeypatch, tmp_path, store):
    briefs = tmp_path / "old-briefs"
    briefs.mkdir()
    for name in ("checker", "fixer"):
        (briefs / f"{name}-brief.md").write_text(
            f"OLD {name} {{REPORT_FILE}} {{STORE}} {{SLUG}} {{PARTS}} {{WORK_DIR}}\n"
        )
    _, _, prompts, _ = loop(
        monkeypatch, tmp_path, store, ["PARTS: \nCOUNTS: checked=1 unsupported=0\n"], briefs=briefs
    )
    assert prompts[0].startswith("OLD checker")


# ---- the guard ----


def test_guard_parts_reverts_a_part_whose_fixer_version_added_a_reference(store):
    path = store / "syntheses" / "attention.md"
    before = path.read_text()
    after = before.replace("Beta says something plain.", f"Beta says something plain. [v]({B})")
    path.write_text(after)
    bad, back = sp.guard_parts(store, {}, "attention", before, after, allowed=["alpha"])
    assert (bad, back) == (["beta"], ["beta"])
    assert (
        sp.split_parts(path.read_text())["beta"].strip() == sp.split_parts(before)["beta"].strip()
    )


def test_ref_lines_in_a_bullet_or_backticks_are_read_and_do_not_count_as_unsupported(tmp_path):
    report = tmp_path / "report.md"
    report.write_text(
        "- REF: alpha | 1 | missing | `../knowledge/a.md`.\n"
        "  `REF: alpha | 2 | wrong ../knowledge/a.md | None`\n"
        "REF: alpha | 3. | missing | ../knowledge/a.md\n"
        "PARTS:\nCOUNTS: checked=3 unsupported=2\n"
    )
    got = parsed(report)
    assert [(r["number"], r["kind"], r["current"], r["target"]) for r in got["refs"]] == [
        (1, "missing", None, "../knowledge/a.md"),
        (2, "wrong", "../knowledge/a.md", None),
    ]
    assert got["ref_malformed"] == 1 and got["claims"] == [] and got["unsupported"] == 0
