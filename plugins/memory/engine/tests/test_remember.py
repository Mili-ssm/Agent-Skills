import io
import json
import subprocess
from pathlib import Path

import pytest

import mem
import records


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    git(root, "init", "-q")
    monkeypatch.setenv("MEM_PROJECT", str(root))
    return root


@pytest.fixture
def gfolder(tmp_path, monkeypatch):
    folder = tmp_path / "gmem"
    monkeypatch.setenv("MEM_MEMORIES", str(folder))
    return folder


def forbid(tmp_path, *terms):
    f = tmp_path / "mem-config" / "agent-memory" / "forbidden-terms"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("".join(t + "\n" for t in terms), encoding="utf-8")


def remember(*extra, claim="Retries need idempotency keys.", kind="lesson"):
    return mem.main(["remember", "--kind", kind, "--claim", claim, *extra])


def test_project_write_needs_no_store(repo, capsys):
    assert remember() == 0
    assert capsys.readouterr().out == "m:retries-need-idempotency-keys\t.memory/retries-need-idempotency-keys.md\n"
    assert (repo / ".memory" / "retries-need-idempotency-keys.md").is_file()


def test_project_write_leaves_git_status_clean(repo):
    assert remember() == 0
    assert ".memory/" in (repo / ".git" / "info" / "exclude").read_text()
    assert git(repo, "status", "--porcelain") == ""


def test_outside_git_exits_2_and_writes_nothing(tmp_path, monkeypatch, capsys):
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)
    assert remember() == 2
    assert capsys.readouterr().err.strip() == "mem: not inside a git repository: pass --global, or set MEM_PROJECT to the project folder."
    assert list(plain.iterdir()) == []


def test_same_claim_exits_3_and_force_writes_a_second(repo, capsys):
    assert remember() == 0
    capsys.readouterr()
    assert remember() == 3
    err = capsys.readouterr().err
    assert "m:retries-need-idempotency-keys\tRetries need idempotency keys." in err
    assert 'run "mem observe m:retries-need-idempotency-keys"' in err and "--force" in err
    assert len(list((repo / ".memory").glob("*.md"))) == 1
    assert remember("--force") == 0
    assert (repo / ".memory" / "retries-need-idempotency-keys-2.md").is_file()


def test_negation_is_not_a_duplicate_but_is_listed(repo, capsys):
    assert remember() == 0
    capsys.readouterr()
    assert remember(claim="Retries do not need idempotency keys.") == 0
    err = capsys.readouterr().err
    assert 'related memories (if one is the same, run "mem observe m:<handle>"; if one says the opposite, keep both):' in err
    assert "m:retries-need-idempotency-keys\t[lesson, observed 1, " in err


def test_global_without_folder_exits_2(hub_root, monkeypatch, capsys):
    (hub_root / "mem-store.yaml").unlink()
    monkeypatch.setenv("MEM_STORE", str(hub_root))
    assert remember("--global") == 2
    assert capsys.readouterr().err.strip() == ('mem: no folder for global memories: set the plugin\'s "memories" option, '
                                               'or MEM_MEMORIES, or use a store made with "mem init".')


