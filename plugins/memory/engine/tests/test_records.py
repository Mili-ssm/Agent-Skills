import datetime
import re
import shutil
import subprocess
from pathlib import Path
from typing import TypedDict, Unpack

import pytest
import records
import yaml

TODAY = datetime.date(2026, 11, 17)
RAW_OBSERVED = 3
SLUG_MAX = 60
HALF = 0.5
TERM_LINE_2 = 2
ALL_MATCHES = 3
MATCH_LIMIT = 2


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    git(root, "init", "-q")
    return root


def test_write_then_load_round_trip(tmp_path):
    m = records.write_memory(
        tmp_path / ".memory",
        "project",
        kind="pitfall",
        claim="The staging database rejects connections after 20:00.",
        body="Seen twice.",
        today=datetime.date(2026, 11, 17),
        context="billing service",
        sources=["https://example.org/a"],
    )
    assert m.handle == "the-staging-database-rejects-connections-after-20-00"
    [loaded] = records.load_memories(tmp_path / ".memory", "project")
    assert (
        loaded.kind,
        loaded.claim,
        loaded.observed,
        loaded.status,
        loaded.context,
        loaded.sources,
        loaded.body.strip(),
        loaded.created,
        loaded.error,
    ) == (
        "pitfall",
        "The staging database rejects connections after 20:00.",
        1,
        "active",
        "billing service",
        ["https://example.org/a"],
        "Seen twice.",
        datetime.date(2026, 11, 17),
        None,
    )


def test_valid_until_round_trips_and_yaml_dates_load(tmp_path):
    records.write_memory(
        tmp_path,
        "global",
        kind="state",
        claim="Freeze ends soon.",
        body="",
        today=TODAY,
        valid_until=datetime.date(2026, 12, 1),
    )
    (tmp_path / "raw.md").write_text(
        "---\nkind: lesson\nclaim: Raw.\ncreated: 2026-11-01\nobserved: 3\nstatus: active\n---\nbody\n"
    )
    got = {m.handle: m for m in records.load_memories(tmp_path, "global")}
    assert got["freeze-ends-soon"].valid_until == datetime.date(2026, 12, 1)
    assert (
        got["raw"].created == datetime.date(2026, 11, 1)
        and got["raw"].observed == RAW_OBSERVED
        and got["raw"].error is None
    )


def test_same_slug_gets_a_suffix(tmp_path):
    a = records.write_memory(
        tmp_path, "project", kind="lesson", claim="Same claim.", body="", today=TODAY
    )
    b = records.write_memory(
        tmp_path, "project", kind="lesson", claim="Same claim.", body="", today=TODAY
    )
    c = records.write_memory(
        tmp_path, "project", kind="lesson", claim="Same claim.", body="", today=TODAY
    )
    assert (a.handle, b.handle, c.handle) == (
        "same-claim",
        "same-claim-2",
        "same-claim-3",
    ) and a.path.exists()


def test_write_rejects_unknown_kind_and_empty_claim(tmp_path):
    with pytest.raises(ValueError):
        records.write_memory(tmp_path, "project", kind="rumor", claim="x", body="", today=TODAY)
    with pytest.raises(ValueError):
        records.write_memory(tmp_path, "project", kind="lesson", claim="  ", body="", today=TODAY)
    assert list(tmp_path.glob("*.md")) == []


def test_slug_is_never_empty():
    assert records.slug_of("¿¡…!?") == "memory" and bool(records.slug_of("Ünïcödé only ñ"))


def test_slug_limits():
    s = records.slug_of("one two three four five six seven eight nine ten")
    assert s == "one-two-three-four-five-six-seven-eight"
    long = records.slug_of(" ".join(["abcdefghij"] * 8))
    assert len(long) <= SLUG_MAX and not long.endswith("-")


def test_project_root_of_a_linked_worktree_is_the_main_one(repo, tmp_path):
    git(
        repo,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.org",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "x",
    )
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


def test_project_dir(tmp_path):
    assert records.project_dir(tmp_path) == tmp_path / ".memory"


