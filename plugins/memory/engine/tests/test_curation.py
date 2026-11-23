import datetime
import os
import subprocess

import pytest

import mem
import records

TODAY = datetime.date.today()


def days_ago(n):
    return (TODAY - datetime.timedelta(days=n)).isoformat()


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    git(root, "init", "-q")
    monkeypatch.setenv("MEM_PROJECT", str(root))
    return root / ".memory"


@pytest.fixture
def gfolder(tmp_path, monkeypatch):
    folder = tmp_path / "gmem"
    monkeypatch.setenv("MEM_MEMORIES", str(folder))
    return folder


def put(folder, handle, claim, *, kind="lesson", status="active", created=None, observed=1, body="", extra=""):
    folder.mkdir(parents=True, exist_ok=True)
    text = (f"---\nkind: {kind}\nclaim: {claim}\ncreated: '{created or days_ago(1)}'\nobserved: {observed}\n"
            f"status: {status}\n{extra}---\n{body}")
    (folder / f"{handle}.md").write_text(text, encoding="utf-8")
    return folder / f"{handle}.md"


def run(capsys, *argv):
    code = mem.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def mem_of(path):
    return records.load_memories(path.parent, "project")[[p.name for p in sorted(path.parent.glob("*.md"))].index(path.name)]


# records

def test_update_keeps_unknown_keys_and_body_and_removes_none(tmp_path):
    path = put(tmp_path, "a", "Alpha beta gamma.", body="Body text.\n", extra="reviewed: '2026-01-01'\nold: x\n")
    m = records.load_memories(tmp_path, "project")[0]
    out = records.update(m, TODAY, observed=4, old=None, new_key=TODAY)
    text = path.read_text()
    assert "reviewed: '2026-01-01'" in text and "old:" not in text and f"new_key: '{TODAY.isoformat()}'" in text
    assert text.endswith("---\nBody text.\n") and out.observed == 4 and out.body == "Body text.\n"
    assert not list(tmp_path.glob(".*.tmp"))


def test_pairs_lists_near_copy_and_negation_not_unrelated_nor_dead(tmp_path):
    ms = [records.Memory("project", tmp_path / f"{h}.md", h, "lesson", c, TODAY, 1, st, None, None, [], "", None)
          for h, c, st in [("a", "Retries need idempotency keys on every payment call", "active"),
                           ("b", "Retries need idempotency keys on every payment call always", "active"),
                           ("c", "Retries never need idempotency keys on every payment call", "active"),
                           ("d", "Pottery glaze firing temperature chart", "active"),
                           ("e", "Retries need idempotency keys on every payment call", "forgotten")]]
    got = records.pairs(ms, TODAY, tokenize=mem.tokenize)
    names = {(a.handle, b.handle) for a, b, _ in got}
    assert ("a", "b") in names and ("a", "c") in names
    assert not any("d" in n or "e" in n for n in names)
    assert [s for *_, s in got] == sorted((s for *_, s in got), reverse=True)


def _mem(tmp_path, h, claim, status="active", created=TODAY, refuted=None):
    return records.Memory("project", tmp_path / f"{h}.md", h, "lesson", claim, created, 1, status, None, None, [], "",
                          None, refuted=refuted)


def _old_pairs(memories, today, *, tokenize):
    """A copy of the implementation before the search took `among` and `budget`."""
    live = sorted((m for m in memories if records.is_live(m, today)), key=lambda m: m.handle)
    tokens = [tokenize(m.claim) for m in live]
    found = []
    for i, a in enumerate(live):
        for j in range(i + 1, len(live)):
            score = max(records.containment(tokens[i], set(tokens[j])), records.containment(tokens[j], set(tokens[i])))
            if score >= records.STRONG and live[j].handle not in a.distinct_from and a.handle not in live[j].distinct_from:
                found.append((a, live[j], score))
    found.sort(key=lambda t: (-t[2], t[0].handle, t[1].handle))
    return found


def test_pairs_unchanged_without_new_arguments(tmp_path):
    base = "Retries need idempotency keys on every payment call"
    claims = []
    for n in range(6):
        claims += [f"{base} version{n}", f"{base} never version{n}", f"Glaze number{n} firing chart for kiln{n} pottery"]
    claims += [f"Unrelated topic{n} words alpha{n} beta{n} gamma{n}" for n in range(12)]
    ms = [_mem(tmp_path, f"m{n:02d}", c) for n, c in enumerate(claims)]
    ms[1] = records.replace(ms[1], distinct_from=["m00"])
    got = records.pairs(ms, TODAY, tokenize=mem.tokenize)
    assert got and got == _old_pairs(ms, TODAY, tokenize=mem.tokenize)


def _abc(tmp_path):
    ms = [_mem(tmp_path, "a", "Retries need idempotency keys on every payment call"),
          _mem(tmp_path, "b", "Retries need idempotency keys on every payment call always today"),
          _mem(tmp_path, "c", "Retries need idempotency keys on every payment call always today now")]
    ms += [_mem(tmp_path, f"x{n}", f"Unrelated topic{n} words alpha{n} beta{n}") for n in range(7)]
    return ms


def test_pairs_among_compares_only_pairs_with_a_listed_memory(tmp_path):
    ms = _abc(tmp_path)
    allp = {(a.handle, b.handle) for a, b, _ in records.pairs(ms, TODAY, tokenize=mem.tokenize)}
    assert {("a", "b"), ("b", "c"), ("a", "c")} <= allp
    got = records.pairs(ms, TODAY, tokenize=mem.tokenize, among=["c"])
    assert {(a.handle, b.handle) for a, b, _ in got} == {("a", "c"), ("b", "c")}
    both = records.pairs(ms, TODAY, tokenize=mem.tokenize, among=["b", "c"])
    assert sorted((a.handle, b.handle) for a, b, _ in both) == [("a", "b"), ("a", "c"), ("b", "c")]


def test_pairs_budget_stops_and_reports(tmp_path):
    ms = _abc(tmp_path)
    budget = records.Budget(1)
    got = records.pairs(ms, TODAY, tokenize=mem.tokenize, among=["a", "x0"], budget=budget)
    assert budget.left == 0 and budget.exhausted and len(got) <= 1
    roomy = records.Budget(10_000)
    records.pairs(ms, TODAY, tokenize=mem.tokenize, among=["a", "x0"], budget=roomy)
    assert roomy.left == 10_000 - 17 and not roomy.exhausted  # 9 partners of a, 8 more of x0
    exact = records.Budget(17)
    records.pairs(ms, TODAY, tokenize=mem.tokenize, among=["a", "x0"], budget=exact)
    assert exact.left == 0 and not exact.exhausted  # used up with nothing left to compare


def test_refuted_pairs_among_and_budget(tmp_path):
    ms = [_mem(tmp_path, "r", "Retries need idempotency keys on every payment call", status="refuted",
               created=TODAY - datetime.timedelta(days=5), refuted=TODAY - datetime.timedelta(days=3)),
          _mem(tmp_path, "a", "Retries need idempotency keys on every payment call again"),
          _mem(tmp_path, "b", "Retries need idempotency keys on every payment call once more")]
    assert [(a.handle, r.handle) for a, r, _ in records.refuted_pairs(ms, TODAY, tokenize=mem.tokenize)] == \
        [("a", "r"), ("b", "r")]
    only = records.refuted_pairs(ms, TODAY, tokenize=mem.tokenize, among=["b"])
    assert [(a.handle, r.handle) for a, r, _ in only] == [("b", "r")]
    budget = records.Budget(1)
    got = records.refuted_pairs(ms, TODAY, tokenize=mem.tokenize, among=["a", "b"], budget=budget)
    assert len(got) == 1 and budget.left == 0 and budget.exhausted


