import json
import subprocess

import mem
import pytest
import records
from conftest import usage_log_path

RC_FORBIDDEN = 4
RC_SOFT = 5
RC_USAGE = 2
TERM_COPIES = 2
TERM_LINES = 3

ARGS = ["remember", "--global", "--kind", "lesson"]


@pytest.fixture
def gfolder(tmp_path, monkeypatch):
    folder = tmp_path / "gmem"
    monkeypatch.setenv("MEM_MEMORIES", str(folder))
    return folder


@pytest.fixture
def terms_file(tmp_path):
    f = tmp_path / "mem-config" / "agent-memory" / "forbidden-terms"
    f.parent.mkdir(parents=True)
    return f


def remember(*extra, claim="Retries need keys."):
    return mem.main([*ARGS, "--claim", claim, *extra])


def test_parse_term_classes():
    assert records.parse_term("# note") is None and records.parse_term("   ") is None
    assert records.parse_term("Acme", 3) == records.Term(3, "Acme", False, None)
    assert records.parse_term("soft: Zeta ", 4) == records.Term(4, "Zeta", True, None)
    assert records.parse_term("soft[lesson]: Zeta", 5) == records.Term(5, "Zeta", True, "lesson")


def test_comments_are_ignored_and_the_line_number_counts_them(gfolder, terms_file, capsys):
    terms_file.write_text("# acme is only a comment here\n\nzeta\n")
    assert remember(claim="Acme retries.") == 0
    assert remember(claim="Zeta retries.") == RC_FORBIDDEN
    assert "line 3 of the forbidden-terms list" in capsys.readouterr().err


def test_soft_term_exits_5_until_the_owner_approves(gfolder, terms_file, capsys):
    terms_file.write_text("soft: Zeta\n")
    assert remember(claim="Zeta retries.") == RC_SOFT
    err = capsys.readouterr().err.strip()
    assert err == (
        'mem: the text mentions "Zeta" (a soft term): ask the owner whether this may be written to the '
        "global scope; if they agree, repeat with --owner-approved."
    )
    assert not gfolder.exists() or not list(gfolder.glob("*.md"))
    assert remember("--owner-approved", claim="Zeta retries.") == 0
    assert any(gfolder.glob("*.md"))
    entries = [json.loads(l) for l in usage_log_path().read_text().splitlines()]
    assert entries[-1]["owner_approved"] is True and "Zeta" not in json.dumps(entries)


def test_owner_approval_does_not_pass_hard_terms_or_secrets(gfolder, terms_file):
    terms_file.write_text("soft: Zeta\nacme\n")
    assert remember("--owner-approved", claim="Zeta and Acme.") == RC_FORBIDDEN
    assert (
        remember(
            "--owner-approved", "--context", "password = hunter2hunter2", claim="Zeta retries."
        )
        == RC_FORBIDDEN
    )


def test_soft_term_with_a_kind_applies_only_to_that_kind(gfolder, terms_file):
    terms_file.write_text("soft[decision]: Zeta\n")
    assert remember(claim="Zeta retries.") == 0  # a lesson
    assert (
        mem.main(["remember", "--global", "--kind", "decision", "--claim", "Zeta wins."]) == RC_SOFT
    )


def test_project_memories_skip_the_term_check(tmp_path, monkeypatch, terms_file):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    monkeypatch.setenv("MEM_PROJECT", str(repo))
    terms_file.write_text("acme\nsoft: zeta\n")
    assert mem.main(["remember", "--kind", "lesson", "--claim", "Acme and zeta."]) == 0


def test_reason_for_a_global_memory_checks_soft_terms(
    gfolder, terms_file, tmp_path, capsys, monkeypatch
):
    assert remember() == 0
    capsys.readouterr()
    terms_file.write_text("soft: zeta\n")
    assert (
        mem.main(["forget", "m:retries-need-keys", "--global", "--because", "Zeta said so"])
        == RC_SOFT
    )
    assert "(a soft term)" in capsys.readouterr().err
    assert (
        mem.main([
            "forget",
            "m:retries-need-keys",
            "--global",
            "--because",
            "Zeta said so",
            "--owner-approved",
        ])
        == 0
    )


