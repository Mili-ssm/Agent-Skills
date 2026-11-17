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


def _marker_less_store(tmp_path, monkeypatch):
    store = tmp_path / "store"
    (store / "knowledge").mkdir(parents=True)
    monkeypatch.setenv("MEM_STORE", str(store))
    return store


@pytest.mark.parametrize("inner", [False, True])
def test_project_inside_a_marker_less_store_is_refused(tmp_path, monkeypatch, capsys, inner):
    store = _marker_less_store(tmp_path, monkeypatch)
    root = store / "sub" if inner else store
    root.mkdir(exist_ok=True)
    git(root, "init", "-q")
    monkeypatch.setenv("MEM_PROJECT", str(root))
    assert remember() == 2
    assert capsys.readouterr().err.strip() == ("mem: this project is the store, which is read-only: it has no "
                                               "mem-store.yaml; a memory cannot be written here.")
    assert not (root / ".memory").exists()
    assert ".memory" not in (root / ".git" / "info" / "exclude").read_text() if (root / ".git" / "info" / "exclude").exists() else True


def test_observe_in_a_marker_less_store_is_refused(tmp_path, monkeypatch, capsys):
    store = _marker_less_store(tmp_path, monkeypatch)
    git(store, "init", "-q")
    monkeypatch.setenv("MEM_PROJECT", str(store))
    (store / ".memory").mkdir()
    (store / ".memory" / "x.md").write_text("---\nkind: lesson\nclaim: X thing.\n---\n")
    assert mem.main(["observe", "m:x"]) == 2
    assert "read-only" in capsys.readouterr().err
    assert "observed" not in (store / ".memory" / "x.md").read_text()


def test_named_memories_folder_inside_a_marker_less_store_is_refused(tmp_path, monkeypatch, capsys):
    store = _marker_less_store(tmp_path, monkeypatch)
    folder = store / "mine"
    monkeypatch.setenv("MEM_MEMORIES", str(folder))
    forbid(tmp_path)
    assert remember("--global") == 2
    assert capsys.readouterr().err.strip() == "mem: the memories folder is inside the store, which is read-only: it has no mem-store.yaml."
    assert not folder.exists()
    folder.mkdir()
    (folder / "x.md").write_text("---\nkind: lesson\nclaim: X thing.\n---\n")
    assert mem.main(["observe", "m:x"]) == 2
    assert "observed" not in (folder / "x.md").read_text()


def test_symlinked_project_memory_folder_into_a_marker_less_store_is_refused(tmp_path, monkeypatch, capsys):
    store = _marker_less_store(tmp_path, monkeypatch)
    target = store / "knowledge"
    proj = tmp_path / "proj"
    proj.mkdir()
    git(proj, "init", "-q")
    (proj / ".memory").symlink_to(target, target_is_directory=True)
    monkeypatch.setenv("MEM_PROJECT", str(proj))
    assert remember() == 2
    assert "read-only" in capsys.readouterr().err
    assert list(target.iterdir()) == []
    (target / "x.md").write_text("---\nkind: lesson\nclaim: X thing.\n---\n")
    assert mem.main(["observe", "m:x"]) == 2
    assert "observed" not in (target / "x.md").read_text()


def test_symlinked_global_memories_folder_into_a_marker_less_store_is_refused(tmp_path, monkeypatch, capsys):
    store = _marker_less_store(tmp_path, monkeypatch)
    target = store / "knowledge"
    link = tmp_path / "glink"
    link.symlink_to(target, target_is_directory=True)
    monkeypatch.setenv("MEM_MEMORIES", str(link))
    forbid(tmp_path)
    assert remember("--global") == 2
    assert "read-only" in capsys.readouterr().err
    assert list(target.iterdir()) == []