def _old_refuted_pairs(memories, today, *, tokenize):
    """A copy of the implementation before the search took `among` and `budget`."""
    live = sorted((m for m in memories if records.is_live(m, today)), key=lambda m: m.handle)
    dead = sorted((m for m in memories if m.error is None and m.status == "refuted"), key=lambda m: m.handle)
    found = []
    for a in live:
        ta = tokenize(a.claim)
        for r in dead:
            if r.handle in a.distinct_from or a.handle in r.distinct_from:
                continue
            since = r.refuted or r.created
            if a.created is None or (since is not None and a.created <= since):
                continue
            tr = tokenize(r.claim)
            score = max(records.containment(ta, set(tr)), records.containment(tr, set(ta)))
            if score >= records.STRONG:
                found.append((a, r, score))
    found.sort(key=lambda t: (-t[2], t[0].handle, t[1].handle))
    return found


def _refuted_fixture(tmp_path):
    base = "Retries need idempotency keys on every payment call"
    old = TODAY - datetime.timedelta(days=9)
    ms = []
    for n in range(4):
        ms.append(_mem(tmp_path, f"r{n}", f"{base} version{n}", status="refuted", created=old,
                       refuted=TODAY - datetime.timedelta(days=3 + n)))
        ms.append(_mem(tmp_path, f"a{n}", f"{base} never version{n}", created=TODAY - datetime.timedelta(days=n)))
    ms.append(_mem(tmp_path, "older", f"{base} version1", created=old - datetime.timedelta(days=1)))
    ms.append(_mem(tmp_path, "same", f"{base} version2 again", created=old))
    ms += [_mem(tmp_path, f"x{n}", f"Unrelated topic{n} words alpha{n} beta{n}") for n in range(5)]
    ms[1] = records.replace(ms[1], distinct_from=["r0"])
    return ms


def test_refuted_pairs_unchanged_without_new_arguments(tmp_path):
    ms = _refuted_fixture(tmp_path)
    got = records.refuted_pairs(ms, TODAY, tokenize=mem.tokenize)
    assert len(got) > 2 and got == _old_refuted_pairs(ms, TODAY, tokenize=mem.tokenize)


def _counting(calls):
    def tokenize(text):
        calls.append(text)
        return mem.tokenize(text)
    return tokenize


def test_pairs_tokenizes_once_per_live_memory(tmp_path):
    ms = _abc(tmp_path) + [_mem(tmp_path, "gone", "Pottery glaze chart", status="forgotten")]
    calls = []
    records.pairs(ms, TODAY, tokenize=_counting(calls))
    assert len(calls) == 10


def test_refuted_pairs_tokenizes_each_claim_at_most_once(tmp_path):
    ms = _refuted_fixture(tmp_path)
    live = [m for m in ms if records.is_live(m, TODAY)]
    dead = [m for m in ms if m.status == "refuted"]
    calls = []
    records.refuted_pairs(ms, TODAY, tokenize=_counting(calls))
    assert len(calls) <= len(live) + len(dead)
    calls.clear()
    records.refuted_pairs(ms, TODAY, tokenize=_counting(calls), among=["a3"])
    assert len(calls) <= 1 + len(dead)
    calls.clear()
    records.refuted_pairs(ms, TODAY, tokenize=_counting(calls), among=["x0"], budget=records.Budget(1))
    assert len(calls) <= 2


def test_differing_words_drops_stopwords_and_keeps_negations():
    assert records.differing_words("the cache is warm", "cache is not warm") == ["not"]
    assert records.differing_words("retry 3 times", "retry 5 times") == ["3", "5"]
    assert records.differing_words("the cache is warm", "a cache is warm") == []


# memories

def test_memories_order_kind_dead_and_scope(project, gfolder, capsys):
    put(project, "old", "Older lesson here", created=days_ago(5))
    put(project, "new", "Newer lesson here", created=days_ago(1))
    put(project, "st", "A state thing", kind="state", created=days_ago(9))
    put(project, "dead", "Gone thing now", status="forgotten", created=days_ago(2))
    put(gfolder, "gl", "Global lesson", created=days_ago(1))
    code, out, _ = run(capsys, "memories")
    assert code == 0
    assert out.splitlines() == [f"m:st\t[state, observed 1, {days_ago(9)}]\tA state thing",
                                f"m:new\t[lesson, observed 1, {days_ago(1)}]\tNewer lesson here",
                                f"m:old\t[lesson, observed 1, {days_ago(5)}]\tOlder lesson here"]
    assert [ln.split("\t")[0] for ln in run(capsys, "memories", "--kind", "state")[1].splitlines()] == ["m:st"]
    dead = run(capsys, "memories", "--dead")[1]
    assert f"m:dead\t[lesson, observed 1, {days_ago(2)}, forgotten]\tGone thing now" in dead and "m:old" in dead
    assert run(capsys, "memories", "--global")[1] == f"m:gl\t[lesson, observed 1, {days_ago(1)}]\tGlobal lesson\n"
    assert "m:gl" in run(capsys, "memories", "--all")[1] and "m:old" in run(capsys, "memories", "--all")[1]


# curate

def test_curate_prints_the_four_blocks(project, capsys):
    put(project, "k1", "Retries need idempotency keys on payment calls")
    put(project, "k2", "Retries never need idempotency keys on payment calls")
    put(project, "exp", "Cache warmup takes long", extra=f"valid_until: '{days_ago(3)}'\n")
    put(project, "often", "Zebra crossing lights flicker", observed=4)
    put(project, "stale", "Quartz clocks drift slowly", created=days_ago(120))
    put(project, "stale-state", "Pending migration window open", kind="state", created=days_ago(120))
    put(project, "seen", "Granite worktops stain easily", created=days_ago(120), extra=f"last_observed: '{days_ago(10)}'\n")
    code, out, _ = run(capsys, "curate")
    assert code == 0
    assert out.splitlines() == [
        "same or opposite? (decide: mem merge <keep> <drop>, or keep both and say so in the body)",
        f"  m:k1  [lesson, {days_ago(1)}]  Retries need idempotency keys on payment calls",
        f"    m:k2  [lesson, {days_ago(1)}]  Retries never need idempotency keys on payment calls",
        "      differ in: never",
        "expired (decide: mem forget <h>, or mem confirm <h> --until <date> if it still holds)",
        f"  m:exp  valid until {days_ago(3)}  Cache warmup takes long",
        "seen 3 times or more: general enough for a global lesson? (mem promote <h>)",
        "  m:often  observed 4  Zebra crossing lights flicker",
        "not confirmed in 90 days (decide: mem confirm <h> or mem forget <h>)",
        f"  m:stale  {days_ago(120)}  Quartz clocks drift slowly",
        "-- project syntheses: none yet --",
        "6 active memories and no project synthesis: organize them (see the memory-curation skill).",
    ]


def test_curate_groups_pairs_by_memory(project, capsys):
    put(project, "hub", "Retries need idempotency keys on payment calls")
    put(project, "p1", "Retries need idempotency keys on payment calls always")
    put(project, "p2", "Retries never need idempotency keys on payment calls")
    put(project, "p3", "Retries need the idempotency keys on payment calls")
    out = run(capsys, "curate", "--project")[1].splitlines()
    head = out.index("same or opposite? (decide: mem merge <keep> <drop>, or keep both and say so in the body)")
    block = [ln for ln in out[head + 1:] if ln.startswith("  m:") or ln.startswith("    ")]
    assert block[0].startswith("  m:hub  [lesson,") and out.count(block[0]) == 1
    assert [ln.split()[0] for ln in block if ln.startswith("  m:")] == ["m:hub", "m:p1", "m:p2"]
    assert sum(ln.startswith("      differ in:") for ln in block) == 6  # six pairs, each once
    assert sum(ln.startswith("    m:") for ln in block) == 6
    assert block[1:7] == [
        f"    m:p1  [lesson, {days_ago(1)}]  Retries need idempotency keys on payment calls always",
        "      differ in: always",
        f"    m:p2  [lesson, {days_ago(1)}]  Retries never need idempotency keys on payment calls",
        "      differ in: never",
        f"    m:p3  [lesson, {days_ago(1)}]  Retries need the idempotency keys on payment calls",
        "      differ in: wording only"]