def test_memories_root_order(tmp_path):
    store = tmp_path / "store"
    cfg = tmp_path / "cfg" / "agent-memory"
    cfg.mkdir(parents=True)
    assert records.memories_root({}, None) is None
    assert records.memories_root({}, store) is None  # store without marker
    store.mkdir()
    (store / "mem-store.yaml").write_text("")
    assert records.memories_root({}, store) == store / "memories"
    (cfg / "memories").write_text("\n/from/file\nsecond\n")
    env = {"XDG_CONFIG_HOME": str(tmp_path / "cfg")}
    assert records.memories_root(env, store) == Path("/from/file")
    assert records.memories_root({**env, "MEM_MEMORIES": "/from/env"}, store) == Path("/from/env")
    assert records.memories_root({**env, "MEM_MEMORIES": ""}, store) == Path("/from/file")
    (cfg / "memories").write_text("")
    assert records.memories_root(env, store) == store / "memories"
    assert records.memories_root({"MEM_MEMORIES": "~/mm", "HOME": "/h"}, None) == Path("/h/mm")


def test_memories_root_without_marker_ignores_store(tmp_path):
    assert records.memories_root({"MEM_MEMORIES": "/x"}, tmp_path) == Path("/x")


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
        base = {
            "scope": "project",
            "path": Path("x.md"),
            "handle": "x",
            "kind": "lesson",
            "claim": "c",
            "created": TODAY,
            "observed": 1,
            "status": "active",
            "context": None,
            "valid_until": None,
            "sources": [],
            "body": "",
            "error": None,
        }
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
    assert records.similarity(["a", "b", "c"], ["a", "b", "d"]) == pytest.approx(
        HALF
    ) and records.similarity([], ["a"]) == pytest.approx(0)
    assert records.similarity(["a"], []) == pytest.approx(0) and records.similarity(
        ["a", "a"], ["a"]
    ) == pytest.approx(1)


def test_observe_increments_and_keeps_the_body(tmp_path):
    m = records.write_memory(
        tmp_path,
        "project",
        kind="lesson",
        claim="Keep me.",
        body="Body text.\n\nMore.",
        today=TODAY,
        context="ctx",
        sources=["https://example.org/a"],
    )
    later = TODAY + datetime.timedelta(days=3)
    o = records.observe(m, later)
    [loaded] = records.load_memories(tmp_path, "project")
    assert (o.observed, loaded.observed) == (2, 2)
    assert "last_observed" in m.path.read_text() and str(later) in m.path.read_text()
    assert (loaded.claim, loaded.body.strip(), loaded.context, loaded.sources, loaded.created) == (
        "Keep me.",
        "Body text.\n\nMore.",
        "ctx",
        ["https://example.org/a"],
        TODAY,
    )


def test_ensure_excluded_once(repo):
    assert records.ensure_excluded(repo) is True
    assert (repo / ".git" / "info" / "exclude").read_text().splitlines()[-1] == ".memory/"
    (repo / ".memory").mkdir()
    assert records.ensure_excluded(repo) is False  # the folder exists: the owner's choice is kept


def test_ensure_excluded_skips_existing_line_and_non_repos(repo, tmp_path):
    ex = repo / ".git" / "info" / "exclude"
    ex.parent.mkdir(exist_ok=True)
    ex.write_text(".memory/\n")
    assert records.ensure_excluded(repo) is False
    assert ex.read_text() == ".memory/\n"
    plain = tmp_path / "plain"
    plain.mkdir()
    assert records.ensure_excluded(plain) is False


def test_forbidden_line_checks_every_text(tmp_path):
    cfg = tmp_path / "agent-memory"
    cfg.mkdir()
    (cfg / "forbidden-terms").write_text("alpha\nzeta\n")
    env = {"XDG_CONFIG_HOME": str(tmp_path)}
    assert records.forbidden_line(["clean", "has Zeta", "alpha"], env) == 1
    assert records.forbidden_line(["clean", "has Zeta"], env) == TERM_LINE_2
    assert records.forbidden_line(["clean", "fine"], env) is None
    assert records.forbidden_line([], env) is None


