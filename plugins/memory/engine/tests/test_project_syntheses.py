import datetime
import subprocess
from pathlib import Path

import pytest
from store import project_syntheses as ps

TODAY = datetime.date(2026, 11, 17)
GIT_TIMEOUT = 2
MIN_GIT_CALLS = 5
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.com"]


def git(cwd, *args):
    subprocess.run([*GIT, *args], cwd=cwd, check=True, capture_output=True)


def commit(cwd, message="c"):
    git(cwd, "add", "-A")
    git(cwd, "commit", "-q", "-m", message)


@pytest.fixture
def git_project(tmp_path):
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "src" / "a.py").write_text("a = 1\n")
    (root / "docs" / "p.md").write_text("plan\n")
    git(root, "init", "-q", "-b", "main")
    commit(root, "first")
    return root


@pytest.fixture
def mem_dir(git_project):
    return git_project / ".memory"


def write(mem_dir, tree, paths=("src/",), heading="Where the engine lives", body="Text."):
    return ps.write_part(
        mem_dir, tree, ps.NewPart("organization", heading, body, list(paths)), TODAY
    )


def stamp_of(mem_dir, handle="where-the-engine-lives"):
    return next(p for p in ps.load(mem_dir)["organization"] if p.handle == handle).stamp


def test_first_part_creates_the_file_with_a_stamp(git_project, mem_dir):
    handle = write(mem_dir, git_project)
    assert handle == "where-the-engine-lives"
    lines = (mem_dir / "syntheses" / "organization.md").read_text().rstrip("\n").split("\n")
    assert lines[-1] == f"Covers: src/ | updated 2026-11-17 at {ps.head_commit(git_project)}"
    (part,) = ps.load(mem_dir)["organization"]
    assert part.handle == "where-the-engine-lives" and part.body == "Text."
    assert part.stamp.paths == ("src/",) and part.stamp.date == TODAY


def test_same_heading_replaces_and_keeps_order(git_project, mem_dir):
    write(mem_dir, git_project)
    write(mem_dir, git_project, heading="Second", body="Two.")
    write(mem_dir, git_project, heading="Where the engine lives", body="New text.")
    parts = ps.load(mem_dir)["organization"]
    assert [p.handle for p in parts] == ["where-the-engine-lives", "second"]
    assert [p.body for p in parts] == ["New text.", "Two."]


def test_unknown_name_is_refused(git_project, mem_dir):
    with pytest.raises(ps.ProjectSynthesisError):
        ps.write_part(mem_dir, git_project, ps.NewPart("notes", "H", "T", ["src/"]), TODAY)


@pytest.mark.parametrize(
    "paths",
    [
        [],
        ["../x"],
        ["/etc"],
        [""],
        ["a,b"],
        ["a|b"],
        [".memory/x"],
        ["missing/"],
        ["./.memory"],
        ["./.memory/x"],
        ["src/../.memory"],
        ["src/../../x"],
    ],
)
def test_bad_paths_are_refused(git_project, mem_dir, paths):
    (git_project / ".memory" / "x").mkdir(parents=True)
    with pytest.raises(ps.ProjectSynthesisError):
        write(mem_dir, git_project, paths=paths)
    assert not (mem_dir / "syntheses").exists()


@pytest.mark.parametrize(
    "body", ["a\n## Other\nb", "a\nCovers: src/ | updated 2026-11-17 at no-commit"]
)
def test_body_with_a_heading_or_a_stamp_is_refused(git_project, mem_dir, body):
    with pytest.raises(ps.ProjectSynthesisError):
        write(mem_dir, git_project, body=body)


def test_heading_without_letters_or_digits_is_refused(git_project, mem_dir):
    with pytest.raises(ps.ProjectSynthesisError):
        write(mem_dir, git_project, heading="¿?")


def test_fresh_then_changed_by_a_commit_then_fresh_after_confirm(git_project, mem_dir):
    write(mem_dir, git_project)
    assert ps.freshness(git_project, stamp_of(mem_dir)) == ps.FRESH
    (git_project / "docs" / "p.md").write_text("other\n")
    commit(git_project, "docs")
    assert ps.freshness(git_project, stamp_of(mem_dir)) == ps.FRESH
    (git_project / "src" / "a.py").write_text("a = 2\n")
    commit(git_project, "src")
    assert ps.freshness(git_project, stamp_of(mem_dir)) == ps.CHANGED
    path = mem_dir / "syntheses" / "organization.md"
    before = ps.load(mem_dir)["organization"][0].body
    ps.confirm_part(mem_dir, git_project, "organization", "where-the-engine-lives", TODAY)
    assert ps.freshness(git_project, stamp_of(mem_dir)) == ps.FRESH
    assert ps.load(mem_dir)["organization"][0].body == before
    assert path.read_text().rstrip("\n").endswith(f"at {ps.head_commit(git_project)}")


