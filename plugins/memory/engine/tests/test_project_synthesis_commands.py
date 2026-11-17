import subprocess

import pytest

import mem
import project_syntheses as ps


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args], cwd=cwd, check=True,
                   capture_output=True)


@pytest.fixture
def proj(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("a = 1\n")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "first")
    monkeypatch.setenv("MEM_PROJECT", str(root))
    monkeypatch.chdir(root)
    return root


def body_file(tmp_path, text="The engine lives in src."):
    f = tmp_path / "body.txt"
    f.write_text(text, encoding="utf-8")
    return str(f)


def add(tmp_path, heading="Where the engine lives", name="organization", paths="src/", text="The engine lives in src."):
    return mem.main(["project-synthesis", "add", name, heading, "--paths", paths, "--body-file",
                     body_file(tmp_path, text)])


def sha(root):
    return ps.head_commit(root)


def test_add_prints_the_handle(proj, tmp_path, capsys):
    assert add(tmp_path) == 0
    assert capsys.readouterr().out == "p:organization#where-the-engine-lives\n"
    (part,) = ps.load(proj / ".memory")["organization"]
    assert part.body == "The engine lives in src." and part.stamp.paths == ("src/",)


def test_add_reads_the_body_from_stdin(proj, monkeypatch, capsys):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("From stdin."))
    assert mem.main(["project-synthesis", "add", "plans", "Next", "--paths", "src/", "--body-file", "-"]) == 0
    assert ps.load(proj / ".memory")["plans"][0].body == "From stdin."


def test_confirm_prints_the_new_stamp_commit(proj, tmp_path, capsys):
    add(tmp_path)
    capsys.readouterr()
    (proj / "src" / "a.py").write_text("a = 2\n")
    git(proj, "commit", "-qam", "second")
    assert mem.main(["project-synthesis", "confirm", "p:organization#where-the-engine-lives"]) == 0
    assert capsys.readouterr().out == f"p:organization#where-the-engine-lives\tconfirmed at {sha(proj)}\n"


def test_list_prints_one_line_per_part(proj, tmp_path, capsys):
    add(tmp_path)
    add(tmp_path, heading="Second", name="plans")
    capsys.readouterr()
    assert mem.main(["project-synthesis", "list"]) == 0
    assert capsys.readouterr().out == ("p:organization#where-the-engine-lives\tfresh\tWhere the engine lives\n"
                                       "p:plans#second\tfresh\tSecond\n")


def test_list_prints_nothing_when_there_is_none(proj, capsys):
    assert mem.main(["project-synthesis", "list"]) == 0
    assert capsys.readouterr().out == ""


def test_show_a_name_prints_the_outline(proj, tmp_path, capsys):
    add(tmp_path)
    capsys.readouterr()
    assert mem.main(["show", "p:organization"]) == 0
    assert capsys.readouterr().out == "p:organization#where-the-engine-lives\tfresh\tWhere the engine lives\n"


def test_show_a_part_prints_heading_body_and_stamp(proj, tmp_path, capsys):
    add(tmp_path)
    capsys.readouterr()
    assert mem.main(["show", "p:organization#where-the-engine-lives"]) == 0
    assert capsys.readouterr().out == (
        f"== p:organization#where-the-engine-lives ({ps.describe(ps.FRESH)})\n"
        "Where the engine lives\n\nThe engine lives in src.\n"
        f"Covers: src/ | updated {ps.load(proj / '.memory')['organization'][0].stamp.date.isoformat()} at {sha(proj)}\n")


def test_show_marks_a_part_whose_files_changed(proj, tmp_path, capsys):
    add(tmp_path)
    (proj / "src" / "a.py").write_text("a = 2\n")
    git(proj, "commit", "-qam", "second")
    capsys.readouterr()
    assert mem.main(["show", "p:organization#where-the-engine-lives"]) == 0
    assert "possibly stale: its files changed" in capsys.readouterr().out.split("\n")[0]


def test_unknown_name_or_part_exits_2_and_names_the_parts(proj, tmp_path, capsys):
    add(tmp_path)
    capsys.readouterr()
    assert mem.main(["project-synthesis", "confirm", "p:organization#nope"]) == 2
    assert "where-the-engine-lives" in capsys.readouterr().err
    assert mem.main(["show", "p:organization#nope"]) == 2
    assert "where-the-engine-lives" in capsys.readouterr().err
    assert mem.main(["show", "p:nothing"]) == 2
    assert "organization" in capsys.readouterr().err


