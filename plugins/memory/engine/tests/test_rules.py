import dataclasses
import datetime
import os
import subprocess

import pytest

import mem
import records
import rules

TODAY = datetime.date.today()
K1, K2, K3 = "0123456789ab", "ba9876543210", "aaaaaaaaaaaa"


@pytest.fixture
def gfolder(tmp_path, monkeypatch):
    folder = tmp_path / "gmem"
    monkeypatch.setenv("MEM_MEMORIES", str(folder))
    return folder


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    monkeypatch.setenv("MEM_PROJECT", str(root))
    return root


def write(claim, *, short=None, topic=None, scope="global", sessions=("a", "b"), weight="light", extra=(), pending=False):
    """A transcript lesson; each session is seen in its own project, so a global one holds in two projects."""
    args = ["remember", "--kind", "lesson", "--claim", claim, "--origin", "transcript", "--weight", weight,
            "--reach", "general"]
    if scope == "global":
        args.append("--global")
    for i, s in enumerate(sessions):
        args += ["--source", f"session {s} project {[K1, K2, K3][i]}"]
    if short:
        args += ["--short", short]
    if topic:
        args += ["--topic", topic]
    assert mem.main([*args, *extra]) == 0
    for m in records.load_memories(records.Path(os.environ["MEM_MEMORIES"]), "global"):
        if m.triage == "pending" and not pending:  # a lesson that left quarantine awaits the owner's triage
            assert mem.main(["triage", "accept", m.handle]) == 0


def load(folder, scope):
    return {m.claim: m for m in records.load_memories(folder, scope)}


def confirm(handle):
    assert mem.main(["confirm", f"m:{handle}", "--global", "--by-owner"]) == 0


def test_what_loads_and_what_does_not(project, gfolder):
    write("Confirmed global lesson one.", short="Confirmed global rule.", topic="testing", sessions=("a",), weight="strong")
    confirm(load(gfolder, "global")["Confirmed global lesson one."].handle)
    write("Project lesson seen twice.", short="Twice in the project.", topic="process", scope="project")
    write("Project lesson seen once.", short="Once in the project.", scope="project", sessions=("a",))
    write("Turned off lesson.", short="Turned off rule.")
    write("Quarantined lesson.", short="Quarantined rule.", sessions=("a",))
    write("Lesson without a short form.")
    mem.main(["remember", "--global", "--kind", "lesson", "--claim", "Hand written lesson.", "--short", "Hand rule."])
    g = load(gfolder, "global")
    off = g["Turned off lesson."]
    assert mem.main(["memory", "edit", f"m:{off.handle}", "--global", "--no-load"]) == 0
    g = load(gfolder, "global")
    p = load(project / ".memory", "project") if (project / ".memory").is_dir() else load(records.project_dir(project), "project")
    assert records.quarantined(g["Quarantined lesson."])
    choice = rules.choose(list(p.values()), list(g.values()), TODAY)
    assert {m.claim for m in choice.loaded} == {"Confirmed global lesson one.", "Project lesson seen twice."}
    assert choice.left == [] and choice.unready == 1


def test_order_inside_a_group():
    base = _base()
    day = datetime.date(2026, 1, 10)
    plain = dataclasses.replace(base, last_observed=day)  # light, two sessions in two projects
    ordered = [
        dataclasses.replace(plain, handle="a", owner_confirmed=day),
        dataclasses.replace(plain, handle="b", weight="medium"),
        dataclasses.replace(plain, handle="c", sources=_sources("s1", "s2", "s3", keys=(K1, K2, K3))),
        dataclasses.replace(plain, handle="d", sources=_sources("s1", "s2", "s3", keys=(K1, K2, K1))),
        dataclasses.replace(plain, handle="e"),
        dataclasses.replace(plain, handle="f", last_observed=None),
    ]
    shuffled = [ordered[i] for i in (3, 5, 1, 0, 4, 2)]
    assert [m.handle for m in rules.choose([], shuffled, TODAY).loaded] == ["a", "b", "c", "d", "e", "f"]
    twins = [dataclasses.replace(plain, handle="y"), dataclasses.replace(plain, handle="x")]
    assert [m.handle for m in rules.choose([], twins, TODAY).loaded] == ["x", "y"]