def test_curate_lists_state_pairs_as_newer_state(project, capsys):
    put(project, "s-old", "Migration window is open for the billing service", kind="state", created=days_ago(9))
    put(project, "s-new", "Migration window is open for the billing service now", kind="state", created=days_ago(2))
    out = run(capsys, "curate", "--project")[1].splitlines()
    assert ("newer state of the same project? (decide: mem supersede <old> <new>, or mem distinct <a> <b>)"
            in out)
    i = out.index(f"  m:s-old  [state, {days_ago(9)}]  Migration window is open for the billing service")
    assert out[i + 1] == f"    -> m:s-new  [state, {days_ago(2)}]  Migration window is open for the billing service now"
    assert not any(ln.startswith("same or opposite") for ln in out)


def test_curate_seen_often_is_a_global_lesson_candidate(project, capsys):
    put(project, "often", "Zebra crossing lights flicker", observed=3)
    out = run(capsys, "curate", "--project")[1]
    assert "seen 3 times or more: general enough for a global lesson? (mem promote <h>)" in out.splitlines()


def test_seen_often_skips_global_memories(gfolder, capsys):
    put(gfolder, "gl", "Zebra crossing lights flicker", observed=5)
    found = mem._decisions(records.load_memories(gfolder, "global"), TODAY)
    assert found.seen == [] and not any(k.startswith("seen:") for k in found.keys())
    assert "seen 3 times or more" not in run(capsys, "curate", "--global")[1]


def test_differ_in_wording_only(project, capsys):
    put(project, "a", "Retries need idempotency keys on payment calls")
    put(project, "b", "Retries need the idempotency keys on payment calls")
    assert "      differ in: wording only" in run(capsys, "curate", "--project")[1].splitlines()


def _load(folder):
    return records.load_memories(folder, "project")


def test_decisions_keys(project):
    put(project, "k2", "Retries never need idempotency keys on payment calls")
    put(project, "k1", "Retries need idempotency keys on payment calls")
    put(project, "s-old", "Migration window is open for the billing service", kind="state", created=days_ago(9))
    put(project, "s-new", "Migration window is open for the billing service now", kind="state", created=days_ago(2))
    put(project, "exp", "Cache warmup takes long", extra=f"valid_until: '{days_ago(3)}'\n")
    put(project, "often", "Zebra crossing lights flicker", observed=4)
    put(project, "stale", "Quartz clocks drift slowly", created=days_ago(120))
    put(project, "dead", "Pottery glaze firing chart", status="refuted", created=days_ago(20),
        extra=f"refuted: '{days_ago(10)}'\n")
    put(project, "again", "Pottery glaze firing chart", created=days_ago(2))
    keys = mem._decisions(_load(project), TODAY).keys()
    assert keys == {"refuted:again|dead": "refuted again", "pair:k1|k2": "same or opposite",
                    "state:s-old|s-new": "newer state", "expired:exp": "expired", "seen:often": "seen often",
                    "stale:stale": "not confirmed in 90 days"}


def _pair_keys(d):
    return {k for k in d.keys() if k.startswith(("pair:", "state:", "refuted:"))}


def _age(path, days):
    t = (datetime.datetime.now() - datetime.timedelta(days=days)).timestamp()
    os.utime(path, (t, t))


SINCE = TODAY - datetime.timedelta(days=10)


def test_decisions_since_on_an_unchanged_store_finds_no_pairs(project):
    for h, c in (("k1", "Retries need idempotency keys on payment calls"),
                 ("k2", "Retries never need idempotency keys on payment calls")):
        _age(put(project, h, c, created=days_ago(30)), 30)
    d = mem._decisions(_load(project), TODAY, since=SINCE, budget=records.Budget(100))
    assert _pair_keys(d) == set() and d.pairs_checked


def test_decisions_since_finds_a_memory_whose_file_changed(project):
    _age(put(project, "k1", "Retries need idempotency keys on payment calls", created=days_ago(30)), 30)
    _age(put(project, "k2", "Retries never need idempotency keys on payment calls", created=days_ago(30)), 0)
    assert _pair_keys(mem._decisions(_load(project), TODAY, since=SINCE)) == {"pair:k1|k2"}


def test_decisions_since_counts_a_memory_without_created_as_changed(project):
    _age(put(project, "k1", "Retries need idempotency keys on payment calls", created=days_ago(30)), 30)
    path = put(project, "k2", "Retries never need idempotency keys on payment calls")
    path.write_text(path.read_text().replace(f"created: '{days_ago(1)}'\n", ""))
    _age(path, 30)
    assert _pair_keys(mem._decisions(_load(project), TODAY, since=SINCE)) == {"pair:k1|k2"}


def test_changed_since_orders_newest_change_first(project):
    for h, n in (("a", 5), ("b", 2), ("c", 8)):
        _age(put(project, h, f"Claim number {h}", created=days_ago(n)), n)
    _age(put(project, "z", "Claim number z", created=days_ago(30)), 30)
    assert mem._changed_since(_load(project), SINCE) == ["b", "a", "c"]


def test_decisions_since_spends_the_budget_on_the_newest_change_first(project):
    for h, c, n in (("n1", "Retries need idempotency keys on payment calls", 1),
                    ("n2", "Retries never need idempotency keys on payment calls", 1),
                    ("o1", "Quartz clocks drift slowly in cold rooms", 5),
                    ("o2", "Quartz clocks never drift slowly in cold rooms", 5)):
        _age(put(project, h, c, created=days_ago(n)), n)
    found = _pair_keys(mem._decisions(_load(project), TODAY, since=SINCE, budget=records.Budget(3)))
    assert "pair:n1|n2" in found and "pair:o1|o2" not in found


def test_decisions_since_with_no_budget_left_checks_nothing(project):
    _age(put(project, "k1", "Retries need idempotency keys on payment calls", created=days_ago(30)), 30)
    put(project, "k2", "Retries never need idempotency keys on payment calls")
    d = mem._decisions(_load(project), TODAY, since=SINCE, budget=records.Budget(0))
    assert _pair_keys(d) == set() and not d.pairs_checked


def test_decisions_since_finds_a_subset_of_the_keys_without_it(project):
    _age(put(project, "k1", "Retries need idempotency keys on payment calls", created=days_ago(30)), 30)
    _age(put(project, "k2", "Retries never need idempotency keys on payment calls", created=days_ago(30)), 30)
    put(project, "m1", "Quartz clocks drift slowly in cold rooms")
    put(project, "m2", "Quartz clocks never drift slowly in cold rooms")
    with_since = set(mem._decisions(_load(project), TODAY, since=SINCE).keys())
    assert "pair:m1|m2" in with_since and with_since <= set(mem._decisions(_load(project), TODAY).keys())


def test_decisions_drops_superseded(project):
    put(project, "a", "Retries need idempotency keys on payment calls")
    put(project, "b", "Retries never need idempotency keys on payment calls", extra="superseded_by: a\n")
    put(project, "c", "Cache warmup takes long", extra=f"valid_until: '{days_ago(3)}'\nsuperseded_by: a\n")
    d = mem._decisions(_load(project), TODAY)
    assert d.keys() == {} and d.pairs_checked