def test_uncommitted_change_new_file_and_deleted_path_are_changed(git_project, mem_dir):
    write(mem_dir, git_project)
    write(mem_dir, git_project, heading="Docs", paths=["docs/p.md"])
    src, doc = stamp_of(mem_dir), stamp_of(mem_dir, "docs")
    (git_project / "src" / "a.py").write_text("a = 3\n")
    assert ps.freshness(git_project, src) == ps.CHANGED
    git(git_project, "checkout", "--", "src/a.py")
    assert ps.freshness(git_project, src) == ps.FRESH
    (git_project / "src" / "new.py").write_text("n\n")
    assert ps.freshness(git_project, src) == ps.CHANGED
    (git_project / "docs" / "p.md").unlink()
    assert ps.freshness(git_project, doc) == ps.CHANGED


def test_a_branch_whose_files_differ_is_changed(git_project, mem_dir):
    git(git_project, "checkout", "-q", "-b", "other")
    (git_project / "src" / "a.py").write_text("a = 9\n")
    commit(git_project, "other")
    git(git_project, "checkout", "-q", "main")
    write(mem_dir, git_project)
    assert ps.freshness(git_project, stamp_of(mem_dir)) == ps.FRESH
    git(git_project, "checkout", "-q", "other")
    assert ps.freshness(git_project, stamp_of(mem_dir)) == ps.CHANGED


def test_a_linked_worktree_stamps_its_own_head(git_project, mem_dir, tmp_path, monkeypatch):
    git(git_project, "branch", "ahead")
    linked = tmp_path / "linked"
    git(git_project, "worktree", "add", "-q", str(linked), "ahead")
    (linked / "docs" / "p.md").write_text("ahead\n")
    commit(linked, "ahead")
    monkeypatch.delenv("MEM_PROJECT", raising=False)
    tree = ps.worktree(linked, git_project, {})
    assert tree.resolve() == linked.resolve()
    write(mem_dir, tree, paths=["docs/"])
    assert stamp_of(mem_dir).commit == ps.head_commit(linked) != ps.head_commit(git_project)
    assert ps.freshness(tree, stamp_of(mem_dir)) == ps.FRESH


def test_a_part_covering_the_root_stays_fresh_when_another_part_is_written(git_project, mem_dir):
    write(mem_dir, git_project, paths=["."])
    write(mem_dir, git_project, heading="Another", paths=["src/"])
    assert ps.freshness(git_project, stamp_of(mem_dir)) == ps.FRESH


def test_no_git_and_missing_commit_are_unknown(tmp_path, git_project, mem_dir):
    plain = tmp_path / "plain"
    (plain / "src").mkdir(parents=True)
    plain_mem = plain / ".memory"
    assert ps.head_commit(plain) is None
    write(plain_mem, plain)
    assert (
        (plain_mem / "syntheses" / "organization.md")
        .read_text()
        .rstrip("\n")
        .endswith("at no-commit")
    )
    stamp = stamp_of(plain_mem)
    assert stamp.commit is None and ps.freshness(plain, stamp) == ps.UNKNOWN
    assert ps.freshness(git_project, ps.Stamp(("src/",), TODAY, "0" * 12)) == ps.UNKNOWN


def test_worktree_rule(git_project, tmp_path):
    linked = tmp_path / "linked"
    git(git_project, "worktree", "add", "-q", str(linked), "-b", "side")
    plain = tmp_path / "plain"
    plain.mkdir()
    assert ps.worktree(linked, git_project, {"MEM_PROJECT": str(git_project)}) == git_project
    assert ps.worktree(linked, git_project, {}).resolve() == linked.resolve()
    assert ps.worktree(plain, git_project, {}) == git_project


def test_git_timeout_is_unknown(git_project, mem_dir, monkeypatch):
    write(mem_dir, git_project)
    stamp = stamp_of(mem_dir)

    def boom(*a, **k):
        raise subprocess.TimeoutExpired("git", 2)

    monkeypatch.setattr(subprocess, "run", boom)
    assert ps.freshness(git_project, stamp) == ps.UNKNOWN
    assert ps.head_commit(git_project) is None


def test_describe_texts():
    assert ps.describe(ps.FRESH) == "fresh: its files are as they were when it was written"
    assert (
        ps.describe(ps.CHANGED)
        == "possibly stale: its files changed since it was written; check them before relying on it"
    )
    assert (
        ps.describe(ps.UNKNOWN)
        == "unknown: not a git project or its commit is gone; check the files"
    )


def test_body_leaving_a_code_fence_open_is_refused(git_project, mem_dir):
    with pytest.raises(ps.ProjectSynthesisError):
        write(mem_dir, git_project, heading="First", body="```\ncode open")
    assert not (mem_dir / "syntheses").exists()
    write(mem_dir, git_project, heading="First", body="```\ncode\n```")
    write(mem_dir, git_project, heading="Second")
    assert [p.handle for p in ps.load(mem_dir)["organization"]] == ["first", "second"]