def test_project_lessons_come_first_and_take_at_most_three():
    base = _base()
    proj = [dataclasses.replace(base, scope="project", handle=f"p{i}", sources=_sources("s1", "s2", keys=(K1, K1)))
            for i in range(5)]
    glob = [dataclasses.replace(base, scope="global", handle=f"g{i}", weight="strong", owner_confirmed=TODAY)
            for i in range(5)]
    choice = rules.choose(proj, glob, TODAY)
    assert [m.handle for m in choice.loaded] == ["p0", "p1", "p2", "g0", "g1", "g2"]
    assert {m.handle for m, why in choice.left} == {"p3", "p4", "g3", "g4"}


def test_lines_carry_the_standing_written_by_code():
    base = _base()
    confirmed = dataclasses.replace(base, short="Run the checks before reporting a change.", owner_confirmed=TODAY)
    global_two_projects = dataclasses.replace(base, scope="global", short="X.", sources=_sources("s1", "s2", keys=(K1, K2)))
    project_three = dataclasses.replace(base, scope="project", short="Y.", sources=_sources("s1", "s2", "s3", keys=(K1, K1, K1)))
    assert rules.line(confirmed) == "- Run the checks before reporting a change. (the user vouched for it)"
    assert rules.line(global_two_projects).endswith("(held in 2 projects)")
    assert rules.line(project_three).endswith("(held in 3 sessions)")
    one_project = dataclasses.replace(base, scope="global", short="X.", sources=_sources("s1", keys=(K1,)))
    one_session = dataclasses.replace(base, scope="project", short="Y.", sources=_sources("s1", keys=(K1,)))
    assert rules.line(one_project).endswith("(held in 1 project)")
    assert rules.line(one_session).endswith("(held in 1 session)")


def test_never_more_than_six_lines_or_900_characters():
    base = _base()
    many = [dataclasses.replace(base, handle=f"g{i}", short=f"{i}" + "x" * 119, owner_confirmed=TODAY) for i in range(10)]
    choice = rules.choose([], many, TODAY)
    assert len(choice.loaded) <= 6
    assert sum(len(rules.line(m)) + 1 for m in choice.loaded) <= 900
    assert len(choice.loaded) + len(choice.left) == 10
    assert all(why == "over the limit" for _, why in choice.left)
    assert len(choice.loaded) == 6 and len(choice.left) == 4  # the count binds first: no line can pass 147 characters


def test_pending_triage_is_counted_not_loaded():
    base = _base()
    waiting = dataclasses.replace(base, handle="w", triage="pending")
    noshort = dataclasses.replace(base, handle="n", triage="pending", short=None)
    ready = dataclasses.replace(base, handle="r")
    choice = rules.choose([], [waiting, noshort, ready], TODAY)
    assert [m.handle for m in choice.loaded] == ["r"]
    assert [(m.handle, why) for m, why in choice.left] == [("w", "awaits triage"), ("n", "awaits triage")]
    assert choice.unready == 0


def test_the_line_after_the_rules_counts_only_what_did_not_fit():
    base = _base()
    waiting = dataclasses.replace(base, handle="w", triage="pending", topic="waiting")
    over = dataclasses.replace(base, handle="o", topic="shell")
    assert rules.more_line(rules.Choice(left=[(waiting, rules.PENDING)])) is None
    text = rules.more_line(rules.Choice(left=[(waiting, rules.PENDING), (over, rules.OVER)]))
    assert text == "1 more lesson by topic: shell 1 (mem rules --more <topic>, when a topic fits your task)"
    assert "waiting" not in text