def test_curate_empty_prints_nothing_even_without_store_or_git(tmp_path, monkeypatch, capsys):
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)
    assert run(capsys, "curate") == (0, "", "")
    assert run(capsys, "curate", "--project") == (0, "", "")
    assert run(capsys, "curate", "--global") == (0, "", "")
    assert run(capsys, "curate", "--done") == (0, "", "")
    assert list(plain.iterdir()) == []


def passes(tmp_path):
    import json
    return json.loads((tmp_path / "mem-data" / "curated.json").read_text())


def test_curate_done_records_the_covered_scopes_in_the_data_folder(project, gfolder, tmp_path, capsys):
    put(project, "a", "Alpha beta gamma")
    gfolder.mkdir()
    assert run(capsys, "curate", "--project", "--done")[0] == 0
    assert passes(tmp_path) == {str(project.resolve()): TODAY.isoformat()}
    assert run(capsys, "curate", "--done")[0] == 0
    assert passes(tmp_path) == {str(project.resolve()): TODAY.isoformat(), str(gfolder.resolve()): TODAY.isoformat()}
    assert not (project / ".curated").exists() and not (gfolder / ".curated").exists()


def test_curate_covers_both_scopes_by_default_and_can_be_restricted(project, gfolder, capsys):
    put(project, "p1", "Retries need idempotency keys on payment calls")
    put(project, "p2", "Retries never need idempotency keys on payment calls")
    put(gfolder, "g1", "Granite worktops stain easily")
    put(gfolder, "g2", "Granite worktops stain easily always")
    both = run(capsys, "curate")[1]
    assert "m:p1" in both and "m:g1" in both
    only_p, only_g = run(capsys, "curate", "--project")[1], run(capsys, "curate", "--global")[1]
    assert "m:p1" in only_p and "m:g1" not in only_p and "m:g1" in only_g and "m:p1" not in only_g
    with pytest.raises(SystemExit):
        mem.main(["curate", "--all"])


# actions

def test_confirm_and_observe_alias(project, capsys):
    path = put(project, "a", "Alpha beta gamma")
    assert run(capsys, "confirm", "m:a") == (0, "m:a\tobserved 2\n", "")
    assert run(capsys, "observe", "m:a")[1] == "m:a\tobserved 3\n"
    assert f"last_observed: '{TODAY.isoformat()}'" in path.read_text()


def test_refute_and_forget_mark_and_append_reason(project, capsys):
    r = put(project, "r", "Alpha beta gamma", body="Old body.\n")
    f = put(project, "f", "Delta epsilon zeta")
    assert run(capsys, "refute", "m:r", "--because", "Measured wrong.") == (0, "m:r\trefuted\n", "")
    text = r.read_text()
    assert "status: refuted" in text and f"refuted: '{TODAY.isoformat()}'" in text
    assert text.endswith(f"Old body.\n\nRefuted {TODAY.isoformat()}:\nMeasured wrong.\n")
    assert run(capsys, "forget", "m:f") == (0, "m:f\tforgotten\n", "")
    assert "status: forgotten" in f.read_text() and f.read_text().endswith("---\n")


def test_unknown_handle_is_refused(project, capsys):
    put(project, "a", "Alpha beta gamma")
    code, out, err = run(capsys, "forget", "m:nope")
    assert (code, out) == (2, "") and err.startswith("mem: no memory named")


def test_supersede(project, capsys):
    old = put(project, "old", "Alpha beta gamma")
    put(project, "new", "Alpha beta gamma delta")
    assert run(capsys, "supersede", "m:old", "m:new") == (0, "m:old\tsuperseded by m:new\n", "")
    assert "status: superseded" in old.read_text() and "superseded_by: new" in old.read_text()
    assert run(capsys, "supersede", "m:old", "m:ghost")[0] == 2


def test_merge_sums_observed_appends_body_and_supersedes(project, capsys):
    keep = put(project, "keep", "Alpha beta gamma", observed=2, body="Keep body.\n")
    drop = put(project, "drop", "Alpha beta gamma delta", observed=3, body="Drop body.\n")
    assert run(capsys, "merge", "m:keep", "m:drop") == (0, "m:keep\tobserved 5, merged m:drop\n", "")
    assert keep.read_text().endswith(f"Keep body.\n\nMerged from m:drop on {TODAY.isoformat()}:\nDrop body.\n")
    assert "observed: 5" in keep.read_text()
    assert "status: superseded" in drop.read_text() and "superseded_by: keep" in drop.read_text()


def test_merge_with_empty_drop_body_adds_no_line(project, capsys):
    keep = put(project, "keep", "Alpha beta gamma", body="Keep body.\n")
    put(project, "drop", "Alpha beta gamma delta")
    assert run(capsys, "merge", "m:keep", "m:drop")[0] == 0
    assert keep.read_text().endswith("---\nKeep body.\n")


def test_merge_into_itself_is_refused(project, capsys):
    keep = put(project, "keep", "Alpha beta gamma")
    before = keep.read_text()
    code, _, err = run(capsys, "merge", "m:keep", "m:keep")
    assert code == 2 and "two different" in err and keep.read_text() == before


def test_merge_and_supersede_across_scopes_are_refused(project, gfolder, capsys):
    p = put(project, "p", "Alpha beta gamma")
    g = put(gfolder, "g", "Alpha beta gamma delta")
    before = (p.read_text(), g.read_text())
    for cmd in ("merge", "supersede"):
        code, _, err = run(capsys, cmd, "m:p", "m:g")
        assert code == 2 and "different scopes" in err
    assert (p.read_text(), g.read_text()) == before


def test_handle_in_both_scopes_means_project_and_global_flag_reaches_the_other(project, gfolder, capsys):
    p = put(project, "same", "Alpha beta gamma")
    g = put(gfolder, "same", "Alpha beta gamma")
    run(capsys, "confirm", "m:same")
    assert "observed: 2" in p.read_text() and "observed: 1" in g.read_text()
    run(capsys, "confirm", "m:same", "--global")
    assert "observed: 2" in g.read_text()
    code, out, _ = run(capsys, "merge", "m:same", "m:other", "--global")
    assert code == 2


def test_chain_with_a_forgotten_replacement_stays_hidden(project, capsys):
    put(project, "old", "Alpha beta gamma")
    put(project, "new", "Alpha beta gamma delta")
    run(capsys, "supersede", "m:old", "m:new")
    assert run(capsys, "forget", "m:new")[0] == 0
    assert run(capsys, "memories")[1] == ""
    assert run(capsys, "search", "--scope", "memories", "alpha beta gamma")[1] == ""
    assert run(capsys, "search", "--scope", "memories", "--all-memories", "alpha beta gamma")[1].count("m:") == 2


def test_dead_statuses_leave_search_and_return_with_all_memories(project, capsys):
    for h, claim, st in [("r", "Refuted quartz claim", "refuted"), ("s", "Superseded quartz claim", "superseded"),
                         ("f", "Forgotten quartz claim", "forgotten")]:
        put(project, h, claim, status=st)
    assert run(capsys, "search", "--scope", "memories", "quartz claim")[1] == ""
    out = run(capsys, "search", "--scope", "memories", "--all-memories", "quartz claim")[1]
    assert all(f"m:{h}" in out for h in "rsf") and "forgotten]" in out


