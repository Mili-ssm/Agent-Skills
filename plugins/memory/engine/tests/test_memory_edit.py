"""`mem memory edit`: a memory's claim, context or body, through the guard, with undo."""

import subprocess

import mem
import pytest
from patching import patch_all

RC_USAGE = 2  # `mem` exit code for a refused edit or bad usage
RC_REFUSED = 4  # a hard refusal: a secret or a forbidden term
FAKE_TOKEN = "ghp_" + "a" * 36  # built from parts: obviously fake
BODY = (
    "Retries must carry an idempotency key so a repeated request is never applied twice by the server.\n"
    "See [the spec](https://example.org/spec) for the exact header name and its lifetime.\n"
)


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    monkeypatch.setenv("MEM_PROJECT", str(root))
    return root / ".memory"


@pytest.fixture
def gfolder(tmp_path, monkeypatch):
    folder = tmp_path / "gmem"
    monkeypatch.setenv("MEM_MEMORIES", str(folder))
    return folder


def put(
    folder,
    handle="retry-keys",
    claim="Retries need idempotency keys to stay safe.",
    body=BODY,
    context="old context",
):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{handle}.md"
    path.write_text(
        f"---\nkind: lesson\nclaim: {claim}\ncreated: '2026-11-01'\nobserved: 2\nstatus: active\n"
        f"context: {context}\nextra_key: keep\n---\n{body}",
        encoding="utf-8",
    )
    return path


def run(capsys, *argv):
    code = mem.main(["memory", "edit", *argv])
    out = capsys.readouterr()
    return code, out.out, out.err


def body_file(tmp_path, text):
    path = tmp_path / "body.md"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_claim_context_and_body_change_and_the_rest_stays(project, capsys, tmp_path):
    path = put(project)
    new = BODY + "A third line about retries and their keys.\n"
    code, out, _ = run(
        capsys,
        "m:retry-keys",
        "--claim",
        "  Retries   need   idempotency keys to stay safe always. ",
        "--context",
        "new context",
        "--body-file",
        body_file(tmp_path, new),
    )
    assert (code, out) == (0, "m:retry-keys\tedited claim, context, body\n")
    text = path.read_text()
    assert (
        "claim: Retries need idempotency keys to stay safe always." in text
        and "context: new context" in text
    )
    assert text.endswith(f"---\n{new}")
    assert "extra_key: keep" in text and "observed: 2" in text


def test_each_field_alone_and_an_empty_context_removes_it(project, capsys):
    path = put(project)
    assert run(capsys, "m:retry-keys", "--context", "")[1] == "m:retry-keys\tedited context\n"
    assert "context:" not in path.read_text()
    assert (
        run(
            capsys, "m:retry-keys", "--claim", "Retries need idempotency keys to stay safe always."
        )[1]
        == "m:retry-keys\tedited claim\n"
    )
    assert path.read_text().endswith(f"---\n{BODY}")


def test_no_field_is_an_error(project, capsys):
    put(project)
    with pytest.raises(SystemExit) as exc:
        run(capsys, "m:retry-keys")
    assert exc.value.code == RC_USAGE


def test_missing_memory_exits_2(project, capsys):
    put(project)
    code, _, err = run(capsys, "m:ghost", "--claim", "x y")
    assert code == RC_USAGE and "no memory named" in err


def test_body_guard_refuses_a_shrink_until_shrink_is_given(project, capsys, tmp_path):
    path = put(project)
    before = path.read_bytes()
    code, _, err = run(capsys, "m:retry-keys", "--body-file", body_file(tmp_path, "Short.\n"))
    assert code == RC_USAGE and "--shrink" in err and path.read_bytes() == before
    assert (
        run(capsys, "m:retry-keys", "--body-file", body_file(tmp_path, "Short.\n"), "--shrink")[0]
        == 0
    )
    assert path.read_text().endswith("---\nShort.\n")


def test_body_guard_refuses_a_lost_link(project, capsys, tmp_path):
    path = put(project)
    before = path.read_bytes()
    new = BODY.replace("[the spec](https://example.org/spec)", "the spec")
    code, _, err = run(capsys, "m:retry-keys", "--body-file", body_file(tmp_path, new))
    assert code == RC_USAGE and "link" in err and path.read_bytes() == before


def test_claim_guard_has_no_sentence_rule_but_checks_the_word_ratio(project, capsys):
    put(project, claim="Retries need idempotency keys to stay safe under load today.")
    assert (
        run(capsys, "m:retry-keys", "--claim", "Retries need keys to stay safe under load.")[0] == 0
    )
    code, _, err = run(capsys, "m:retry-keys", "--claim", "Retries.")
    assert code == RC_USAGE and "--shrink" in err
    assert run(capsys, "m:retry-keys", "--claim", "Retries.", "--shrink")[0] == 0


