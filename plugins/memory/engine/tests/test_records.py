import datetime
import subprocess
from pathlib import Path

import pytest

import records

TODAY = datetime.date(2026, 11, 17)


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    git(root, "init", "-q")
    return root


def test_write_then_load_round_trip(tmp_path):
    m = records.write_memory(tmp_path / ".memory", "project", kind="pitfall",
        claim="The staging database rejects connections after 20:00.", body="Seen twice.",
        today=datetime.date(2026, 11, 17), context="billing service", sources=["https://example.org/a"])
    assert m.handle == "the-staging-database-rejects-connections-after-20-00"
    [loaded] = records.load_memories(tmp_path / ".memory", "project")
    assert (loaded.kind, loaded.claim, loaded.observed, loaded.status, loaded.context, loaded.sources, loaded.body.strip(), loaded.created, loaded.error) == \
        ("pitfall", "The staging database rejects connections after 20:00.", 1, "active", "billing service", ["https://example.org/a"], "Seen twice.", datetime.date(2026, 11, 17), None)


def test_valid_until_round_trips_and_yaml_dates_load(tmp_path):
    records.write_memory(tmp_path, "global", kind="state", claim="Freeze ends soon.", body="",
                         today=TODAY, valid_until=datetime.date(2026, 12, 1))
    (tmp_path / "raw.md").write_text("---\nkind: lesson\nclaim: Raw.\ncreated: 2026-11-01\nobserved: 3\nstatus: active\n---\nbody\n")
    got = {m.handle: m for m in records.load_memories(tmp_path, "global")}
    assert got["freeze-ends-soon"].valid_until == datetime.date(2026, 12, 1)
    assert got["raw"].created == datetime.date(2026, 11, 1) and got["raw"].observed == 3 and got["raw"].error is None


def test_same_slug_gets_a_suffix(tmp_path):
    a = records.write_memory(tmp_path, "project", kind="lesson", claim="Same claim.", body="", today=TODAY)
    b = records.write_memory(tmp_path, "project", kind="lesson", claim="Same claim.", body="", today=TODAY)
    c = records.write_memory(tmp_path, "project", kind="lesson", claim="Same claim.", body="", today=TODAY)
    assert (a.handle, b.handle, c.handle) == ("same-claim", "same-claim-2", "same-claim-3") and a.path.exists()


def test_write_rejects_unknown_kind_and_empty_claim(tmp_path):
    with pytest.raises(ValueError):
        records.write_memory(tmp_path, "project", kind="rumor", claim="x", body="", today=TODAY)
    with pytest.raises(ValueError):
        records.write_memory(tmp_path, "project", kind="lesson", claim="  ", body="", today=TODAY)
    assert list(tmp_path.glob("*.md")) == []


def test_slug_is_never_empty():
    assert records.slug_of("¿¡…!?") == "memory" and records.slug_of("Ünïcödé only ñ") != ""


def test_slug_limits():
    s = records.slug_of("one two three four five six seven eight nine ten")
    assert s == "one-two-three-four-five-six-seven-eight"
    long = records.slug_of(" ".join(["abcdefghij"] * 8))
    assert len(long) <= 60 and not long.endswith("-")


def test_project_root_of_a_linked_worktree_is_the_main_one(repo, tmp_path):
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.org", "commit", "-q", "--allow-empty", "-m", "x")
    git(repo, "worktree", "add", "-q", str(tmp_path / "wt"))
    assert records.project_root(tmp_path / "wt", {}) == repo
    assert records.project_root(repo, {}) == repo


def test_project_root_outside_git_is_none(tmp_path):
    assert records.project_root(tmp_path, {}) is None
    assert records.project_root(tmp_path, {"MEM_PROJECT": "/p"}) == Path("/p")
    assert records.project_root(tmp_path, {"MEM_PROJECT": ""}) is None