def test_global_reason_goes_through_the_forbidden_terms(project, gfolder, tmp_path, capsys):
    f = tmp_path / "mem-config" / "agent-memory" / "forbidden-terms"
    f.parent.mkdir(parents=True)
    f.write_text("acme\n")
    g = put(gfolder, "g", "Alpha beta gamma")
    code, _, err = run(capsys, "forget", "m:g", "--because", "Acme broke it")
    assert code == 4 and "forbidden term" in err and "status: active" in g.read_text()
    assert run(capsys, "forget", "m:g", "--because", "Not true")[0] == 0


def test_promote_writes_nothing_and_prints_a_draft(project, capsys):
    p = put(project, "p", "Acme retries need keys", extra="context: the nightly job\n")
    before = p.read_text()
    code, out, _ = run(capsys, "promote", "m:p")
    assert code == 0 and p.read_text() == before
    lines = out.splitlines()
    assert lines[0] == 'Draft for: mem remember --global --kind lesson --claim "…"'
    assert lines[1] == "m:p\tAcme retries need keys" and lines[2] == "  context: the nightly job"
    assert lines[-1].startswith("Rewrite the claim in general terms, with no name of a project")


# guards

def _marker_less_store(tmp_path, monkeypatch):
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setenv("MEM_STORE", str(store))
    return store


@pytest.mark.parametrize("argv", [("confirm", "m:x"), ("refute", "m:x"), ("forget", "m:x"),
                                  ("supersede", "m:x", "m:y"), ("merge", "m:x", "m:y"),
                                  ("distinct", "m:x", "m:y"), ("restore", "m:x"), ("promote", "--no", "m:x")])
def test_actions_in_a_marker_less_store_are_refused(tmp_path, monkeypatch, capsys, argv):
    store = _marker_less_store(tmp_path, monkeypatch)
    git(store, "init", "-q")
    monkeypatch.setenv("MEM_PROJECT", str(store))
    x = put(store / ".memory", "x", "X thing here")
    put(store / ".memory", "y", "Y thing here")
    before = x.read_text()
    code, _, err = run(capsys, *argv)
    assert code == 2 and "read-only" in err and x.read_text() == before


def test_curate_done_in_a_marker_less_store_is_refused(tmp_path, monkeypatch, capsys):
    store = _marker_less_store(tmp_path, monkeypatch)
    git(store, "init", "-q")
    monkeypatch.setenv("MEM_PROJECT", str(store))
    put(store / ".memory", "x", "X thing here")
    code, _, err = run(capsys, "curate", "--done")
    assert code == 2 and "read-only" in err and not (store / ".memory" / ".curated").exists()


# amendment A: undo

def log_lines(folder):
    import json
    return [json.loads(ln) for ln in (folder / ".curation-log").read_text().splitlines()]


def test_every_action_logs_the_previous_text_before_writing(project, capsys):
    a = put(project, "a", "Alpha beta gamma", body="Body.\r\nCRLF line.\r\n")
    for h, c in (("b", "Delta epsilon zeta"), ("c", "Eta theta iota"), ("d", "Kappa lambda mu"), ("e", "Nu xi omicron")):
        put(project, h, c)
    before = {p.stem: p.read_bytes().decode() for p in project.glob("*.md")}
    run(capsys, "confirm", "m:a")
    run(capsys, "refute", "m:b")
    run(capsys, "forget", "m:c")
    run(capsys, "supersede", "m:d", "m:e")
    run(capsys, "distinct", "m:a", "m:e")
    run(capsys, "promote", "--no", "m:a")
    got = [(ln["action"], ln["handle"]) for ln in log_lines(project)]
    assert got == [("confirm", "a"), ("refute", "b"), ("forget", "c"), ("supersede", "d"), ("distinct", "a"),
                   ("distinct", "e"), ("promote", "a")]
    first = log_lines(project)[0]
    assert first["before"] == before["a"] and first["t"].endswith("Z") and len(first["t"]) == 20
    assert not list(project.glob("*.log"))
    assert run(capsys, "memories", "--dead")[1].count("m:") == 5  # the log is not read as a memory


def test_merge_logs_both_files_and_restore_undoes_each(project, capsys):
    keep = put(project, "keep", "Alpha beta gamma", observed=2, body="K.\n")
    drop = put(project, "drop", "Alpha beta gamma delta", body="D.\n")
    kb, db = keep.read_bytes(), drop.read_bytes()
    assert run(capsys, "merge", "m:keep", "m:drop")[0] == 0
    assert {(ln["action"], ln["handle"]) for ln in log_lines(project)} == {("merge", "keep"), ("merge", "drop")}
    logged_day = log_lines(project)[0]["t"][:10]  # the curation log dates in UTC, not local time
    code, out, _ = run(capsys, "restore", "m:keep")
    assert code == 0 and out == f"m:keep\trestored to before merge of {logged_day}\n" and keep.read_bytes() == kb
    assert run(capsys, "restore", "drop")[0] == 0 and drop.read_bytes() == db
    assert [ln["action"] for ln in log_lines(project)].count("restore") == 2


def test_restore_walks_back_step_by_step_to_the_original(project, capsys):
    a = put(project, "a", "Alpha beta gamma", body="Body.\n")
    states = [a.read_bytes()]
    for argv in (("confirm", "m:a"), ("refute", "m:a", "--because", "why"), ("forget", "m:a")):
        run(capsys, *argv)
        states.append(a.read_bytes())
    for expected in reversed(states[:-1]):
        assert run(capsys, "restore", "m:a")[0] == 0
        assert a.read_bytes() == expected
    code, out, err = run(capsys, "restore", "m:a")
    assert (code, out) == (2, "") and "no logged text" in err
    run(capsys, "forget", "m:a")  # a new action after the undo is undoable again
    assert run(capsys, "restore", "m:a")[0] == 0 and a.read_bytes() == states[0]
    put(project, "b", "Beta gamma delta")
    code, out, err = run(capsys, "restore", "m:b")
    assert (code, out) == (2, "") and err.startswith("mem: ")


def test_restore_a_body_with_a_unicode_line_separator(project, capsys):
    a = put(project, "a", "Alpha beta gamma", body="one\u2028two\u0085three\n")
    original = a.read_bytes()
    run(capsys, "forget", "m:a")
    assert run(capsys, "restore", "m:a")[0] == 0 and a.read_bytes() == original


def test_restore_reports_unreadable_log_lines_and_uses_the_newest_readable(project, capsys):
    a = put(project, "a", "Alpha beta gamma")
    original = a.read_bytes()
    run(capsys, "forget", "m:a")
    with (project / ".curation-log").open("a") as f:
        f.write("{not json\n")
    code, out, err = run(capsys, "restore", "m:a")
    assert code == 0 and a.read_bytes() == original
    assert err == "mem: skipped 1 unreadable lines in the curation log\n"


def test_restore_global_memory_needs_no_forbidden_list(project, gfolder, capsys):
    g = put(gfolder, "g", "Alpha beta gamma")
    original = g.read_bytes()
    run(capsys, "forget", "m:g")
    assert run(capsys, "restore", "m:g")[0] == 0 and g.read_bytes() == original


def test_merge_refuses_a_negation_or_a_number_unless_forced(project, capsys):
    k = put(project, "k", "Retries need idempotency keys on payment calls")
    put(project, "n", "Retries never need idempotency keys on payment calls")
    put(project, "v1", "The parser supports version 2.1 of the format")
    put(project, "v2", "The parser supports version 3 of the format")
    put(project, "ok", "Retries need idempotency keys on payment calls always")
    before = k.read_bytes()
    code, out, err = run(capsys, "merge", "m:k", "m:n")
    assert (code, out) == (2, "") and err == ("mem: these claims differ in never: they may be opposites or different "
                                              "versions; use --force to merge anyway.\n") and k.read_bytes() == before
    assert not (project / ".curation-log").exists()
    code, _, err = run(capsys, "merge", "m:v1", "m:v2")
    assert code == 2 and "2.1" in err and "3" in err
    assert run(capsys, "merge", "m:k", "m:n", "--force")[0] == 0
    assert run(capsys, "merge", "m:k", "m:ok")[0] == 0