def test_forbidden_file(tmp_path):
    assert records.forbidden_file({"XDG_CONFIG_HOME": "/c"}) == Path(
        "/c/agent-memory/forbidden-terms"
    )
    assert records.forbidden_file({"HOME": "/h"}) == Path("/h/.config/agent-memory/forbidden-terms")
    assert records.forbidden_file({}) is None


def test_forbidden_line(tmp_path):
    cfg = tmp_path / "agent-memory"
    cfg.mkdir()
    (cfg / "forbidden-terms").write_text("\nAcme Corp\nzeta\n")
    env = {"XDG_CONFIG_HOME": str(tmp_path)}
    assert records.forbidden_line(["we met ACME corp today"], env) == TERM_LINE_2
    assert (
        records.forbidden_line(["nothing here"], env) is None
        and records.forbidden_line(["x"], {}) is None
    )


def test_forbidden_line_falls_back_to_home(tmp_path):
    cfg = tmp_path / ".config" / "agent-memory"
    cfg.mkdir(parents=True)
    (cfg / "forbidden-terms").write_text("zeta\n")
    assert records.forbidden_line(["a Zeta b"], {"HOME": str(tmp_path)}) == 1


def test_store_is_writable(tmp_path):
    assert not records.store_is_writable(tmp_path)
    (tmp_path / "mem-store.yaml").write_text("")
    assert records.store_is_writable(tmp_path)


def test_project_root_of_a_submodule_is_its_own(tmp_path):
    def run(cwd, *args):
        subprocess.run(
            [
                "git",
                "-C",
                str(cwd),
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@example.org",
                "-c",
                "protocol.file.allow=always",
                *args,
            ],
            check=True,
            capture_output=True,
        )

    sub = tmp_path / "sub"
    sub.mkdir()
    run(sub, "init", "-q")
    run(sub, "commit", "-q", "--allow-empty", "-m", "s")
    parent = tmp_path / "parent"
    parent.mkdir()
    run(parent, "init", "-q")
    run(parent, "commit", "-q", "--allow-empty", "-m", "p")
    run(parent, "submodule", "add", "-q", str(sub), "vendored")
    assert records.project_root(parent / "vendored", {}) == parent / "vendored"


def test_project_root_env_wins_over_git(repo):
    assert records.project_root(repo, {"MEM_PROJECT": "/p"}) == Path("/p")


def test_observe_keeps_unknown_keys(tmp_path):
    m = records.write_memory(
        tmp_path, "project", kind="lesson", claim="Keep extras.", body="b", today=TODAY
    )
    text = m.path.read_text().replace(
        "status: active\n", "status: active\nreviewed: '2026-01-01'\n"
    )
    m.path.write_text(text)
    [loaded] = records.load_memories(tmp_path, "project")
    records.observe(loaded, TODAY + datetime.timedelta(days=1))
    out = m.path.read_text()
    assert (
        "reviewed: '2026-01-01'" in out
        and "last_observed: '2026-11-18'" in out
        and "observed: 2" in out
    )
    assert [p.name for p in tmp_path.iterdir()] == ["keep-extras.md"]


def test_finding_needs_a_source_and_expires_in_90_days(tmp_path):
    with pytest.raises(ValueError):
        records.write_memory(
            tmp_path, "project", kind="finding", claim="No source.", body="", today=TODAY
        )
    assert list(tmp_path.glob("*.md")) == []
    m = records.write_memory(
        tmp_path,
        "project",
        kind="finding",
        claim="With source.",
        body="",
        today=TODAY,
        sources=["https://example.org/a"],
    )
    assert m.valid_until == TODAY + datetime.timedelta(days=90)
    [loaded] = records.load_memories(tmp_path, "project")
    assert loaded.valid_until == TODAY + datetime.timedelta(days=90)
    keep = records.write_memory(
        tmp_path,
        "project",
        kind="finding",
        claim="Dated.",
        body="",
        today=TODAY,
        sources=["u"],
        valid_until=datetime.date(2027, 1, 1),
    )
    assert keep.valid_until == datetime.date(2027, 1, 1)
    other = records.write_memory(
        tmp_path, "project", kind="lesson", claim="Plain.", body="", today=TODAY
    )
    assert other.valid_until is None