def test_project_root_without_git_is_none(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    assert records.project_root(tmp_path, {}) is None


def test_memory_dir(tmp_path):
    assert records.memory_dir("project", store=None, project=tmp_path) == tmp_path / ".memory"
    assert records.memory_dir("global", store=tmp_path, project=None) == tmp_path / "memories"
    assert records.memory_dir("project", store=tmp_path, project=None) is None
    assert records.memory_dir("global", store=None, project=tmp_path) is None


def test_load_memories_missing_or_none(tmp_path):
    assert records.load_memories(None, "project") == []
    assert records.load_memories(tmp_path / "nope", "project") == []


def test_load_memories_sorted_and_only_direct_md(tmp_path):
    for n in ("b", "a"):
        records.write_memory(tmp_path, "project", kind="lesson", claim=n, body="", today=TODAY)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.md").write_text("x")
    (tmp_path / "n.txt").write_text("x")
    assert [m.handle for m in records.load_memories(tmp_path, "project")] == ["a", "b"]


def test_broken_file_is_reported_not_raised(tmp_path):
    (tmp_path / "bad.md").write_text("---\nkind: [unclosed\n---\n")
    (tmp_path / "odd.md").write_text("---\nkind: rumor\nclaim: x\n---\n")
    (tmp_path / "plain.md").write_text("no frontmatter\n")
    got = records.load_memories(tmp_path, "project")
    assert [m.handle for m in got] == ["bad", "odd", "plain"] and all(m.error for m in got)
    assert got[0].observed == 1 and got[0].sources == [] and got[0].status == "active"


def test_is_live():
    def mk(**kw):
        base = dict(scope="project", path=Path("x.md"), handle="x", kind="lesson", claim="c", created=TODAY,
                    observed=1, status="active", context=None, valid_until=None, sources=[], body="", error=None)
        base.update(kw)
        return records.Memory(**base)
    y = TODAY - datetime.timedelta(days=1)
    assert records.is_live(mk(), TODAY)
    assert not records.is_live(mk(valid_until=y), TODAY)
    assert records.is_live(mk(valid_until=TODAY), TODAY)
    assert not records.is_live(mk(status="refuted"), TODAY)
    assert not records.is_live(mk(status="superseded"), TODAY)
    assert not records.is_live(mk(error="bad"), TODAY)


def test_similarity():
    assert records.similarity(["a", "b", "c"], ["a", "b", "d"]) == 0.5 and records.similarity([], ["a"]) == 0.0
    assert records.similarity(["a"], []) == 0.0 and records.similarity(["a", "a"], ["a"]) == 1.0


def test_observe_increments_and_keeps_the_body(tmp_path):
    m = records.write_memory(tmp_path, "project", kind="lesson", claim="Keep me.", body="Body text.\n\nMore.",
                             today=TODAY, context="ctx", sources=["https://example.org/a"])
    later = TODAY + datetime.timedelta(days=3)
    o = records.observe(m, later)
    [loaded] = records.load_memories(tmp_path, "project")
    assert (o.observed, loaded.observed) == (2, 2)
    assert "last_observed" in m.path.read_text() and str(later) in m.path.read_text()
    assert (loaded.claim, loaded.body.strip(), loaded.context, loaded.sources, loaded.created) == \
        ("Keep me.", "Body text.\n\nMore.", "ctx", ["https://example.org/a"], TODAY)


def test_ensure_excluded_once(repo):
    assert records.ensure_excluded(repo) is True
    assert (repo / ".git" / "info" / "exclude").read_text().splitlines()[-1] == ".memory/"
    (repo / ".memory").mkdir()
    assert records.ensure_excluded(repo) is False       # the folder exists: the owner's choice is kept


def test_ensure_excluded_skips_existing_line_and_non_repos(repo, tmp_path):
    ex = repo / ".git" / "info" / "exclude"
    ex.parent.mkdir(exist_ok=True)
    ex.write_text(".memory/\n")
    assert records.ensure_excluded(repo) is False
    assert ex.read_text() == ".memory/\n"
    plain = tmp_path / "plain"
    plain.mkdir()
    assert records.ensure_excluded(plain) is False


def test_forbidden_line(tmp_path):
    cfg = tmp_path / "agent-memory"; cfg.mkdir(); (cfg / "forbidden-terms").write_text("\nAcme Corp\nzeta\n")
    env = {"XDG_CONFIG_HOME": str(tmp_path)}
    assert records.forbidden_line("we met ACME corp today", env) == 2
    assert records.forbidden_line("nothing here", env) is None and records.forbidden_line("x", {}) is None


def test_forbidden_line_falls_back_to_home(tmp_path):
    cfg = tmp_path / ".config" / "agent-memory"; cfg.mkdir(parents=True); (cfg / "forbidden-terms").write_text("zeta\n")
    assert records.forbidden_line("a Zeta b", {"HOME": str(tmp_path)}) == 1


def test_store_is_writable(tmp_path):
    assert not records.store_is_writable(tmp_path, {})
    assert records.store_is_writable(tmp_path, {"MEM_ALLOW_WRITE": "1"})
    (tmp_path / "mem-store.yaml").write_text(""); assert records.store_is_writable(tmp_path, {})