def test_global_in_a_marked_store(hub_root, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MEM_STORE", str(hub_root))
    forbid(tmp_path)
    assert remember("--global") == 0
    assert capsys.readouterr().out == "m:retries-need-idempotency-keys\tretries-need-idempotency-keys.md\n"
    assert (hub_root / "memories" / "retries-need-idempotency-keys.md").is_file()


def test_global_needs_the_forbidden_terms_file(gfolder, tmp_path, capsys):
    assert remember("--global") == 2
    err = capsys.readouterr().err.strip()
    assert err.startswith("mem: global memories need the file ") and str(tmp_path / "mem-config" / "agent-memory" / "forbidden-terms") in err
    assert not gfolder.exists()


def test_empty_forbidden_file_allows_global_write(gfolder, tmp_path):
    forbid(tmp_path)
    assert remember("--global") == 0
    assert any(gfolder.glob("*.md"))


@pytest.mark.parametrize("where", ["claim", "context", "body", "source"])
def test_forbidden_term_exits_4(gfolder, tmp_path, capsys, monkeypatch, where):
    forbid(tmp_path, "other", "acme")
    claim, extra = "Retries need keys.", []
    if where == "claim":
        claim = "Acme retries need keys."
    elif where == "context":
        extra = ["--context", "at ACME"]
    elif where == "source":
        extra = ["--source", "https://acme.example/x"]
    else:
        monkeypatch.setattr("sys.stdin", io.StringIO("seen at acme\n"))
        monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
        extra = ["--body-file", "-"]
    assert remember("--global", *extra, claim=claim) == 4
    assert capsys.readouterr().err.strip() == "mem: the text contains a forbidden term (line 2 of the forbidden-terms list); nothing was written."
    assert not gfolder.exists() or not list(gfolder.glob("*.md"))


def test_observe_raises_the_count(repo, capsys):
    remember()
    capsys.readouterr()
    assert mem.main(["observe", "m:retries-need-idempotency-keys"]) == 0
    assert capsys.readouterr().out == "m:retries-need-idempotency-keys\tobserved 2\n"
    [m] = records.load_memories(repo / ".memory", "project")
    assert m.observed == 2


def test_observe_falls_back_to_global(repo, gfolder, tmp_path, capsys):
    forbid(tmp_path)
    remember("--global")
    capsys.readouterr()
    assert mem.main(["observe", "m:retries-need-idempotency-keys"]) == 0
    assert capsys.readouterr().out.endswith("observed 2\n")


def test_observe_unknown_exits_2(repo, capsys):
    assert mem.main(["observe", "m:nope"]) == 2
    assert capsys.readouterr().err.strip() == "mem: no memory named m:nope"


def test_finding_needs_a_source(repo, capsys):
    assert remember(kind="finding") == 2
    assert "finding" in capsys.readouterr().err and not (repo / ".memory").exists()
    assert remember("--source", "https://example.org/a", kind="finding") == 0
    [m] = records.load_memories(repo / ".memory", "project")
    assert m.valid_until is not None


def test_body_file_from_stdin_and_empty_body(repo, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("Details here.\n"))
    monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
    assert remember("--body-file", "-") == 0
    [m] = records.load_memories(repo / ".memory", "project")
    assert m.body == "Details here.\n"
    empty = repo / "empty.txt"
    empty.write_text("")
    assert remember("--body-file", str(empty), claim="Another claim here.") == 0


@pytest.mark.parametrize("argv", [["--valid-until", "2026-13-01"], ["--kind", "rumor"]])
def test_argparse_rejects_bad_values(repo, argv):
    with pytest.raises(SystemExit) as e:
        mem.main(["remember", "--kind", "lesson", "--claim", "c", *argv])
    assert e.value.code == 2


def test_usage_log_has_command_and_scope_but_never_the_claim(repo):
    remember()
    text = (Path(__import__("os").environ["MEM_DATA"]) / "usage" / "log.jsonl").read_text()
    entry = json.loads(text.splitlines()[-1])
    assert entry["cmd"] == "remember" and entry["scope"] == "project"
    assert "idempotency" not in text


def test_init_creates_a_store_and_is_repeatable(tmp_path, capsys):
    folder = tmp_path / "s"
    assert mem.main(["init", str(folder)]) == 0
    assert (folder / "mem-store.yaml").read_text() == "format: 1\n"
    assert (folder / "topics.yaml").is_file()
    assert all((folder / d).is_dir() for d in ("literature", "knowledge", "research", "memories"))
    assert mem.main(["init", str(folder)]) == 0
    assert records.store_is_writable(folder)


def test_init_refuses_a_foreign_folder_but_accepts_git_files(tmp_path, capsys):
    foreign = tmp_path / "f"
    foreign.mkdir()
    (foreign / "notes.txt").write_text("x")
    assert mem.main(["init", str(foreign)]) == 2
    assert capsys.readouterr().err.strip() == f"mem: {foreign} is not empty and is not a store"
    ok = tmp_path / "g"
    ok.mkdir()
    git(ok, "init", "-q")
    (ok / ".gitignore").write_text("x\n")
    (ok / "README.md").write_text("r\n")
    assert mem.main(["init", str(ok)]) == 0