def _tok(text):
    return re.findall(r"[a-z0-9]+", text.lower())


class _MemOptions(TypedDict, total=False):
    context: str | None
    body: str
    observed: int
    created: datetime.date
    status: str
    valid_until: datetime.date | None


def _mem(handle, claim, **options: Unpack[_MemOptions]):
    return records.Memory(
        "project",
        Path(f"{handle}.md"),
        handle,
        "lesson",
        claim,
        options.get("created", TODAY),
        options.get("observed", 1),
        options.get("status", "active"),
        options.get("context"),
        options.get("valid_until"),
        [],
        options.get("body", ""),
        None,
    )


def _match(mems, query, **kw):
    return records.match_memories(mems, _tok(query), TODAY, tokenize=_tok, **kw)


def test_stopwords_is_a_frozenset_of_common_words():
    assert (
        isinstance(records.STOPWORDS, frozenset)
        and {"the", "is", "of", "what", "a"} <= records.STOPWORDS
    )


def test_match_stop_word_overlap_only_returns_nothing():
    mems = [_mem("a", "The cache is stale")]
    assert _match(mems, "what is the") == []
    assert _match(mems, "is the database fast") == []  # only stop words overlap


def test_match_two_of_three_terms_matches_one_of_three_does_not():
    mems = [_mem("a", "Redis cache evicts keys")]
    assert _match(mems, "redis cache postgres") == mems
    assert _match(mems, "redis mysql postgres") == []
    assert _match(mems, "redis") == mems  # one term: half rounded up is 1
    assert _match(mems, "redis mysql") == mems  # two terms: need 1


def test_match_uses_context_and_body():
    mems = [_mem("a", "Unrelated claim", context="billing service", body="rate limit")]
    assert _match(mems, "billing limit") == mems


def test_match_order_rule():
    mems = [
        _mem("h-old", "alpha", body="beta", created=datetime.date(2026, 1, 1)),
        _mem("g-body", "unrelated", body="alpha beta gamma", observed=9),
        _mem("f-claim2", "alpha beta"),
        _mem("e-claim1", "alpha", body="beta gamma"),
        _mem("d-obs", "alpha", body="beta", observed=2),
        _mem("c-new", "alpha", body="beta", created=datetime.date(2026, 6, 1)),
        _mem("b-handle", "alpha", body="beta", created=datetime.date(2026, 6, 1)),
    ]
    got = [m.handle for m in _match(mems, "alpha beta gamma", limit=10)]
    assert got == ["f-claim2", "e-claim1", "d-obs", "b-handle", "c-new", "h-old", "g-body"]
    assert (
        got.index("f-claim2")
        < got.index("e-claim1")
        < got.index("d-obs")
        < got.index("b-handle")
        < got.index("c-new")
        < got.index("h-old")
    )
    assert got.index("h-old") < got.index("g-body")


def test_match_limit_default_three():
    mems = [_mem(f"m{i}", "alpha") for i in range(5)]
    assert len(_match(mems, "alpha")) == ALL_MATCHES
    assert len(_match(mems, "alpha", limit=2)) == MATCH_LIMIT


def test_match_dead_memories_only_with_include_dead():
    mems = [
        _mem("r", "alpha thing", status="refuted"),
        _mem("e", "alpha thing", valid_until=TODAY - datetime.timedelta(days=1)),
        _mem("ok", "alpha thing"),
    ]
    assert [m.handle for m in _match(mems, "alpha")] == ["ok"]
    assert {m.handle for m in _match(mems, "alpha", include_dead=True)} == {"r", "e", "ok"}


def _terms(tmp_path, data: bytes):
    cfg = tmp_path / "agent-memory"
    cfg.mkdir(exist_ok=True)
    (cfg / "forbidden-terms").write_bytes(data)
    return {"XDG_CONFIG_HOME": str(tmp_path)}


def test_forbidden_line_fails_closed_on_an_unreadable_list(tmp_path):
    env = _terms(tmp_path, b"\xff\xfe\x00bad\x80\n")
    with pytest.raises(records.ForbiddenListError):
        records.forbidden_line(["clean"], env)
    assert issubclass(records.ForbiddenListError, ValueError)
    assert (
        records.forbidden_line(["x"], {"XDG_CONFIG_HOME": str(tmp_path / "none")}) is None
    )  # missing: caller's case


