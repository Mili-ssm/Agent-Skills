"""Characterization of the integrate trial's grading (`evals/integrate/run_trial.py`): `grade` and `totals_verdict`,
on canned snapshots of a store (relative path -> text)."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from syntheses import units

TRIAL = Path(__file__).resolve().parents[3] / "evals" / "integrate" / "run_trial.py"
LINK = "../knowledge/indexing/{}.md"
SYN = "db-indexing"
PART = f"{SYN}#structures"
OTHER_PART = f"{SYN}#selection"
FIRST, SECOND = "First fact.", "Second fact."
MIN_APPEND_SEEDS = 15
USAGE_EXIT = 2


def _load() -> Any:
    spec = importlib.util.spec_from_file_location("integrate_run_trial_under_test", TRIAL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _ref(slug: str) -> str:
    return f"[{slug}]({LINK.format(slug)})"


def _part(*paragraphs: tuple[str, str], members: tuple[str, ...] = ("m1",)) -> str:
    body = "\n\n".join(f"{text}{_ref(slug)}" for text, slug in paragraphs)
    return f"{body}\n\nSources: " + ", ".join(_ref(m) for m in members)


def _synthesis(**parts: str) -> str:
    sections = "\n\n".join(f"## {name.capitalize()}\n\n{text}" for name, text in parts.items())
    return (
        "---\ntitle: Database indexing\ntopics: [indexing]\ncreated: 2026-01-01\n"
        f"updated: 2026-01-01\n---\n\n## Summary\n\nAbout indexes.\n\n{sections}\n"
    )


def _note(
    slug: str, claim: str = "A claim.", part_of: str = "", stamp: str = "", **extra: str
) -> tuple[str, str]:
    lines = [f"claim: {claim}", "topics: [indexing]", "updated: 2026-01-01"]
    lines += [f"{k}: {v}" for k, v in extra.items()]
    if part_of:
        lines += [f"part_of: {part_of}", f'part_of_hash: "{stamp}"']
    text = "---\n" + "\n".join(lines) + f"\n---\n\n## Claim\n\n{claim}\n\n## Evidence\n\nSeen.\n"
    return f"knowledge/indexing/{slug}.md", text


def _store(syn: dict[str, str], *notes: tuple[str, str]) -> dict[str, str]:
    return {f"syntheses/{SYN}.md": _synthesis(**syn), **dict(notes)}


def _seed(*notes: dict) -> dict:
    return {"notes": list(notes)}


def _label(slug: str, label: str, part: str | None = None, sentence: int | None = None) -> dict:
    out: dict = {"slug": slug, "claim": f"claim of {slug}", "label": label}
    if part:
        out["part"] = f"s:{part}"
    if sentence:
        out["sentence"] = sentence
    return out


BASE_PART = _part((FIRST, "m1"), (SECOND, "m1"))
STAMP = units.fingerprint(BASE_PART)


def _member(part_text: str = BASE_PART) -> tuple[str, str]:
    return _note("m1", part_of=PART, stamp=units.fingerprint(part_text))


def _before(*loose: tuple[str, str]) -> dict[str, str]:
    return _store(
        {"structures": BASE_PART, "selection": BASE_PART.replace("m1", "m1")}, _member(), *loose
    )


def _appended(slug: str, claim: str) -> str:
    return BASE_PART.replace("\n\nSources", f"\n\n{claim}{_ref(slug)}\n\nSources")


def _after(*attached: tuple[str, str], part: str = BASE_PART) -> dict[str, str]:
    return _store({"structures": part, "selection": BASE_PART}, _member(part), *attached)


RECORD = {"cost": 0.1, "estimate": {"sessions": 0.2, "audit": 0.05}, "undo_identical": True}


def _grade(trial: Any, before: dict, after: dict, *notes: dict, record: dict | None = None) -> dict:
    return trial.grade(before, after, _seed(*notes), record or RECORD)


def test_grade_counts_wrong_attachment():
    trial = _load()
    loose = [_note(s, f"claim of {s}") for s in ("n-fit", "n-no", "n-away", "n-mode", "n-ok")]
    notes = (
        _label("n-fit", "on-topic-no-fit"),
        _label("n-no", "superseded"),
        _label("n-away", "append", OTHER_PART),
        _label("n-mode", "belongs-existing-sentence", PART, 1),
        _label("n-ok", "append", PART),
    )
    claim = "claim of n-ok."
    attached = [
        _note("n-fit", part_of=PART, stamp="x"),
        _note("n-no", part_of=PART, stamp="x"),
        _note("n-away", part_of=PART, stamp="x"),
        _note("n-mode", part_of=PART, stamp="x"),
        _note("n-ok", part_of=PART, stamp="x"),
    ]
    part = _appended("n-ok", claim).replace(
        "\n\nSources", f"\n\nOther.{_ref('n-away')} More.{_ref('n-mode')}\n\nSources"
    )
    graded = _grade(trial, _before(*loose), _after(*attached, part=part), *notes)
    assert {w["note"] for w in graded["wrong_attachments"]} == {"n-fit", "n-no", "n-away", "n-mode"}
    assert graded["by_label"]["append"] == {"seeded": 2, "attached": 2, "wrong": 1}


def test_grade_reports_a_wrong_sentence_apart_from_wrong_attachments():
    trial = _load()
    before = _before(_note("n-dup", FIRST))
    cited = BASE_PART.replace(f"{SECOND}{_ref('m1')}", f"{SECOND}{_ref('m1')}{_ref('n-dup')}")
    after = _after(_note("n-dup", FIRST, part_of=PART, stamp="x"), part=cited)
    graded = _grade(trial, before, after, _label("n-dup", "duplicate-of-existing", PART, 1))
    assert graded["wrong_attachments"] == []
    assert [w["note"] for w in graded["wrong_sentences"]] == ["n-dup"]
    verdict = trial.totals_verdict(graded)
    assert verdict["verdict"].startswith("kill") and "wrong attachment" in verdict["verdict"]
    (wrong,) = (c for c in verdict["criteria"] if c["name"] == "wrong attachment")
    assert wrong["count"] == 1 and wrong["ok"] is False


def test_grade_lists_appended_sentences_with_their_notes():
    trial = _load()
    before = _before(_note("n-1", "Claim one."))
    after = _after(
        _note("n-1", "Claim one.", part_of=PART, stamp="x"), part=_appended("n-1", "Claim one.")
    )
    graded = _grade(trial, before, after, _label("n-1", "append", PART))
    assert graded["appended"] == [{"part": PART, "sentence": "Claim one.", "notes": ["n-1"]}]
    assert graded["wrong_attachments"] == []


def test_grade_flags_another_note_change_outside_allowed_fields():
    trial = _load()
    assert frozenset({"updated", "part_of_hash"}) == trial.ALLOWED_OTHER_FIELDS
    before = _before(_note("loose", "Loose claim."), _note("quiet", "Quiet claim."))
    member = "knowledge/indexing/m1.md"
    restamped = before[member].replace("updated: 2026-01-01", "updated: 2026-02-02")
    restamped = re.sub(r'part_of_hash: ".*"', 'part_of_hash: "0000"', restamped)
    assert _grade(trial, before, {**before, member: restamped})["other_changes"] == []
    changed = {
        **before,
        "knowledge/indexing/quiet.md": before["knowledge/indexing/quiet.md"].replace(
            "claim: Quiet claim.", "claim: Another claim.", 1
        ),
        "knowledge/indexing/loose.md": before["knowledge/indexing/loose.md"] + "\nAn edit.\n",
        member: before[member].replace("topics:", "confidence: high\ntopics:"),
    }
    found = _grade(trial, before, changed)["other_changes"]
    assert {c["note"]: c["fields"] for c in found} == {
        "quiet": ["claim"],
        "loose": ["body"],
        "m1": ["confidence"],
    }


def test_grade_flags_stale_to_current_without_part_change():
    trial = _load()
    stale = _note("m1", part_of=PART, stamp="not-the-part")
    before = {**_before(), stale[0]: stale[1]}
    restamped = {**before, stale[0]: _member()[1]}
    graded = _grade(trial, before, restamped)
    assert graded["stale_to_current"] == ["m1"]
    changed_part = _appended("m1", "New claim.")
    after = _after(part=changed_part)
    assert (
        _grade(trial, before, after)["stale_to_current"] == []
    )  # its part changed: a re-stamp may follow


def _graded(**changes: Any) -> dict:
    ok = {
        "seeded": 33,
        "append_labelled": 17,
        "wrong_attachments": [],
        "other_changes": [],
        "stale_to_current": [],
        "undo_identical": True,
        "integrated": 20,
        "run_failures": [],
        "cost": 0.1,
        "estimate": {"sessions": 0.2, "audit": 0.05},
    }
    return {**ok, **changes}


def _by_name(result: dict) -> dict:
    return {c["name"]: c for c in result["criteria"]}


def test_totals_verdict_kills_on_one_wrong_attachment():
    trial = _load()
    assert trial.totals_verdict(_graded(), unbacked=0, audit_cost=0.05)["verdict"] == "pass"
    bad = trial.totals_verdict(_graded(wrong_attachments=[{"note": "n"}]), unbacked=0)
    assert bad["verdict"].startswith("kill") and _by_name(bad)["wrong attachment"] == {
        "name": "wrong attachment",
        "count": 1,
        "ok": False,
    }


def test_totals_verdict_each_other_criterion():
    trial = _load()
    cases = {
        "seed size": _graded(seeded=29),
        "append share": _graded(append_labelled=14),
        "another note changed": _graded(other_changes=[{"note": "x"}]),
        "stale to current": _graded(stale_to_current=["x"]),
        "undo": _graded(undo_identical=False),
        "cost": _graded(cost=0.46),
    }
    for name, graded in cases.items():
        result = trial.totals_verdict(graded, unbacked=0, audit_cost=0.05)
        assert result["verdict"].startswith("kill") and _by_name(result)[name]["ok"] is False, name
    assert trial.totals_verdict(_graded(), unbacked=2)["verdict"].startswith("kill")
    assert trial.totals_verdict(_graded(), unbacked=1, audit_cost=0.05)["verdict"] == "pass"


def test_totals_verdict_waits_for_the_audit():
    trial = _load()
    result = trial.totals_verdict(_graded())
    assert (
        result["verdict"].startswith("pending")
        and _by_name(result)["unbacked sentences"]["ok"] is None
    )
    killed = trial.totals_verdict(_graded(wrong_attachments=[{"note": "n"}]))
    assert killed["verdict"].startswith("kill")  # a failed criterion needs no audit


def test_cost_bar_holds_the_sessions_alone_until_the_audit_cost_is_known():
    trial = _load()
    open_bar = trial.totals_verdict(_graded(), unbacked=0)
    assert open_bar["verdict"] == "pending: cost" and _by_name(open_bar)["cost"]["ok"] is None
    over = trial.totals_verdict(
        _graded(cost=0.41), unbacked=0
    )  # twice the sessions estimate is 0.40
    assert over["verdict"] == "kill: cost"


def test_cost_bar_closes_on_the_total_against_twice_the_sum():
    trial = _load()  # sessions 0.2 + audit 0.05: the bar is 0.50
    assert trial.totals_verdict(_graded(cost=0.4), unbacked=0, audit_cost=0.1)["verdict"] == "pass"
    late = trial.totals_verdict(_graded(cost=0.4), unbacked=0, audit_cost=0.11)
    assert late["verdict"] == "kill: cost" and _by_name(late)["cost"]["count"] == pytest.approx(
        0.51
    )


def test_an_audit_estimate_is_sized_from_the_listing_not_the_seed_file():
    trial = _load()
    seed = trial.load_seed()
    listing = trial.expected_listing(seed)
    appended = [e for e in seed["notes"] if e["label"] == "append"]
    assert listing.count("### Item ") == len(appended) > MIN_APPEND_SEEDS
    both = trial.estimates(seed, 0.1)
    assert (
        both["sessions"] == pytest.approx(0.1) and both["total"] == both["sessions"] + both["audit"]
    )
    prompt = trial.AUDIT_PROMPT.format(items=listing)
    assert both["audit"] == trial.audit_estimate_usd(prompt, len(appended))


def test_the_audit_is_estimated_as_one_request_not_two_sessions():
    trial = _load()
    prompt = "x" * 6_000  # 1,500 tokens
    tokens = 1_500 + trial.AUDIT_OVERHEAD_TOKENS
    haiku = (
        tokens * trial.HAIKU_INPUT_PER_MTOK
        + 17 * trial.AUDIT_OUTPUT_TOKENS_PER_SENTENCE * trial.HAIKU_OUTPUT_PER_MTOK
    ) / trial.MILLION
    got = trial.audit_estimate_usd(prompt, 17)
    assert got == pytest.approx(haiku * trial.sonnet_price_ratio())
    two_sessions = 2 * trial.session_usd(1_500, trial.sonnet_price_ratio())
    assert got < two_sessions / 5  # the old shape came out near 1.5 USD for this prompt


def test_a_sessions_overrun_is_not_masked_by_a_cheap_audit():
    trial = _load()  # sessions bar 0.40, total bar 0.50
    masked = trial.totals_verdict(_graded(cost=0.41), unbacked=0, audit_cost=0.0)
    assert masked["verdict"] == "kill: cost"  # the total 0.41 is under 0.50
    inside = trial.totals_verdict(_graded(cost=0.40), unbacked=0, audit_cost=0.1)
    assert inside["verdict"] == "pass"


AUDIT_OK = "1 | backed | stated\n2 | not backed | adds a claim\n3 | backed | follows\n"


def test_parse_audit_reply_counts_the_not_backed_lines():
    trial = _load()
    assert trial.parse_audit_reply(AUDIT_OK + "\n", 3) == 1
    assert trial.parse_audit_reply("", 0) == 0


@pytest.mark.parametrize(
    ("reply", "fragment"),
    [
        ("1 | backed | a\n3 | backed | c\n", "sentence 2"),
        (AUDIT_OK + "4 | backed | d\n", "sentence 4"),
        (AUDIT_OK + "2 | backed | again\n", "two audit lines for sentence 2"),
        ("1 | backed | a\n2 | maybe | b\n3 | backed | c\n", "malformed"),
        ("1 | backed |\n2 | backed | b\n3 | backed | c\n", "malformed"),
        ("Item 1 is fine\n", "malformed"),
    ],
)
def test_parse_audit_reply_refuses_anything_else(reply, fragment):
    trial = _load()
    with pytest.raises(ValueError, match=fragment):
        trial.parse_audit_reply(reply, 3)


def test_a_run_with_a_failed_session_is_void_not_a_pass():
    trial = _load()
    result = trial.totals_verdict(
        _graded(run_failures=["alpha: the session failed"]), unbacked=0, audit_cost=0.05
    )
    assert result["verdict"] == "void: run failures: alpha: the session failed"


def test_a_run_that_integrated_nothing_is_void_not_a_pass():
    trial = _load()
    result = trial.totals_verdict(_graded(integrated=0), unbacked=0, audit_cost=0.05)
    assert result["verdict"] == "void: no note was integrated"


def test_a_kill_that_fired_is_shown_before_a_void_run():
    trial = _load()
    result = trial.totals_verdict(
        _graded(wrong_attachments=[{"note": "n"}], run_failures=["alpha: the session failed"]),
        unbacked=0,
        audit_cost=0.05,
    )
    assert result["verdict"] == "kill: wrong attachment"


def test_undo_comparison_skips_the_git_folder_and_the_curation_log_only(tmp_path):
    trial = _load()
    for rel, text in {
        ".gitignore": "x",
        ".git/HEAD": "y",
        ".curation-log": "z",
        "knowledge/a/.curation-log": "z",
        ".gitattributes": "w",
        "knowledge/a/n.md": "n",
    }.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    assert set(trial.file_bytes(tmp_path)) == {".gitignore", ".gitattributes", "knowledge/a/n.md"}


def test_a_note_cited_in_a_part_its_label_does_not_allow_is_wrong_whatever_part_of_says():
    trial = _load()
    before = _before(_note("n-away", "Away claim."), _note("n-never", "Never claim."))
    stray = BASE_PART.replace(
        "\n\nSources", f"\n\nAway claim.{_ref('n-away')} Never claim.{_ref('n-never')}\n\nSources"
    )
    after = _store(
        {"structures": _appended("n-away", "Away claim."), "selection": stray},
        _member(BASE_PART),
        _note("n-away", "Away claim.", part_of=PART, stamp="x"),
        _note("n-never", "Never claim."),  # no part_of: only its citation shows
    )
    graded = _grade(
        trial,
        before,
        after,
        _label("n-away", "append", PART),
        _label("n-never", "on-topic-no-fit"),
    )
    found = {w["note"]: w["why"] for w in graded["wrong_attachments"]}
    assert set(found) == {"n-away", "n-never"}
    assert OTHER_PART in found["n-away"] and OTHER_PART in found["n-never"]


def test_another_note_is_compared_by_raw_bytes_and_a_created_note_is_reported():
    trial = _load()
    before = _before(_note("quiet", "Quiet claim."))
    path = "knowledge/indexing/quiet.md"
    crlf = before[path].replace("\n", "\r\n")
    found = _grade(trial, before, {**before, path: crlf})["other_changes"]
    assert [(c["note"], c["fields"]) for c in found] == [("quiet", ["body"])]
    created = _grade(trial, before, {**before, **dict([_note("surprise", "New.")])})[
        "other_changes"
    ]
    assert [(c["note"], c["fields"]) for c in created] == [("surprise", ["created"])]


def test_snapshot_keeps_the_line_endings_on_disk(tmp_path):
    trial = _load()
    (tmp_path / "knowledge" / "t").mkdir(parents=True)
    (tmp_path / "knowledge" / "t" / "n.md").write_bytes(b"---\r\nclaim: x\r\n---\r\n\r\nBody\r\n")
    assert trial.snapshot(tmp_path)["knowledge/t/n.md"].endswith("Body\r\n")


def test_seed_handles_describe_the_subject_only():
    trial = _load()
    seed = trial.load_seed()
    hints = {
        "dup",
        "same",
        "nofit",
        "wrong",
        "stale",
        "old",
        "disputed",
        "duplicate",
        "superseded",
        "append",
        "fit",
    }
    handles = [n["slug"] for n in (*seed["members"], *seed["notes"])]
    assert len(handles) == len(set(handles))
    assert [h for h in handles if hints & set(h.split("-"))] == []


def test_seed_keeps_its_label_counts():
    trial = _load()
    labels = [n["label"] for n in trial.load_seed()["notes"]]
    minimum = {"append": 16, "belongs-existing-sentence": 5, "duplicate-of-existing": 3}
    minimum |= {"on-topic-no-fit": 4, "superseded": 2, "disputed": 2}
    assert all(labels.count(k) >= v for k, v in minimum.items()), minimum


def test_verdict_command_closes_a_saved_result(tmp_path, capsys):
    trial = _load()
    graded = _graded(
        by_label={label: {"seeded": 1, "attached": 1, "wrong": 0} for label in trial.LABELS},
        appended=[],
        wrong_sentences=[],
        undo_differences=[],
    )
    saved = {
        **graded,
        "run": {"run_id": "r1", "failures": []},
        "verdict": "pending: unbacked sentences",
    }
    path = tmp_path / "result.json"
    path.write_text(json.dumps(saved), encoding="utf-8")
    reply = tmp_path / "reply.txt"
    reply.write_text("", encoding="utf-8")  # no sentence appended: nothing to audit
    assert (
        trial.main(["verdict", str(path), "--audit-reply", str(reply), "--audit-cost", "0.05"]) == 0
    )
    assert capsys.readouterr().out.strip().endswith("verdict: pass")
    saved["appended"] = [{"part": PART, "sentence": f"S{n}.", "notes": []} for n in (1, 2, 3)]
    path.write_text(json.dumps(saved), encoding="utf-8")
    reply.write_text("1 | not backed | a\n2 | not backed | b\n3 | backed | c\n", encoding="utf-8")
    assert trial.main(["verdict", str(path), "--audit-reply", str(reply)]) == 0
    assert capsys.readouterr().out.strip().endswith("verdict: kill: unbacked sentences")
    reply.write_text("1 | backed | a\n3 | backed | c\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exit_info:
        trial.main(["verdict", str(path), "--audit-reply", str(reply)])
    assert exit_info.value.code == USAGE_EXIT
    assert "sentence 2" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        trial.main(["verdict", str(path)])  # --audit-reply is required


@pytest.mark.parametrize("bad", ["-1", "nan", "inf", "abc"])
def test_number_arguments_must_be_finite_and_not_negative(tmp_path, bad):
    trial = _load()
    path = tmp_path / "result.json"
    path.write_text("{}", encoding="utf-8")
    reply = tmp_path / "reply.txt"
    reply.write_text("", encoding="utf-8")
    with pytest.raises(SystemExit) as exit_info:
        trial.main(["verdict", str(path), "--audit-reply", str(reply), "--audit-cost", bad])
    assert exit_info.value.code == USAGE_EXIT
    with pytest.raises(SystemExit) as exit_info:
        trial.main(["--budget", bad, "--claude", "x"])
    assert exit_info.value.code == USAGE_EXIT


def test_a_paid_run_that_raises_saves_what_it_spent_and_fails(tmp_path, monkeypatch, capsys):
    trial = _load()
    snaps = iter([{}])

    def snap(_store):
        try:
            return next(snaps)
        except StopIteration:
            raise RuntimeError("boom") from None

    ran = subprocess.CompletedProcess([], 0, "cost: 0.5 USD of 1.0; run r1\nfailed: alpha\n", "")
    monkeypatch.setattr(trial, "build_store", lambda *_: tmp_path)
    monkeypatch.setattr(trial, "dry_run", lambda *_: {"estimate": 0.1})
    monkeypatch.setattr(trial, "snapshot", snap)
    monkeypatch.setattr(trial, "_integrate", lambda *_a: ran)
    args = argparse.Namespace(claude="x", budget=1.0, runner="claude", out=tmp_path / "out")
    assert trial.cmd_paid(args) == 1
    (saved,) = (tmp_path / "out").glob("integrate-failed-*.json")
    data = json.loads(saved.read_text(encoding="utf-8"))
    assert data["cost"] == pytest.approx(0.5) and data["failures"] == ["alpha"]
    assert "boom" in data["error"] and data["run_id"] == "r1"
    assert "boom" in capsys.readouterr().err


TOKENS = 777


def test_a_codex_run_reports_tokens_instead_of_cost(tmp_path, monkeypatch):
    trial = _load()
    seen: list[tuple] = []

    def fake(_env, _store, *args):
        seen.append(args)
        return subprocess.CompletedProcess(
            [], 0, f"tokens: {TOKENS} of 500000 (codex); run r2\n", ""
        )

    monkeypatch.setattr(trial, "_integrate", fake)
    spent: dict = {}
    run = trial.run_integrate({}, tmp_path, ("", 1.0, "codex"), spent)
    assert run["tokens"] == TOKENS and run["cost"] == pytest.approx(0.0) and run["run_id"] == "r2"
    assert seen[0][seen[0].index("--runner") + 1] == "codex"