@pytest.mark.parametrize("one, two", [
    ("The API exposes the v2 endpoint", "The API exposes the v3 endpoint"),
    ("The nightly job works", "The nightly job fails"),
    ("The cache is enable by default", "The cache is disable by default"),
])
def test_merge_refuses_versions_and_antonyms(project, capsys, one, two):
    put(project, "x", one)
    put(project, "y", two)
    code, out, err = run(capsys, "merge", "m:x", "m:y")
    assert (code, out) == (2, "") and "may be opposites or different versions" in err
    assert run(capsys, "merge", "m:x", "m:y", "--force")[0] == 0


def test_merge_allows_a_harmless_difference(project, capsys):
    put(project, "x", "The nightly job takes a long time")
    put(project, "y", "The nightly job takes a big long time")
    assert run(capsys, "merge", "m:x", "m:y")[0] == 0


def test_merge_refuses_a_word_ending_in_nt(project, capsys):
    put(project, "k", "Tests pass on the main branch")
    put(project, "n", "Tests don't pass on the main branch")
    assert run(capsys, "merge", "m:k", "m:n")[0] == 2


# amendment B: remembered decisions

def test_distinct_hides_the_pair_in_both_scopes_of_the_queue(project, capsys):
    a = put(project, "k1", "Retries need idempotency keys on payment calls")
    b = put(project, "k2", "Retries never need idempotency keys on payment calls")
    assert "m:k1" in run(capsys, "curate")[1]
    assert run(capsys, "distinct", "m:k1", "k2") == (0, "m:k1\tkept apart from m:k2\n", "")
    assert "distinct_from:\n- k2" in a.read_text() and "distinct_from:\n- k1" in b.read_text()
    assert run(capsys, "curate") == (0, "", "")
    assert run(capsys, "distinct", "m:k1", "m:k1")[0] == 2


def d_(n):
    return TODAY - datetime.timedelta(days=n)


def test_pairs_skips_distinct_and_refuted_pairs_are_listed_apart(tmp_path):
    ms = [records.Memory("project", tmp_path / f"{h}.md", h, "lesson", c, TODAY if st == "active" else d_(3), 1, st,
                         None, None, [], "", None, distinct_from=d)
          for h, c, st, d in [("a", "Retries need idempotency keys on every payment call", "active", ["b"]),
                              ("b", "Retries need idempotency keys on every payment call always", "active", []),
                              ("r", "Retries need idempotency keys on every payment call", "refuted", [])]]
    assert records.pairs(ms, TODAY, tokenize=mem.tokenize) == []
    got = records.refuted_pairs(ms, TODAY, tokenize=mem.tokenize)
    assert [(a.handle, b.handle) for a, b, _ in got] == [("a", "r"), ("b", "r")]


def test_promote_no_removes_the_memory_from_the_frequent_block(project, capsys):
    p = put(project, "often", "Zebra crossing lights flicker", observed=4)
    assert "m:often" in run(capsys, "curate")[1]
    code, out, _ = run(capsys, "promote", "--no", "m:often")
    assert code == 0 and out.startswith("m:often\t") and "promote: 'no'" in p.read_text()
    assert run(capsys, "curate") == (0, "", "")


def test_live_memory_written_again_after_a_refutation_gets_the_first_block(project, capsys):
    put(project, "old", "Retries need idempotency keys on payment calls", status="refuted", created=days_ago(3))
    put(project, "new", "Retries need idempotency keys on payment calls")
    code, out, _ = run(capsys, "curate")
    assert out.splitlines() == [
        "written again after being refuted (decide: mem refute <h>, or mem distinct <a> <b> if it is a different claim)",
        f"  m:new  [lesson, {days_ago(1)}]  Retries need idempotency keys on payment calls",
        f"  m:old  [lesson, {days_ago(3)}, refuted]  Retries need idempotency keys on payment calls"]
    run(capsys, "distinct", "m:new", "m:old")
    assert run(capsys, "curate") == (0, "", "")


def test_refuted_pairs_list_only_memories_written_after_the_refutation(tmp_path):
    def pair(live_created, refuted, r_created):
        ms = [records.Memory("project", tmp_path / "a.md", "a", "lesson", "Retries need keys", live_created, 1, "active",
                             None, None, [], "", None),
              records.Memory("project", tmp_path / "r.md", "r", "lesson", "Retries need keys", r_created, 1, "refuted",
                             None, None, [], "", None, refuted=refuted)]
        return records.refuted_pairs(ms, TODAY, tokenize=mem.tokenize)
    assert len(pair(d(1), d(3), d(9))) == 1
    assert pair(d(3), d(3), d(9)) == [] and pair(d(5), d(3), d(9)) == []
    assert len(pair(d(1), None, d(3))) == 1 and pair(d(3), None, d(3)) == []


# amendment C

def test_unconfirmed_counts_from_the_later_date_and_skips_standing_kinds(project, capsys):
    put(project, "con", "Pottery glaze needs cone six firing", kind="constraint", created=days_ago(200))
    put(project, "dec", "Ledger exports run nightly via cron", kind="decision", created=days_ago(200))
    put(project, "seen", "Granite worktops stain easily", created=days_ago(200), observed=2, extra=f"last_observed: '{days_ago(5)}'\n")
    put(project, "old", "Quartz clocks drift slowly", created=days_ago(200), observed=2, extra=f"last_observed: '{days_ago(100)}'\n")
    out = run(capsys, "curate")[1]
    assert "m:old" in out and "m:seen" not in out and "m:con" not in out and "m:dec" not in out
    assert records.load_memories(project, "project")[3].last_observed is not None


def test_state_memory_without_valid_until_expires_after_30_days(tmp_path):
    m = records.write_memory(tmp_path, "project", kind="state", claim="Migration window is open", body="", today=TODAY)
    assert m.valid_until == TODAY + datetime.timedelta(days=30)
    n = records.write_memory(tmp_path, "project", kind="state", claim="Other window is open", body="", today=TODAY,
                             valid_until=TODAY + datetime.timedelta(days=5))
    assert n.valid_until == TODAY + datetime.timedelta(days=5)
    assert f"valid_until: '{(TODAY + datetime.timedelta(days=30)).isoformat()}'" in m.path.read_text()


# amendment E

def test_handles_work_with_or_without_the_prefix(project, capsys):
    a = put(project, "a", "Alpha beta gamma")
    put(project, "b", "Delta epsilon zeta")
    assert run(capsys, "confirm", "a")[1] == "m:a\tobserved 2\n"
    assert run(capsys, "observe", "a")[1] == "m:a\tobserved 3\n"
    assert run(capsys, "refute", "b")[0] == 0
    assert run(capsys, "restore", "b")[0] == 0
    assert run(capsys, "supersede", "b", "m:a")[0] == 0
    assert run(capsys, "promote", "a")[0] == 0
    code, out, _ = run(capsys, "show", "a")
    assert code == 0 and "== m:a (project)" in out
    assert run(capsys, "show", "ghost")[0] == 2  # no store, no such memory


# amendment D: when a pass is due

def d(n):
    return TODAY - datetime.timedelta(days=n)


def _first(capsys):
    return run(capsys, "session-index")[1].splitlines()[0]


def _pair(folder, a="p1", b="p2", **kw):
    put(folder, a, "Retries need idempotency keys on payment calls", **kw)
    put(folder, b, "Retries never need idempotency keys on payment calls", **kw)