def test_terms_list_add_remove(tmp_path, capsys):
    terms = tmp_path / "mem-config" / "agent-memory" / "forbidden-terms"
    assert mem.main(["terms", "list"]) == 0 and not capsys.readouterr().out
    assert mem.main(["terms", "add", "Acme Corp"]) == 0
    assert mem.main(["terms", "add", "Zeta", "--soft"]) == 0
    assert mem.main(["terms", "add", "Zeta", "--soft", "--kind", "lesson"]) == 0
    capsys.readouterr()
    assert terms.read_text().startswith("#")
    assert mem.main(["terms", "list"]) == 0
    assert capsys.readouterr().out == "hard\tAcme Corp\nsoft\tZeta\nsoft[lesson]\tZeta\n"
    assert (
        mem.main(["terms", "add", "Zeta", "--soft"]) == 0
        and capsys.readouterr().out == "already listed\n"
    )
    assert terms.read_text().count("Zeta") == RC_USAGE
    assert mem.main(["terms", "add", "Zeta"]) == 0  # the hard class is another one
    capsys.readouterr()
    assert mem.main(["terms", "remove", "Zeta"]) == 0
    capsys.readouterr()
    assert mem.main(["terms", "list"]) == 0 and capsys.readouterr().out == "hard\tAcme Corp\n"
    assert terms.read_text().startswith("#")  # comments stay
    assert (
        mem.main(["terms", "remove", "Zeta"]) == RC_USAGE and "no term" in capsys.readouterr().err
    )


def test_terms_commands_need_no_store(capsys):
    assert mem.main(["terms", "add", "x"]) == 0


def test_terms_add_refuses_a_misparsed_term(capsys):
    assert mem.main(["terms", "add", "# x"]) == RC_USAGE
    assert mem.main(["terms", "add", "soft: x"]) == RC_USAGE


def test_init_creates_the_terms_file_once(tmp_path, capsys):
    terms = tmp_path / "mem-config" / "agent-memory" / "forbidden-terms"
    assert mem.main(["init", str(tmp_path / "store")]) == 0
    assert len(terms.read_text().splitlines()) == TERM_LINES
    terms.write_text("mine\n")
    assert mem.main(["init", str(tmp_path / "store2")]) == 0
    assert terms.read_text() == "mine\n"


# --- every command that writes text into the store runs the term check -----------------------------------------

SRC_LINE = "Sources: [attention](../knowledge/computing/attention-replaces-recurrence.md)"
NOTE_BODY = (
    "## Claim\n\n{}\n\n## Evidence\n\n- Experience (anonymized): seen.\n\n## Applies when\n\nAlways.\n\n"
    "## Does not apply when\n\nNever.\n"
)


def _file(tmp_path, text, name):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def _knowledge(slug, claim, body):
    return [
        "new",
        "knowledge",
        "--slug",
        slug,
        "--claim",
        claim,
        "--topics",
        "llm",
        "--confidence",
        "medium",
        "--level",
        "intermediate",
        "--origin",
        "experience",
        "--body-file",
        body,
    ]


def _synthesis(tmp_path):
    assert (
        mem.main([
            "synthesis",
            "new",
            "--title",
            "Attention",
            "--topics",
            "computing,ml",
            "--slug",
            "attention",
            "--summary-file",
            _file(tmp_path, "How attention works.\n", "s.md"),
        ])
        == 0
    )
    assert (
        mem.main([
            "synthesis",
            "add",
            "s:attention",
            "--section",
            "One",
            "--body-file",
            _file(tmp_path, f"First part.\n\n{SRC_LINE}\n", "p.md"),
        ])
        == 0
    )


def _two_notes(tmp_path):
    for slug, claim in (
        ("quartz-widgets-shrink", "Quartz widgets shrink under load"),
        ("amber-gadgets-expand", "Amber gadgets expand under heat"),
    ):
        assert (
            mem.main(
                _knowledge(slug, claim, _file(tmp_path, NOTE_BODY.format(claim), slug + ".md"))
            )
            == 0
        )