def test_a_part_covering_the_root_of_a_subfolder_project_stays_fresh(tmp_path):
    repo = tmp_path / "repo"
    proj = repo / "proj"
    (proj / "src").mkdir(parents=True)
    (proj / "src" / "a.py").write_text("a\n")
    git(repo, "init", "-q", "-b", "main")
    commit(repo)
    mem = proj / ".memory"
    write(mem, proj, paths=["."])
    write(mem, proj, heading="Another", paths=["src/"])
    assert ps.freshness(proj, stamp_of(mem)) == ps.FRESH
    (proj / "src" / "a.py").write_text("b\n")
    assert ps.freshness(proj, stamp_of(mem)) == ps.CHANGED


def test_a_tracked_memory_folder_is_ignored_under_diff_relative(tmp_path):
    repo = tmp_path / "repo"
    proj = repo / "proj"
    (proj / "src").mkdir(parents=True)
    (proj / "src" / "a.py").write_text("a\n")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "diff.relative", "true")  # makes --name-only names relative to the cwd
    mem = proj / ".memory"
    write(mem, proj, heading="Another", paths=["src/"])
    commit(repo)  # .memory/ is tracked here
    write(mem, proj, paths=["."])
    write(mem, proj, heading="Another", body="Changed.", paths=["src/"])
    assert ps.freshness(proj, stamp_of(mem)) == ps.FRESH


def test_worktree_runs_git_through_the_timeout_helper(git_project, monkeypatch):
    seen = []
    real = subprocess.run

    def spy(*a, **k):
        seen.append(k)
        return real(*a, **k)

    monkeypatch.setattr(subprocess, "run", spy)
    assert (
        ps.worktree(git_project, Path("/nonexistent-root"), {}).resolve() == git_project.resolve()
    )
    assert seen and all(k.get("timeout") == GIT_TIMEOUT for k in seen)

    def boom(*a, **k):
        raise subprocess.TimeoutExpired("git", 2)

    monkeypatch.setattr(subprocess, "run", boom)
    assert ps.worktree(git_project, git_project / "root", {}) == git_project / "root"


def test_write_and_confirm_bump_updated_and_keep_created(git_project, mem_dir):
    path = mem_dir / "syntheses" / "organization.md"
    write(mem_dir, git_project)
    day2, day3 = datetime.date(2026, 11, 18), datetime.date(2026, 11, 19)
    ps.write_part(
        mem_dir, git_project, ps.NewPart("organization", "Second", "Two.", ["src/"]), day2
    )
    text = path.read_text()
    assert "created: '2026-11-17'" in text or "created: 2026-11-17" in text
    assert "updated: '2026-11-18'" in text
    ps.confirm_part(mem_dir, git_project, "organization", "second", day3)
    text = path.read_text()
    assert "updated: '2026-11-19'" in text and (
        "created: '2026-11-17'" in text or "created: 2026-11-17" in text
    )


def test_every_git_call_has_the_timeout(git_project, mem_dir, monkeypatch):
    real = subprocess.run
    seen = []

    def spy(*a, **k):
        seen.append(k)
        return real(*a, **k)

    monkeypatch.setattr(subprocess, "run", spy)
    write(mem_dir, git_project)
    ps.confirm_part(mem_dir, git_project, "organization", "where-the-engine-lives", TODAY)
    ps.freshness(git_project, stamp_of(mem_dir))
    assert len(seen) >= MIN_GIT_CALLS and all(k.get("timeout") == GIT_TIMEOUT for k in seen)


def test_confirming_a_part_whose_path_was_deleted_raises(git_project, mem_dir):
    write(mem_dir, git_project, paths=["docs/p.md"])
    (git_project / "docs" / "p.md").unlink()
    with pytest.raises(ps.ProjectSynthesisError, match="write the part again"):
        ps.confirm_part(mem_dir, git_project, "organization", "where-the-engine-lives", TODAY)


def test_heading_starting_with_a_hash_is_refused(git_project, mem_dir):
    with pytest.raises(ps.ProjectSynthesisError):
        write(mem_dir, git_project, heading="## X")


def test_covers_uncommitted_sees_only_covered_changes_and_needs_git(tmp_path, git_project):
    assert not ps.covers_uncommitted(git_project, ["src/"])
    (git_project / "docs" / "p.md").write_text("changed\n")
    assert not ps.covers_uncommitted(git_project, ["src/"])
    assert ps.covers_uncommitted(git_project, ["docs/"])
    plain = tmp_path / "plain"
    (plain / "src").mkdir(parents=True)
    assert not ps.covers_uncommitted(plain, ["src/"])


def test_load_each_skips_a_broken_file_and_reports_it(git_project, mem_dir):
    write(mem_dir, git_project)
    (mem_dir / "syntheses" / "plans.md").write_text("no frontmatter here\n", encoding="utf-8")
    found, broken = ps.load_each(mem_dir)
    assert list(found) == ["organization"]
    assert [(p, e.startswith("plans.md:")) for p, e in broken] == [("syntheses/plans.md", True)]