def test_the_project_group_is_split_by_position():
    base = _base()
    twins = [dataclasses.replace(base, scope="project", handle=f"p{i}", owner_confirmed=TODAY) for i in range(5)]
    choice = rules.choose(twins, [], TODAY)
    assert len(choice.loaded) == 5 and choice.left == []


def test_quarantine_and_turned_off_lessons_are_nowhere(project, gfolder, capsys):
    write("Quarantined lesson.", short="Quarantined rule.", topic="secret", sessions=("a",))
    write("Turned off lesson.", short="Turned off rule.", topic="secret")
    g = load(gfolder, "global")
    assert mem.main(["memory", "edit", f"m:{g['Turned off lesson.'].handle}", "--global", "--no-load"]) == 0
    base = _base()
    shown = [dataclasses.replace(base, handle=f"s{i}", short="x" * 120, owner_confirmed=TODAY) for i in range(7)]
    g = load(gfolder, "global")
    choice = rules.choose([], [*g.values(), *shown], TODAY)
    assert len(choice.left) == 1 and choice.unready == 0
    text = "\n".join([*rules.block(choice), rules.more_line(choice) or ""])
    assert "secret" not in text and "Quarantined" not in text and "Turned off" not in text
    capsys.readouterr()
    assert mem.main(["rules", "--more"]) == 0
    out = capsys.readouterr().out
    assert "secret" not in out and "Quarantined lesson" not in out and "Turned off lesson" not in out


def test_a_project_record_linked_to_a_loaded_global_one_loads_once():
    base = _base()
    glob = dataclasses.replace(base, scope="global", handle="g", owner_confirmed=TODAY)
    proj = dataclasses.replace(base, scope="project", handle="p", general="g", owner_confirmed=TODAY)
    other = dataclasses.replace(base, scope="project", handle="q", general="nobody", owner_confirmed=TODAY)
    choice = rules.choose([proj, other], [glob], TODAY)
    assert sorted(m.handle for m in choice.loaded) == ["g", "q"]
    assert choice.left == []


def test_a_project_record_linked_to_a_global_one_that_cannot_load_still_loads():
    base = _base()
    glob = dataclasses.replace(base, scope="global", handle="g", owner_confirmed=TODAY, short=None)
    waiting = dataclasses.replace(base, scope="global", handle="w", owner_confirmed=TODAY, triage="pending")
    p1 = dataclasses.replace(base, scope="project", handle="p", general="g", owner_confirmed=TODAY)
    p2 = dataclasses.replace(base, scope="project", handle="r", general="m:w", owner_confirmed=TODAY)
    choice = rules.choose([p1, p2], [glob, waiting], TODAY)
    assert sorted(m.handle for m in choice.loaded) == ["p", "r"]
    assert [m.handle for m, _ in choice.left] == ["w"] and choice.unready == 1


def _left(topics):
    base = _base()
    return rules.Choice(left=[(dataclasses.replace(base, handle=f"h{i}", topic=t), "over the limit")
                              for i, t in enumerate(topics)])


def test_more_line_names_topics_by_frequency_and_fits():
    topics = ["testing"] * 3 + ["process"] * 2 + ["shell", None]
    choice = _left(topics)
    assert rules.more_line(choice) == "7 more lessons by topic: testing 3, process 2, shell 1, other 1 (mem rules --more <topic>, when a topic fits your task)"
    five = _left(["a"] * 5 + ["b"] * 4 + ["c"] * 3 + ["d"] * 2 + ["e"])
    assert rules.more_line(five) == "15 more lessons by topic: a 5, b 4, c 3, d 2, other 1 (mem rules --more <topic>, when a topic fits your task)"
    long = _left([f"{c}" * 24 for c in "abcdefg" for _ in range(2)])
    text = rules.more_line(long)
    assert len(text) <= 200 and "other" in text


def test_more_line_singular_and_without_topics():
    assert rules.more_line(_left([None])) == "1 more lesson: mem rules --more"
    assert rules.more_line(_left([None, None])) == "2 more lessons: mem rules --more"
    assert rules.more_line(_left(["testing"])).startswith("1 more lesson by topic: testing 1")