def test_forbidden_line_matches_split_accented_fullwidth_bom_and_slug(tmp_path):
    env = _terms(tmp_path, "﻿acme corp\nnaïve\nzeta\n".encode())
    assert records.forbidden_line(["we met acme", "corp today"], env) == 1  # split between texts
    assert records.forbidden_line(["ACME CORP"], env) == 1  # first line after a BOM
    assert records.forbidden_line(["a NAIVE case"], env) == TERM_LINE_2  # accent on the list side
    assert records.forbidden_line(["a naive case"], env) == TERM_LINE_2
    env2 = _terms(tmp_path, b"naive\n")
    assert records.forbidden_line(["a naïve case"], env2) == 1  # accent on the text side
    assert (
        records.forbidden_line(["\uff5a\uff45\uff54\uff41"], _terms(tmp_path, b"zeta\n")) == 1
    )  # full-width
    assert (
        records.forbidden_line(
            [records.slug_of("Zeta, retries")], _terms(tmp_path, b"zeta-retries\n")
        )
        == 1
    )


def test_ensure_excluded_raises_when_the_line_cannot_be_written(repo):
    info = repo / ".git" / "info"
    if info.exists():
        shutil.rmtree(info)
    assert records.ensure_excluded(repo) is True  # creates .git/info when missing
    (repo / ".memory").rmdir() if (repo / ".memory").exists() else None
    ex = info / "exclude"
    ex.unlink()
    ex.mkdir()  # a folder where the file should be
    with pytest.raises(OSError):
        records.ensure_excluded(repo)


def test_project_root_override_expands_home_and_resolves(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert (
        records.project_root(tmp_path, {"MEM_PROJECT": "~/projX"}) == (tmp_path / "projX").resolve()
    )
    monkeypatch.chdir(tmp_path)
    assert records.project_root(tmp_path, {"MEM_PROJECT": "rel"}) == (tmp_path / "rel").resolve()


def test_document_needs_a_source_and_has_no_default_expiry(tmp_path):
    with pytest.raises(ValueError, match="document"):
        records.write_memory(
            tmp_path, "project", kind="document", claim="No source.", body="", today=TODAY
        )
    assert list(tmp_path.glob("*.md")) == []
    m = records.write_memory(
        tmp_path,
        "project",
        kind="document",
        claim="With a path.",
        body="",
        today=TODAY,
        sources=["docs/spec.pdf"],
    )
    assert m.valid_until is None and "valid_until" not in m.path.read_text()
    [loaded] = records.load_memories(tmp_path, "project")
    assert loaded.kind == "document" and loaded.sources == ["docs/spec.pdf"]


@pytest.mark.parametrize(
    "text",
    [
        "name: plain\ncount: 3\nratio: 1.5",
        "date: 2026-11-17\nwhen: 2026-11-17 10:20:30",
        "a: on\nb: off\nc: yes\nd: no\ne: true",
        "k: 1\nk: 2",
        "",
        "- a\n- b\n- 3",
        "outer:\n  inner:\n    leaf: [1, 2]\n  other: {x: y}",
        "title: caf\u00e9 \u00f1 \u65e5\u672c\u8a9e \U0001f600",
    ],
)
@pytest.mark.skipif(
    not hasattr(yaml, "CSafeLoader"), reason="libyaml absent: both sides would be the Python loader"
)
def test_safe_load_matches_python_safe_loader(text):
    assert records.safe_load(text) == yaml.load(text, Loader=yaml.SafeLoader)


@pytest.mark.skipif(
    not hasattr(yaml, "CSafeLoader"),
    reason="libyaml absent: safe_load falls back to the Python loader",
)
def test_safe_load_accepts_tab_after_colon_unlike_python_loader():
    assert records.safe_load("a:\tb") == {"a": "b"}
    with pytest.raises(yaml.YAMLError):
        yaml.load("a:\tb", Loader=yaml.SafeLoader)