def test_init_refuses_an_existing_store_without_marker(tmp_path, capsys):
    for entry in ("literature", "knowledge", "research", "topics.yaml"):
        folder = tmp_path / entry.replace(".", "_")
        folder.mkdir()
        (folder / entry).mkdir() if "." not in entry else (folder / entry).write_text("{}\n")
        assert mem.main(["init", str(folder)]) == 2
        assert capsys.readouterr().err.strip() == (f"mem: {folder} already holds a store without mem-store.yaml; it stays "
                                                   "read-only (add the file by hand only if you own it and mean to write to it).")
        assert not (folder / "mem-store.yaml").exists()


def test_init_on_a_marked_store_changes_nothing(tmp_path):
    assert mem.main(["init", str(tmp_path / "s")]) == 0
    (tmp_path / "s" / "topics.yaml").unlink()
    assert mem.main(["init", str(tmp_path / "s")]) == 0
    assert not (tmp_path / "s" / "topics.yaml").exists()


def test_global_write_fails_closed_on_an_unreadable_forbidden_list(gfolder, tmp_path, capsys):
    f = tmp_path / "mem-config" / "agent-memory" / "forbidden-terms"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"\xff\xfe\x80\n")
    assert remember("--global") == 2
    assert capsys.readouterr().err.strip() == f"mem: the forbidden-terms list cannot be read ({f}); nothing was written."
    assert not gfolder.exists()


def test_forbidden_term_split_between_claim_and_body(gfolder, tmp_path, capsys, monkeypatch):
    forbid(tmp_path, "acme corp")
    monkeypatch.setattr("sys.stdin", io.StringIO("corp\n"))
    monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
    assert remember("--global", "--body-file", "-", claim="Seen at Acme") == 4


def test_failed_exclusion_warns_but_writes(repo, capsys, monkeypatch):
    def boom(project):
        raise OSError("denied")
    monkeypatch.setattr(records, "ensure_excluded", boom)
    assert remember() == 0
    cap = capsys.readouterr()
    assert (repo / ".memory" / "retries-need-idempotency-keys.md").is_file()
    assert "mem: could not add .memory/ to .git/info/exclude; the folder may appear in git status." in cap.err


def test_distinct_non_latin_claims_are_not_duplicates(repo, capsys):
    assert remember(claim="重试需要键") == 0
    assert remember(claim="超时需要设置") == 0
    assert remember(claim="重试需要键") == 3


def test_claim_whitespace_is_collapsed_and_empty_is_rejected(repo, capsys):
    assert remember("--context", "a\tb\nc", claim="Line one\n\ttwo  three") == 0
    out = capsys.readouterr().out
    assert out.count("\n") == 1 and out.startswith("m:line-one-two-three\t")
    assert "claim: Line one two three" in (repo / ".memory" / "line-one-two-three.md").read_text()
    assert "context: a b c" in (repo / ".memory" / "line-one-two-three.md").read_text()
    assert remember(claim=" \n\t ") == 2


def test_rejected_call_leaves_no_exclude_line(repo, capsys):
    assert remember(claim=" ") == 2
    assert remember(claim="A finding.", kind="finding") == 2
    assert not (repo / ".memory").exists()
    ex = repo / ".git" / "info" / "exclude"
    assert not ex.exists() or ".memory" not in ex.read_text()


def test_document_needs_a_source_and_takes_a_path(repo, capsys):
    assert remember(kind="document") == 2
    assert "document" in capsys.readouterr().err and not (repo / ".memory").exists()
    assert remember("--source", "docs/spec.pdf", kind="document") == 0
    text = (repo / ".memory" / "retries-need-idempotency-keys.md").read_text()
    assert "docs/spec.pdf" in text and "valid_until" not in text


def test_document_in_global_scope_checks_forbidden_terms_in_sources(gfolder, tmp_path, capsys):
    forbid(tmp_path, "acme")
    assert remember("--global", "--source", "/srv/ACME/spec.pdf", kind="document") == 4
    assert remember("--global", "--source", "/srv/other/spec.pdf", kind="document") == 0