def test_remember_prints_no_curation_count(project, gfolder, capsys):
    for i in range(12):
        code, _, err = run(capsys, "remember", "--kind", "lesson", "--claim", f"Distinct lesson {i} about topic{i}.")
        assert code == 0 and "curation" not in err


def test_new_memories_alone_do_not_make_curation_due(project, gfolder, capsys):
    run(capsys, "curate", "--done")
    for i in range(15):
        put(project, f"m{i}", f"Unrelated topic{i} words{i} only{i} here{i}", created=days_ago(0))
    assert "Curation due" not in run(capsys, "session-index")[1]


def test_done_clears_the_count_and_a_new_pair_counts_one(project, gfolder, capsys):
    put(project, "o1", "Retries need idempotency keys on payment calls")
    put(project, "o2", "Pottery glaze firing temperature chart")
    run(capsys, "curate", "--done")
    put(project, "n1", "Retries never need idempotency keys on payment calls", created=days_ago(0))
    assert _first(capsys).endswith("Curation due: 1 item (1 same or opposite) (run mem curate after the current task).")
    run(capsys, "curate", "--done")
    assert "Curation due" not in run(capsys, "session-index")[1]
    put(project, "n2", "Pottery glaze firing temperature chart today", created=days_ago(0))  # pairs with o2 only
    assert "Curation due: 1 item (1 same or opposite)" in _first(capsys)


def test_done_on_a_mixed_store_leaves_no_line(project, gfolder, capsys):
    put(project, "act", "Retries need idempotency keys on payment calls")
    put(project, "old", "Retries never need idempotency keys on payment calls", extra="superseded_by: act\n")
    put(project, "unc", "Cache invalidation needs explicit versions", extra="origin: transcript\nweight: medium\n"
        "sources:\n- session a\n")
    put(project, "exp", "Cache warmup takes long", extra=f"valid_until: '{days_ago(3)}'\n")
    put(project, "s1", "Deploy freeze runs until the migration ends", kind="state", created=days_ago(5))
    put(project, "s2", "Deploy freeze runs until the migration is done", kind="state", created=days_ago(1))
    put(project, "r1", "Queues drain slowly under heavy load tonight")
    put(project, "gone", "Queues drain slowly under heavy load tonight", status="refuted")
    put(project, "q", "Quarantined lesson about gizmos", extra="quarantine: true\n")
    put(gfolder, "g", "General lesson about widgets", observed=4)
    put(gfolder, "gq", "General lesson about widgets and gadgets", observed=1,
        extra="origin: transcript\nweight: medium\nsources:\n- session b\n")
    assert records.quarantined(records.load_memories(gfolder, "global")[1])
    assert "Curation due" in run(capsys, "session-index")[1]
    run(capsys, "curate", "--done")
    assert "Curation due" not in run(capsys, "session-index")[1]


def test_done_prints_recorded_items(project, gfolder, capsys):
    put(project, "exp", "Cache warmup takes long", extra=f"valid_until: '{days_ago(3)}'\n")
    _pair(gfolder, "g1", "g2")
    put(gfolder, "g3", "Pottery glaze firing chart")
    code, out, _ = run(capsys, "curate", "--done")
    assert code == 0 and out == "recorded 1 item (global)\nrecorded 1 item (project)\n"


def test_count_names_its_parts(project, gfolder, capsys):
    run(capsys, "curate", "--done")
    _pair(project, created=days_ago(0))
    put(project, "e1", "Cache warmup takes long", extra=f"valid_until: '{days_ago(3)}'\n")
    put(project, "e2", "Seat belts fastened early", extra=f"valid_until: '{days_ago(3)}'\n")
    put(project, "s", "Gizmo habits repeat often", observed=4)
    assert _first(capsys).endswith("Curation due: 4 items (1 same or opposite, 2 expired, 1 seen often) "
                                   "(run mem curate after the current task).")


def _set_pass(folder, days):
    mem._write_passes(os.environ, [folder], TODAY - datetime.timedelta(days=days))


def test_old_pairs_are_not_searched_after_a_pass_without_marks(project, gfolder, capsys):
    for h, c in (("k1", "Retries need idempotency keys on payment calls"),
                 ("k2", "Retries never need idempotency keys on payment calls")):
        _age(put(project, h, c, created=days_ago(30)), 30)
    _set_pass(project, 10)
    assert "Curation due" not in run(capsys, "session-index")[1]


def test_edited_old_memory_pair_is_counted(project, gfolder, capsys):
    paths = [put(project, h, c, created=days_ago(30)) for h, c in (
        ("k1", "Retries need idempotency keys on payment calls"),
        ("k2", "Retries never need idempotency keys on payment calls"))]
    for p in paths:
        _age(p, 30)
    _set_pass(project, 10)
    os.utime(paths[1], None)
    assert "Curation due: 1 item (1 same or opposite)" in _first(capsys)


@pytest.mark.parametrize("raw", ["[]", '"x"', "{bad", '{"a": "k"}', '{"a": [1]}', '{"a": {"b": 1}}'])
def test_marks_file_malformed_reads_as_none(tmp_path, raw):
    data = tmp_path / "mem-data"
    data.mkdir(exist_ok=True)
    (data / "curated-items.json").write_text(raw)
    assert mem.read_marks(os.environ) == {}


def test_done_global_keeps_project_marks(project, gfolder, tmp_path, capsys):
    import json
    put(project, "exp", "Cache warmup takes long", extra=f"valid_until: '{days_ago(3)}'\n")
    put(gfolder, "gexp", "Seat belts fastened early", extra=f"valid_until: '{days_ago(3)}'\n")
    run(capsys, "curate", "--done")
    path = tmp_path / "mem-data" / "curated-items.json"
    before = json.loads(path.read_text())
    put(gfolder, "gexp2", "Other seat habits matter", extra=f"valid_until: '{days_ago(3)}'\n")
    run(capsys, "curate", "--global", "--done")
    after = json.loads(path.read_text())
    assert after[str(project.resolve())] == before[str(project.resolve())] == ["expired:exp"]
    assert after[str(gfolder.resolve())] == ["expired:gexp", "expired:gexp2"]


def test_curated_json_keeps_its_format(project, gfolder, tmp_path, capsys):
    put(project, "exp", "Cache warmup takes long", extra=f"valid_until: '{days_ago(3)}'\n")
    run(capsys, "curate", "--project", "--done")
    assert passes(tmp_path) == {str(project.resolve()): TODAY.isoformat()}


def _session(project, gfolder):
    return mem.session_index(None, project, gfolder, TODAY, passes=mem.read_passes(os.environ),
                             marks=mem.read_marks(os.environ))


def test_budget_shared_across_folders_never_exceeded(project, gfolder, monkeypatch):
    for i in range(6):
        put(project, f"p{i}", f"Project topic{i} alpha{i} beta{i} gamma{i} delta{i}")
        put(gfolder, f"g{i}", f"Global topic{i} alpha{i} beta{i} gamma{i} delta{i}")
    made = []
    real = records.Budget

    def wrapped(left):
        made.append(real(left))
        return made[-1]
    monkeypatch.setattr(records, "Budget", wrapped)
    monkeypatch.setattr(mem, "PAIR_WORK", 20)
    _session(project, gfolder)
    assert len(made) == 1 and made[0].left >= 0 and made[0].left < 20