def test_nothing_qualifies_gives_an_empty_block_and_no_line():
    choice = rules.choose([], [], TODAY)
    assert rules.block(choice) == [] and rules.more_line(choice) is None


def test_more_with_a_topic_prints_only_that_group(project, gfolder, capsys):
    topics = [None] * 6 + ["testing", "testing", "shell"]
    for i, topic in enumerate(topics):
        write(f"Lesson number {i}.", short=f"Rule {i}.", topic=topic)
    capsys.readouterr()
    assert mem.main(["rules", "--more", "testing"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 3 and all(x.split("\t")[2] == "over the limit" and x.split("\t")[4] == "testing" for x in out[:2])
    assert out[2] == "mem show m:<handle> prints a whole lesson."
    assert mem.main(["rules", "--more", "shell"]) == 0
    assert len(capsys.readouterr().out.splitlines()) == 2
    assert mem.main(["rules", "--more", "other"]) == 0
    assert capsys.readouterr().out == "No lessons left out under other.\n"
    assert mem.main(["rules", "--more"]) == 0
    assert [x.split("\t")[4] for x in capsys.readouterr().out.splitlines()[:-1]] == ["testing", "testing", "shell"]


def test_mem_rules_and_more(project, gfolder, capsys):
    assert mem.main(["rules"]) == 0
    assert capsys.readouterr().out == "No rules loaded.\n"
    write("Needs a short form.")
    capsys.readouterr()
    assert mem.main(["rules"]) == 0
    assert capsys.readouterr().out == ("No rules loaded.\n1 established lesson has no short form yet: "
                                       "the background pass writes them when auto_capture is on (mem-corroborate status shows the last one).\n")
    # nine more that fit only six, each with a topic
    for i in range(8):
        write(f"Lesson {i} about things in general.", short=f"Rule {i} " + "y" * 100, topic="testing" if i % 2 else None)
    capsys.readouterr()
    assert mem.main(["rules"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == rules.HEADER and len(out) == 1 + 6 + 1 and out[-1].startswith("2 more lessons")
    assert all(x.endswith("(held in 2 projects)") for x in out[1:7])
    assert mem.main(["rules", "--more"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 2 + 1 + 1
    assert all(x.startswith("m:") and x.split("\t")[1:4] == ["global", "over the limit", "(held in 2 projects)"] for x in out[:2])
    assert out[2] == "mem show m:<handle> prints a whole lesson."
    assert out[-1].startswith("1 established lesson has no short form")
    assert mem.main(["rules", "--more", "nonexistent"]) == 0
    assert "No lessons left out under nonexistent." in capsys.readouterr().out


def _sources(*sessions, keys):
    return [f"session {s} project {k}" for s, k in zip(sessions, keys)]


def _base():
    """One valid, established, loadable global record to derive the others from."""
    return records.Memory(scope="global", path=None, handle="base", kind="lesson", claim="A claim.",
                          created=datetime.date(2026, 1, 1), observed=1, status="active", context=None,
                          valid_until=None, sources=_sources("s1", "s2", keys=(K1, K2)), body="", error=None,
                          origin="transcript", weight="light", short="A short rule.")


def test_an_index_only_lesson_never_loads_and_is_counted_with_its_reason():
    base = _base()
    idx = dataclasses.replace(base, handle="i", load="index", topic="shell")
    noshort = dataclasses.replace(base, handle="n", load="index", short=None)
    ready = dataclasses.replace(base, handle="r")
    waiting = dataclasses.replace(base, handle="w", load="index", triage="pending")
    assert rules.eligible(idx, TODAY)
    choice = rules.choose([], [idx, noshort, ready, waiting], TODAY)
    assert [m.handle for m in choice.loaded] == ["r"]
    assert sorted((m.handle, why) for m, why in choice.left) == [("i", "index only"), ("n", "index only"), ("w", "awaits triage")]
    assert choice.unready == 0
    assert [m.handle for m, _ in rules.not_fitted(choice)] == ["i", "n"]
    assert rules.more_line(choice) == "2 more lessons by topic: shell 1, other 1 (mem rules --more <topic>, when a topic fits your task)"


def test_mem_rules_more_lists_index_only_lessons(project, gfolder, capsys):
    write("Fits in the block.", short="Fits.", topic="process")
    write("Niche lesson about one kind of work.", short="Niche rule.", topic="docs")
    h = load(gfolder, "global")["Niche lesson about one kind of work."].handle
    assert mem.main(["memory", "edit", f"m:{h}", "--global", "--index-only"]) == 0
    capsys.readouterr()
    assert mem.main(["rules"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 3 and "Niche" not in "".join(out[:2]) and out[-1] == "1 more lesson by topic: docs 1 (mem rules --more <topic>, when a topic fits your task)"
    assert mem.main(["rules", "--more", "docs"]) == 0
    row, closing = capsys.readouterr().out.splitlines()
    assert row.split("\t")[:5] == [f"m:{h}", "global", "index only", "(held in 2 projects)", "docs"]
    assert closing == "mem show m:<handle> prints a whole lesson."


def test_an_index_only_global_lesson_does_not_hide_its_twin_in_the_project():
    base = _base()
    glob = dataclasses.replace(base, scope="global", handle="g", owner_confirmed=TODAY, load="index", topic="ui")
    twin = dataclasses.replace(base, scope="project", handle="p", general="g", owner_confirmed=TODAY)
    choice = rules.choose([twin], [glob], TODAY)
    assert [m.handle for m in choice.loaded] == ["p"]
    assert [(m.handle, why) for m, why in choice.left] == [("g", "index only")]


def test_mem_rules_prints_the_index_line_when_no_rule_loads(project, gfolder, capsys):
    write("Index only lesson about shells.", short="Quote heredoc delimiters.", topic="shell")
    handle = load(gfolder, "global")["Index only lesson about shells."].handle
    assert mem.main(["memory", "edit", f"m:{handle}", "--global", "--index-only"]) == 0
    capsys.readouterr()
    assert mem.main(["rules"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines() == ["No rules loaded.", "1 more lesson by topic: shell 1 (mem rules --more <topic>, when a topic fits your task)"]


def test_mem_rules_says_it_is_switched_off_and_still_prints_what_would_load(project, gfolder, capsys, monkeypatch):
    write("A lesson that would load.", short="A rule that would load.")
    monkeypatch.setenv("MEM_LOADED_RULES", "off")
    capsys.readouterr()
    assert mem.main(["rules"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == "Loaded rules are switched off (plugin option loaded_rules): nothing below loads at session start."
    assert out[1] == rules.HEADER and out[2].startswith("- A rule that would load.")


def test_a_medium_general_lesson_is_released_without_triage_and_a_strong_one_waits(gfolder):
    def remember(claim, weight, sessions):
        args = ["remember", "--global", "--kind", "lesson", "--claim", claim, "--origin", "transcript",
                "--reach", "general", "--weight", weight]
        for s, key in zip(sessions, (K1, K2, K1)):
            args += ["--source", f"session {s} project {key}"]
        assert mem.main(args) == 0

    remember("Medium lesson about retries.", "medium", "ab")
    remember("Strong lesson about retries.", "strong", "abc")
    found = {m.claim: m for m in records.load_memories(gfolder, "global")}
    medium, strong = found["Medium lesson about retries."], found["Strong lesson about retries."]
    assert medium.released and medium.triage is None
    assert strong.released and strong.triage == "pending"


def test_a_released_medium_lesson_loads_once_it_has_a_short_form(gfolder):
    write("Medium lesson with a short form.", short="Medium rule that loads.", weight="medium")
    (m,) = records.load_memories(gfolder, "global")
    assert m.triage is None
    choice = rules.choose([], [m], datetime.date.today())
    assert [x.handle for x in choice.loaded] == [m.handle]
