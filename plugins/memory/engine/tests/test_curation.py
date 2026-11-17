import datetime
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
        f"  m:k2  [lesson, {days_ago(1)}]  Retries never need idempotency keys on payment calls",
        "  differ in: never",
        "expired (decide: mem forget <h>, or mem remember again with a new date)",
        f"  m:exp  valid until {days_ago(3)}  Cache warmup takes long",
        "seen 3 times or more: general enough for a note? (mem promote <h>)",
        "  m:often  observed 4  Zebra crossing lights flicker",
        "not confirmed in 90 days (decide: mem confirm <h> or mem forget <h>)",
        f"  m:stale  {days_ago(120)}  Quartz clocks drift slowly",
    ]


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
    code, out, _ = run(capsys, "restore", "m:keep")
    assert code == 0 and out == f"m:keep\trestored to before merge of {TODAY.isoformat()}\n" and keep.read_bytes() == kb
    assert run(capsys, "restore", "drop")[0] == 0 and drop.read_bytes() == db
    assert [ln["action"] for ln in log_lines(project)].count("restore") == 2


def test_restore_twice_undoes_the_restore_and_unknown_log_exits_2(project, capsys):
    a = put(project, "a", "Alpha beta gamma")
    original = a.read_bytes()
    run(capsys, "forget", "m:a")
    forgotten = a.read_bytes()
    run(capsys, "restore", "m:a")
    assert a.read_bytes() == original
    code, out, _ = run(capsys, "restore", "m:a")
    assert out.startswith("m:a\trestored to before restore of") and a.read_bytes() == forgotten
    put(project, "b", "Beta gamma delta")
    code, out, err = run(capsys, "restore", "m:b")
    assert (code, out) == (2, "") and err.startswith("mem: ")


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


def test_pairs_skips_distinct_and_refuted_pairs_are_listed_apart(tmp_path):
    ms = [records.Memory("project", tmp_path / f"{h}.md", h, "lesson", c, TODAY, 1, st, None, None, [], "", None,
                         distinct_from=d)
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
    put(project, "old", "Retries need idempotency keys on payment calls", status="refuted")
    put(project, "new", "Retries need idempotency keys on payment calls")
    code, out, _ = run(capsys, "curate")
    assert out.splitlines() == [
        "written again after being refuted (decide: mem refute <h>, or mem distinct <a> <b> if it is a different claim)",
        f"  m:new  [lesson, {days_ago(1)}]  Retries need idempotency keys on payment calls",
        f"  m:old  [lesson, {days_ago(1)}, refuted]  Retries need idempotency keys on payment calls"]
    run(capsys, "distinct", "m:new", "m:old")
    assert run(capsys, "curate") == (0, "", "")


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

def mems(tmp_path, specs):
    return [records.Memory("project", tmp_path / f"{i}.md", str(i), "lesson", "c", created, 1, "active", None, vu, [], "", None)
            for i, (created, vu) in enumerate(specs)]


def d(n):
    return TODAY - datetime.timedelta(days=n)


def test_curation_due_rule(tmp_path):
    due = records.curation_due
    assert due(mems(tmp_path, [(d(1), None)] * 10), d(2), TODAY) == 10
    assert due(mems(tmp_path, [(d(1), None)] * 9), d(2), TODAY) == 0
    assert due(mems(tmp_path, [(d(1), None)] * 2), d(14), TODAY) == 2
    assert due(mems(tmp_path, [(d(1), None)] * 2), d(13), TODAY) == 0
    assert due(mems(tmp_path, [(d(20), None), (d(1), None)]), None, TODAY) == 2
    assert due(mems(tmp_path, [(d(3), None)]), None, TODAY) == 0
    assert due([], d(30), TODAY) == 0
    # created on the day of the last pass is not new
    assert due(mems(tmp_path, [(d(14), None)]), d(14), TODAY) == 0
    # a live memory past valid_until counts and makes a pass due
    assert due(mems(tmp_path, [(d(30), d(1)), (d(30), None)]), d(1), TODAY) == 1


def test_index_line_says_curation_is_due(project, gfolder, tmp_path, capsys):
    run(capsys, "curate", "--done")
    for i in range(3):
        put(project, f"m{i}", f"Unrelated thing number {'x' * i}", created=days_ago(0))
    assert "Curation due" not in run(capsys, "session-index")[1]
    put(project, "exp", "Cache warmup takes long", extra=f"valid_until: '{days_ago(3)}'\n")
    first = run(capsys, "session-index")[1].splitlines()[0]
    assert first.endswith("Curation due: 1 items (run mem curate after the current task).")
    assert "This project: 3 memories. Curation due" in first