def test_past_the_budget_found_items_say_at_least_and_none_say_nothing(project, gfolder, monkeypatch):
    _pair(project, created=days_ago(5))
    _age(project / "p1.md", 5)
    _age(project / "p2.md", 5)
    for i in range(10):  # newer, so they are compared first and use the budget
        put(project, f"u{i}", f"Unrelated topic{i} words{i} only{i} here{i}", created=days_ago(0))
    _set_pass(project, 10)
    monkeypatch.setattr(mem, "PAIR_WORK", 3)
    assert "Curation due" not in _session(project, gfolder)
    monkeypatch.setattr(mem, "PAIR_WORK", 150_000)
    assert "Curation due: 1 item" in _session(project, gfolder)
    put(project, "e1", "Cache warmup takes long", extra=f"valid_until: '{days_ago(3)}'\n")
    monkeypatch.setattr(mem, "PAIR_WORK", 3)
    assert "Curation due: at least 1 item (1 expired)" in _session(project, gfolder)


def test_count_failure_keeps_the_rules(project, gfolder, monkeypatch):
    put(project, "r1", "Always run the linter before committing", extra="reach: general\n")
    put(project, "exp", "Cache warmup takes long", extra=f"valid_until: '{days_ago(3)}'\n")
    clean = _session(project, gfolder)
    assert "Curation due" in clean

    def boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(mem, "_decisions", boom)
    text = _session(project, gfolder)
    assert "Curation due" not in text and "This project: 1 memories." in text
    assert text.splitlines()[1:] == clean.splitlines()[1:]


def test_session_index_near_the_budget_is_fast(project, gfolder):
    import time
    words = [f"w{i}" for i in range(2000)]
    project.mkdir(parents=True, exist_ok=True)
    for i in range(2000):
        claim = " ".join(words[(i * 7 + j) % 2000] for j in range(60))
        changed = i < 70  # created and written after the pass; the rest were there at the pass
        _age(put(project, f"m{i}", claim, created=days_ago(0 if changed else 30)), 0 if changed else 30)
    _set_pass(project, 10)
    loaded = records.load_memories(project, "project")
    budget = records.Budget(mem.PAIR_WORK)
    assert mem._decisions(loaded, TODAY, since=TODAY - datetime.timedelta(days=10), budget=budget).pairs_checked
    start = time.perf_counter()
    _session(project, gfolder)
    took = time.perf_counter() - start
    assert took < 2  # half the hook's 4 s; measured 0.95 to 1.04 s here, 0.80 s alone (0.48 s without the count)


# fix round 1: decisions that stay decided

def test_confirm_until_sets_valid_until_and_leaves_the_expired_block(project, capsys):
    p = put(project, "exp", "Cache warmup takes long", extra=f"valid_until: '{days_ago(3)}'\n")
    assert "m:exp" in run(capsys, "curate")[1]
    until = (TODAY + datetime.timedelta(days=30)).isoformat()
    assert run(capsys, "confirm", "m:exp", "--until", until)[0] == 0
    assert f"valid_until: '{until}'" in p.read_text() or f"valid_until: {until}" in p.read_text()
    assert "observed: 2" in p.read_text()
    assert run(capsys, "curate") == (0, "", "")
    assert run(capsys, "confirm", "m:exp", "--until", "soon")[0] == 2


def test_superseded_by_memory_is_never_listed(project, capsys):
    put(project, "exp", "Cache warmup takes long", observed=5, created=days_ago(200),
        extra=f"valid_until: '{days_ago(3)}'\nsuperseded_by: other\n")
    assert run(capsys, "curate") == (0, "", "")


def test_promote_done_records_and_removes_from_the_frequent_block(project, capsys):
    p = put(project, "often", "Zebra crossing lights flicker", observed=4)
    before = p.read_bytes()
    code, out, _ = run(capsys, "promote", "--done", "m:often")
    assert (code, out) == (0, "m:often\tpromoted\n") and "promote: done" in p.read_text()
    assert run(capsys, "curate") == (0, "", "")
    assert [ln["action"] for ln in log_lines(project)] == ["promote"]
    assert run(capsys, "restore", "m:often")[0] == 0 and p.read_bytes() == before
    out = run(capsys, "promote", "m:often")[1]
    assert out.splitlines()[-1].endswith("before you run it; then run: mem promote --done <h>")


# fix round 1 of Task 3

def test_a_folder_whose_count_failed_says_at_least(project, gfolder, monkeypatch):
    put(project, "r1", "Always run the linter before committing", extra="reach: general\n")
    put(project, "exp", "Cache warmup takes long", extra=f"valid_until: '{days_ago(3)}'\n")
    put(gfolder, "g", "General lesson about widgets", observed=4)
    real = mem._decisions

    def flaky(loaded, today, **kw):
        if loaded and loaded[0].scope == "global":
            raise RuntimeError("boom")
        return real(loaded, today, **kw)
    monkeypatch.setattr(mem, "_decisions", flaky)
    text = _session(project, gfolder)
    assert "Curation due: at least 1 item (1 expired)" in text and "This project: 1 memories." in text


def test_done_that_fails_writing_marks_keeps_the_old_pass_date(project, gfolder, monkeypatch, capsys):
    put(project, "exp", "Cache warmup takes long", extra=f"valid_until: '{days_ago(3)}'\n")
    _set_pass(project, 10)
    old = mem.read_passes(os.environ)

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(mem, "_write_marks", boom)
    assert run(capsys, "curate", "--done")[0] == 2
    assert mem.read_passes(os.environ) == old


def test_write_marks_does_not_drop_keys_it_could_not_read(tmp_path, monkeypatch):
    env = {"MEM_DATA": str(tmp_path / "data")}
    other, covered = tmp_path / "a", tmp_path / "b"
    other.mkdir()
    covered.mkdir()
    mem._write_marks(env, {other: ["x"]})
    path = mem._marks_file(env)
    real = type(path).read_text

    def failing(self, *a, **k):
        if self == path:
            raise OSError("denied")
        return real(self, *a, **k)
    monkeypatch.setattr(type(path), "read_text", failing)
    with pytest.raises(OSError):
        mem._write_marks(env, {covered: ["y"]})
    monkeypatch.undo()
    assert mem.read_marks(env) == {str(other.resolve()): frozenset({"x"})}
    path.write_text("not json", encoding="utf-8")  # malformed stays lenient
    mem._write_marks(env, {covered: ["y"]})
    assert mem.read_marks(env) == {str(covered.resolve()): frozenset({"y"})}
    path.write_bytes(b"\xff\xfe\x00bad")  # not UTF-8: malformed too, not unreadable
    assert mem.read_marks(env) == {}
    mem._write_marks(env, {covered: ["z"]})
    assert mem.read_marks(env) == {str(covered.resolve()): frozenset({"z"})}


def test_marks_file_not_utf8_keeps_the_session_index(project, gfolder, tmp_path, capsys):
    put(project, "exp", "Cache warmup takes long", extra=f"valid_until: '{days_ago(3)}'\n")
    (tmp_path / "mem-data").mkdir(exist_ok=True)
    (tmp_path / "mem-data" / "curated-items.json").write_bytes(b"\xff\xfe\x00bad")
    first = run(capsys, "session-index")[1].splitlines()[0]
    assert first.startswith("memory: the mem command") and "Curation due: 1 item (1 expired)" in first
    assert run(capsys, "curate", "--done")[0] == 0


def _state_pair(folder, scope):
    put(folder, "s-old", "Migration window is open for the billing service", kind="state", created=days_ago(9))
    put(folder, "s-new", "Migration window is open for the billing service now", kind="state", created=days_ago(2))
    return mem._decisions(records.load_memories(folder, scope), TODAY)


def test_newer_state_is_a_project_matter(project, gfolder):
    found = _state_pair(project, "project")
    assert len(found.state) == 1 and found.same == []
    found = _state_pair(gfolder, "global")
    assert found.state == [] and len(found.same) == 1
