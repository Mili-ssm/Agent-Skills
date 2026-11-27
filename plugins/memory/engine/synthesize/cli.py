"""The command line of `mem-synthesize`: argument parser, `main` and the self-check."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from core import codex_pass
from core import runner as runners

from synthesize import backfill, run, topics
from synthesize import pipeline as sp


def _check_parsers() -> None:
    curate = (
        "2 memories seen several times\n  foo\n\ntopics with 8 notes or more and no synthesis (mem synthesis new)\n"
        "  alpha-beta  26 notes\n  gamma  9 notes\nnotes to unify\n  delta  4 notes\n"
    )
    assert run.topics_without_synthesis(curate) == ["alpha-beta", "gamma"], (
        run.topics_without_synthesis(curate)
    )
    answer = "Slug: x\nATTACH\nknowledge/a/b.md\ts:x#part-one\nknowledge/a/c.md  s:x#bad\nliterature/z.md\ts:x#p\n"
    assert run.attach_lines(answer) == [("knowledge/a/b.md", "s:x#part-one")], run.attach_lines(
        answer
    )
    assert (
        "/plugins/cache/" not in run.session_env(Path("/x"))["PATH"]
        and run.session_env(Path("/x"))["MEM_STORE"] == "/x"
    )
    rows = [
        {
            **topics.new_row("t"),
            "parts": 5,
            "attached": 7,
            "fixed": 2,
            "deleted": 1,
            "refs": 4,
            "mem_check": 0,
            "cost": 0.31,
        }
    ]
    assert topics.table(rows).splitlines()[1].split()[:3] == ["t", "5", "7"], topics.table(rows)


def _init_store(store: Path, env: dict) -> None:
    assert (
        subprocess.run(
            [str(sp.MEM), "init", str(store)], env=env, capture_output=True, check=False
        ).returncode
        == 0
    )
    assert (
        subprocess.run(
            [str(sp.MEM), "history", "init"],
            env={**env, "MEM_STORE": str(store)},
            cwd=store,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def _check_dry_runs(store: Path, tmp: Path) -> None:
    lines: list[str] = []
    assert topics.run(None, store, ["one", "two"], 3.0, True, out=lines.append) == 0
    assert "2 topics" in lines[0] and "1.10 USD" in lines[0] and "reference step" in lines[0], lines
    lines.clear()
    assert (
        topics.run(None, store, ["one", "two"], 3.0, True, out=lines.append, references=False) == 0
    )
    assert "1.00 USD" in lines[0] and "no reference step" in lines[0], lines
    lines.clear()
    assert topics.run(None, store, ["one", "two"], 3.0, True, out=lines.append) == 0
    assert not (tmp / "data").exists(), "a dry run wrote something"


def _commit_all(store: Path, message: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=store, check=True)
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", message],
        cwd=store,
        check=True,
    )


# What the fake session writes: it must pass `mem check`, or the store's commit gate holds it back.
FAKE_NOTE = """---
claim: A fake session wrote this
topics: [notes]
confidence: low
level: basic
origin: experience
updated: 2026-11-26
---

## Claim

x

## Evidence

x

## Applies when

x

## Does not apply when