def test_secret_is_refused_with_exit_4_and_nothing_written(project, capsys, tmp_path):
    path = put(project)
    before = path.read_bytes()
    for args in (
        ("--claim", f"Use {FAKE_TOKEN} for it."),
        ("--context", FAKE_TOKEN),
        ("--body-file", body_file(tmp_path, BODY + FAKE_TOKEN + "\n")),
    ):
        code, _, err = run(capsys, "m:retry-keys", *args)
        assert code == RC_REFUSED and "secret" in err and path.read_bytes() == before
    assert not (project / ".curation-log").exists()


def test_forbidden_term_refuses_a_global_memory_but_not_a_project_one(
    project, gfolder, capsys, tmp_path
):
    terms = tmp_path / "mem-config" / "agent-memory" / "forbidden-terms"
    terms.parent.mkdir(parents=True)
    terms.write_text("acme\n")
    g = put(gfolder, handle="g-one")
    before = g.read_bytes()
    code, _, err = run(
        capsys, "m:g-one", "--global", "--claim", "Acme needs idempotency keys to stay safe."
    )
    assert code == RC_REFUSED and "forbidden term" in err and g.read_bytes() == before
    p = put(project, handle="p-one")
    assert run(capsys, "m:p-one", "--claim", "Acme needs idempotency keys to stay safe.")[0] == 0
    assert "claim: Acme needs idempotency keys to stay safe." in p.read_text()


def test_restore_puts_the_previous_bytes_back(project, capsys, tmp_path):
    path = put(project)
    before = path.read_bytes()
    assert (
        run(
            capsys,
            "m:retry-keys",
            "--claim",
            "Changed claim needs idempotency keys to stay.",
            "--context",
            "other",
        )[0]
        == 0
    )
    assert path.read_bytes() != before
    assert mem.main(["restore", "m:retry-keys"]) == 0
    capsys.readouterr()
    assert path.read_bytes() == before


def test_global_flag_picks_the_global_memory_when_both_scopes_hold_the_handle(
    project, gfolder, capsys
):
    p, g = put(project), put(gfolder)
    assert (
        run(
            capsys,
            "m:retry-keys",
            "--global",
            "--claim",
            "Global claim needs idempotency keys to stay.",
        )[0]
        == 0
    )
    assert (
        "Global claim needs idempotency keys to stay." in g.read_text()
        and "Global claim needs idempotency keys to stay." not in p.read_text()
    )
    assert (
        run(capsys, "m:retry-keys", "--claim", "Project claim needs idempotency keys to stay.")[0]
        == 0
    )
    assert "Project claim needs idempotency keys to stay." in p.read_text()


def test_a_file_changed_since_it_was_read_is_refused(project, capsys, monkeypatch):
    path = put(project)
    other = path.read_bytes() + b"concurrent\n"
    real = mem.records.log_before

    def racing(memory, action):
        real(memory, action)
        path.write_bytes(other)  # another writer lands between the read and the swap

    patch_all(monkeypatch, "log_before", racing)
    code, _, err = run(
        capsys, "m:retry-keys", "--claim", "Changed claim needs idempotency keys to stay."
    )
    assert code == RC_USAGE and "changed since" in err and path.read_bytes() == other
    assert not (project / ".curation-log").exists()


def test_a_failure_after_the_swap_puts_the_file_and_the_log_back(project, capsys, monkeypatch):
    path = put(project)
    before = path.read_bytes()

    real = mem.records.update

    def boom(*a, **k):
        real(*a, **k)  # the swap happened; the read-back then fails
        raise OSError("read-back failed")

    patch_all(monkeypatch, "update", boom)
    code, _, err = run(
        capsys, "m:retry-keys", "--claim", "Changed claim needs idempotency keys to stay."
    )
    assert code == RC_USAGE and "read-back failed" in err
    assert path.read_bytes() == before and not (project / ".curation-log").exists()


@pytest.mark.parametrize("status", ["refuted", "forgotten", "superseded"])
def test_a_retired_memory_is_refused_and_an_active_one_accepted(project, capsys, status):
    path = put(project)
    path.write_text(path.read_text().replace("status: active", f"status: {status}"))
    before = path.read_bytes()
    code, _, err = run(capsys, "m:retry-keys", "--context", "new")
    assert code == RC_USAGE and "mem restore" in err and path.read_bytes() == before
    path.write_text(path.read_text().replace(f"status: {status}", "status: active"))
    assert run(capsys, "m:retry-keys", "--context", "new")[0] == 0