def test_outside_a_project_exits_2(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("MEM_PROJECT")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    assert mem.main(["project-synthesis", "list"]) == 2
    assert "mem: not inside a project" in capsys.readouterr().err
    assert mem.main(["show", "p:organization"]) == 2
    assert "mem: not inside a project" in capsys.readouterr().err


def test_a_secret_in_the_body_exits_4_and_writes_nothing(proj, tmp_path, capsys):
    secret = "password = hunter2hunter2hunter2\napi_key = AKIAABCDEFGHIJKLMNOP"
    assert add(tmp_path, text=secret) == 4
    assert "secret" in capsys.readouterr().err
    assert not (proj / ".memory" / "syntheses").exists()


def test_the_command_and_show_work_without_a_store(proj, tmp_path, monkeypatch, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    for var in ("XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(var, str(empty))
    monkeypatch.delenv("MEM_STORE", raising=False)
    assert add(tmp_path) == 0
    assert mem.main(["project-synthesis", "list"]) == 0
    assert mem.main(["show", "p:organization"]) == 0


def test_the_store_is_untouched(proj, hub_root, tmp_path, monkeypatch):
    monkeypatch.setenv("MEM_STORE", str(hub_root))
    before = sorted((p.relative_to(hub_root), p.read_bytes()) for p in hub_root.rglob("*") if p.is_file())
    assert add(tmp_path) == 0
    assert mem.main(["show", "p:organization"]) == 0
    after = sorted((p.relative_to(hub_root), p.read_bytes()) for p in hub_root.rglob("*") if p.is_file())
    assert before == after


def test_add_over_uncommitted_changes_warns_and_still_writes(proj, tmp_path, capsys):
    (proj / "src" / "a.py").write_text("a = 2\n")
    assert add(tmp_path) == 0
    cap = capsys.readouterr()
    ref = "p:organization#where-the-engine-lives"
    assert cap.out == ref + "\n"
    assert cap.err == (f"mem: {ref} covers files with uncommitted changes; "
                       "it will read possibly stale until you confirm it after committing.\n")


def test_add_over_a_clean_tree_does_not_warn(proj, tmp_path, capsys):
    assert add(tmp_path) == 0
    assert capsys.readouterr().err == ""


def test_confirm_over_uncommitted_changes_warns(proj, tmp_path, capsys):
    add(tmp_path)
    (proj / "src" / "a.py").write_text("a = 2\n")
    capsys.readouterr()
    ref = "p:organization#where-the-engine-lives"
    assert mem.main(["project-synthesis", "confirm", ref]) == 0
    assert capsys.readouterr().err == (f"mem: {ref} covers files with uncommitted changes; "
                                       "it will read possibly stale until you confirm it after committing.\n")


def test_show_p_handle_rejects_project_and_section(proj, tmp_path, capsys):
    add(tmp_path)
    capsys.readouterr()
    assert mem.main(["show", "p:organization", "--project", "x"]) == 2  # an unknown project is refused first
    capsys.readouterr()
    assert mem.main(["show", "p:organization", "--section", "y"]) == 2
    err = capsys.readouterr().err
    assert err.count("\n") == 1 and "do not apply to `p:` handles" in err


def test_a_refused_p_handle_does_not_hide_a_memory_in_the_same_call(proj, tmp_path, capsys):
    add(tmp_path)
    assert mem.main(["remember", "--kind", "lesson", "--claim", "Tests seed one memory here"]) == 0
    handle = capsys.readouterr().out.split()[0]
    assert mem.main(["show", "p:organization", handle, "--section", "y"]) == 2
    out = capsys.readouterr().out
    assert "== p:organization\n(not found)" in out and handle in out


def test_trailing_hash_exits_2(proj, tmp_path, capsys):
    add(tmp_path)
    capsys.readouterr()
    assert mem.main(["show", "p:organization#"]) == 2
    assert "mem:" in capsys.readouterr().err
    assert mem.main(["project-synthesis", "confirm", "p:organization#"]) == 2
    assert "mem:" in capsys.readouterr().err


def test_paths_are_trimmed_and_empty_items_dropped(proj, tmp_path):
    (proj / "lib.txt").write_text("x\n")
    git(proj, "add", "-A")
    git(proj, "commit", "-q", "-m", "lib")
    assert add(tmp_path, paths="src/, lib.txt") == 0
    assert add(tmp_path, heading="Second", paths="src/,") == 0
    parts = {p.heading: p for p in ps.load(proj / ".memory")["organization"]}
    assert parts["Where the engine lives"].stamp.paths == ("src/", "lib.txt")
    assert parts["Second"].stamp.paths == ("src/",)


def test_paths_with_nothing_left_exit_2(proj, tmp_path, capsys):
    assert add(tmp_path, paths=" , ") == 2
    assert "at least one path" in capsys.readouterr().err


def test_a_bad_path_is_reported_before_the_secret_scan(proj, tmp_path, capsys):
    secret = "password = hunter2hunter2hunter2\napi_key = AKIAABCDEFGHIJKLMNOP"
    assert add(tmp_path, paths="nope/", text=secret) == 2
    assert "does not exist" in capsys.readouterr().err


def test_a_bad_name_is_reported_before_the_secret_scan(proj, tmp_path, capsys):
    secret = "password = hunter2hunter2hunter2\napi_key = AKIAABCDEFGHIJKLMNOP"
    assert add(tmp_path, name="organisation", text=secret) == 2
    err = capsys.readouterr().err
    assert "unknown project synthesis" in err and "secret" not in err


def test_show_mixes_a_p_handle_and_a_memory(proj, tmp_path, capsys):
    add(tmp_path)
    assert mem.main(["remember", "--kind", "lesson", "--claim", "A fact.", "--body-file",
                     body_file(tmp_path, "Fact body.")]) == 0
    handle = next((proj / ".memory").glob("*.md")).stem
    capsys.readouterr()
    assert mem.main(["show", "p:organization#where-the-engine-lives", f"m:{handle}"]) == 0
    out = capsys.readouterr().out
    assert "== p:organization#where-the-engine-lives" in out and "Fact body." in out