x
"""


def _fake_claude(tmp: Path, store: Path) -> Path:
    """A `claude` that writes a valid note into the store and stops; the store gets a committed fixture."""
    fake = tmp / "fake-claude"
    fake.write_text(
        '#!/bin/sh\nmkdir -p "$MEM_STORE/knowledge/notes"\ncat > "$MEM_STORE/knowledge/notes/touched.md" <<\'EOF\'\n'
        + FAKE_NOTE
        + 'EOF\necho \'{"type":"result","is_error":false,"result":"STOP: fake","total_cost_usd":0.0}\'\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    (store / "knowledge").mkdir(exist_ok=True)
    (store / "knowledge" / "keep.md").write_text("kept\n", encoding="utf-8")
    _commit_all(store, "fixture")
    return fake


def _check_guard(store: Path, env: dict) -> None:
    """The out-of-scope guard: a fake fixer edits two parts, the report lists one; the other is put back."""
    os.environ["MEM_STORE"] = str(store)
    assert (
        sp.mem(
            store,
            env,
            "synthesis",
            "new",
            "--title",
            "Demo",
            "--topics",
            "notes",
            "--slug",
            "demo",
            "--summary-file",
            "-",
            stdin="Summary.\n",
        ).returncode
        == 0
    )
    for heading in ("Alpha", "Beta"):
        added = sp.mem(
            store,
            env,
            "synthesis",
            "add",
            "s:demo",
            "--section",
            heading,
            "--body-file",
            "-",
            stdin=f"{heading} text one. Second sentence here.\n\nSources: experience 2026-11-17\n",
        )
        assert added.returncode == 0, added.stderr
    demo = store / "syntheses" / "demo.md"
    before = demo.read_text(encoding="utf-8")
    demo.write_text(
        before.replace("Alpha text one.", "Alpha fixed.").replace("Second sentence here.", "Cut."),
        encoding="utf-8",
    )
    after = demo.read_text(encoding="utf-8")
    bad, back = sp.guard_parts(store, env, "demo", before, after, allowed=["alpha"])
    assert (bad, back) == (["beta"], ["beta"]), (bad, back)
    now = sp.split_parts(demo.read_text(encoding="utf-8"))
    assert (
        now["beta"].strip() == sp.split_parts(before)["beta"].strip()
        and "Alpha fixed." in now["alpha"]
    ), now
    checked = sp.mem(store, env, "check")
    assert "demo.md" not in checked.stdout, checked.stdout  # keep.md above is not a note
    assert (
        sp.mem(store, env, "restore", "s:demo").returncode == 0
    )  # the revert is one undoable step
    assert sp.guard_parts(store, env, "demo", before, before, allowed=[])[0] == []
    os.environ.pop("MEM_STORE", None)


def _check_fake_run(store: Path, fake: Path, env: dict) -> None:
    lines: list[str] = []
    assert topics.run(str(fake), store, ["one", "two"], 3.0, False, out=lines.append) == 1
    assert (
        "failed: STOP: fake" in lines[1]
        and lines[1].count("failed") == run.FAILED_WORDS_PER_FAKE_ROW
    ), lines
    assert (store / "knowledge" / "keep.md").read_text(encoding="utf-8") == "kept\n"
    log = subprocess.run(
        ["git", "log", "--format=%s"], cwd=store, capture_output=True, text=True, check=False
    ).stdout
    assert "mem-synthesize: after one, two" in log and "mem-synthesize: before" not in log, (
        log
    )  # only a change commits
    shown = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=store,
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    assert "knowledge/notes/touched.md" in shown.splitlines(), shown  # not held back
    checked = sp.mem(store, env, "check")
    report = checked.stdout + checked.stderr
    # keep.md is a fixture finding: seeing it proves `mem check` ran; only the fake's note must be clean
    assert "knowledge/keep.md" in report and "notes/touched.md" not in report, report


def self_check() -> int:
    """No model: parsers, the dry run, and a whole run with a fake `claude` that writes a valid note and stops
    (every topic fails, the run goes on, the closing commit holds the note, `mem check` reports nothing on it, the store keeps its content)."""
    _check_parsers()
    with tempfile.TemporaryDirectory(prefix="mem-synthesize-check-") as tmp_name:
        tmp = Path(tmp_name)
        store = tmp / "store"
        env = {**os.environ, "MEM_DATA": str(tmp / "data")}
        _init_store(store, env)
        os.environ["MEM_DATA"] = str(tmp / "data")
        _check_dry_runs(store, tmp)
        fake = _fake_claude(tmp, store)
        _check_guard(store, env)
        _commit_all(store, "demo")
        _check_fake_run(store, fake, env)
    print("self-check passed")
    return 0


def _parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description.splitlines()[0])
    parser.add_argument(
        "--backfill",
        nargs="*",
        metavar="s:HANDLE",
        help="add inline references to existing "
        "syntheses (the named ones, or all) with one read-only session each",
    )
    parser.add_argument(
        "--topic",
        action="append",
        default=[],
        help="topic id (repeatable; default: the topics "
        "`mem curate --notes` lists without a synthesis)",
    )
    parser.add_argument(
        "--budget", type=float, default=3.0, help="USD; no new topic starts past it"
    )
    parser.add_argument(
        "--no-references",
        action="store_true",
        help="skip the last step of a topic (adding inline references with the --backfill session)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="list the topics and the estimated cost; run nothing"
    )
    parser.add_argument(
        "--store", type=Path, help="default: the store `mem` resolves (MEM_STORE, else the default)"
    )
    parser.add_argument(
        "--claude", default=os.environ.get("CLAUDE_CODE_EXECPATH") or shutil.which("claude")
    )
    runners.add_flag(parser)
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="no model: prove the parsers and a run with a fake claude",
    )
    return parser


def _check_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.backfill is not None and args.topic:
        parser.error("--backfill takes synthesis handles (s:<handle>), not --topic")
    if args.backfill is not None and args.no_references:
        parser.error("--no-references applies to writing syntheses, not to --backfill")
    if args.backfill is not None and args.self_check:
        parser.error("--backfill takes synthesis handles (s:<handle>), not --self-check")


def main(description: str) -> int:
    parser = _parser(description)
    args = parser.parse_args()
    _check_args(parser, args)
    if args.self_check:
        return self_check()
    if (refused := codex_pass.refuse_codex("mem-synthesize", args.runner)) is not None:
        return refused
    store = args.store.expanduser().resolve() if args.store else run.default_store()
    if store is None or not (store / "mem-store.yaml").is_file():
        print(f"mem-synthesize: no writable store at {store}", file=sys.stderr)
        return 2
    if args.backfill is not None:
        return backfill.run_backfill(args.claude, store, args.backfill, args.budget, args.dry_run)
    return topics.run(
        args.claude, store, args.topic, args.budget, args.dry_run, references=not args.no_references
    )