# case: (setup, argv(text, tmp_path), kind the text belongs to)
CASES = {
    "new-claim": (
        None,
        lambda t, p: _knowledge("zz", f"{t} widgets", _file(p, NOTE_BODY.format("Clean."), "b.md")),
        "note",
    ),
    "new-body": (
        None,
        lambda t, p: _knowledge("zz", "Clean claim", _file(p, NOTE_BODY.format(t), "b.md")),
        "note",
    ),
    "new-url": (
        None,
        lambda t, p: [
            "new",
            "literature",
            "--title",
            "A title",
            "--author",
            "Doe",
            "--year",
            "2020",
            "--kind",
            "web",
            "--level",
            "beginner",
            "--url",
            f"https://example.org/{t}",
            "--topics",
            "llm",
            "--slug",
            "zz",
        ],
        "note",
    ),
    "unify": (
        _two_notes,
        lambda t, p: [
            "unify",
            "quartz-widgets-shrink",
            "amber-gadgets-expand",
            "--body-file",
            _file(p, NOTE_BODY.format(t), "u.md"),
        ],
        "note",
    ),
    "synthesis-new": (
        None,
        lambda t, p: [
            "synthesis",
            "new",
            "--title",
            "Other",
            "--topics",
            "biology",
            "--slug",
            "other",
            "--summary-file",
            _file(p, f"About {t}.\n", "x.md"),
        ],
        "synthesis",
    ),
    "synthesis-add": (
        _synthesis,
        lambda t, p: [
            "synthesis",
            "add",
            "s:attention",
            "--section",
            "Two",
            "--body-file",
            _file(p, f"About {t}.\n\n{SRC_LINE}\n", "x.md"),
        ],
        "synthesis",
    ),
    "synthesis-append": (
        _synthesis,
        lambda t, p: [
            "synthesis",
            "append",
            "s:attention#one",
            "--body-file",
            _file(p, f"More about {t}.\n", "x.md"),
        ],
        "synthesis",
    ),
    "synthesis-edit": (
        _synthesis,
        lambda t, p: [
            "synthesis",
            "edit",
            "s:attention#one",
            "--body-file",
            _file(p, f"Rewritten about {t} and first part.\n\n{SRC_LINE}\n", "x.md"),
        ],
        "synthesis",
    ),
    "synthesis-add-note": (
        _synthesis,
        lambda t, p: [
            "synthesis",
            "add",
            "s:attention",
            "--section",
            "Two",
            "--body-file",
            _file(p, f"Second part.\n\n{SRC_LINE}\n", "x.md"),
            "--note-slug",
            "zz",
            "--note-claim",
            f"{t} widgets",
            "--note-body-file",
            _file(p, NOTE_BODY.format("Clean."), "n.md"),
            "--confidence",
            "medium",
            "--level",
            "intermediate",
        ],
        "note",
    ),
}


def _tree(root):
    return {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.fixture
def store_env(hub_root, monkeypatch):
    monkeypatch.setenv("MEM_STORE", str(hub_root))
    return hub_root


@pytest.mark.parametrize("case", CASES)
def test_every_store_write_runs_the_term_check(case, store_env, tmp_path, terms_file, capsys):
    hub_root = store_env
    setup, argv, kind = CASES[case]
    root = []
    if setup:
        setup(tmp_path)
        capsys.readouterr()
    work = tmp_path / "args"
    work.mkdir()
    before = _tree(hub_root)
    terms_file.write_text("zeta\n")
    assert mem.main([*root, *argv("zeta", work)]) == RC_FORBIDDEN
    assert "forbidden term" in capsys.readouterr().err and _tree(hub_root) == before
    terms_file.write_text("soft: zeta\n")
    assert mem.main([*root, *argv("zeta", work)]) == RC_SOFT
    assert "(a soft term)" in capsys.readouterr().err and _tree(hub_root) == before
    terms_file.write_text(f"soft[{kind}]: zeta\n")
    assert mem.main([*root, *argv("zeta", work)]) == RC_SOFT
    capsys.readouterr()
    assert mem.main([*root, *argv("zeta", work), "--owner-approved"]) == 0, capsys.readouterr().err
    assert _tree(hub_root) != before


def test_a_soft_term_of_the_other_kind_does_not_stop_a_note_or_a_synthesis(
    hub_root, tmp_path, terms_file, capsys
):
    argv_note = CASES["new-claim"][1]("zeta", tmp_path)
    terms_file.write_text("soft[synthesis]: zeta\nsoft[lesson]: zeta\n")
    assert mem.main(["--root", str(hub_root), *argv_note]) == 0
    argv_syn = CASES["synthesis-new"][1]("zeta", tmp_path)
    terms_file.write_text("soft[note]: zeta\n")
    assert mem.main(["--root", str(hub_root), *argv_syn]) == 0
